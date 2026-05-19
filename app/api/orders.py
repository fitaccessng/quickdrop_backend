import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_rider, get_current_user, get_current_vendor, get_db_session
from app.core.config import settings
from app.core.security import decode_access_token
from app.models.order import Order, OrderItem
from app.models.order import OrderStatus
from app.models.user import User
from app.models.vendor import Vendor
from app.schemas.order import (
    CheckoutInitializationResponse,
    CheckoutRequest,
    CheckoutQuoteResponse,
    CheckoutResponse,
    OrderResponse,
    OrderStatusResponse,
    RiderSummary,
    VendorOrderResponse,
    VendorOrderStatusUpdate,
)
from app.services.orders import (
    build_checkout_quote,
    build_order_status_response,
    build_order_tracking_snapshot,
    build_timeline,
    create_checkout,
    get_order_with_relations,
    get_orders_for_user,
)
from app.services.paystack import initialize_paystack_transaction, verify_paystack_signature, verify_paystack_transaction
from app.services.notifications import create_notification
from app.services.order_realtime import order_realtime_manager

router = APIRouter(prefix="/orders", tags=["orders"])

vendor_order_options = (
    selectinload(Order.user),
    selectinload(Order.rider),
    selectinload(Order.address),
    selectinload(Order.items).selectinload(OrderItem.product),
)


async def _send_order_socket_payload(websocket: WebSocket, payload: dict) -> bool:
    try:
        await websocket.send_text(json.dumps(payload, default=str))
        return True
    except (WebSocketDisconnect, RuntimeError):
        return False


async def broadcast_order_state(session: AsyncSession, order_id: int, event: str = "order.updated") -> None:
    payload = await build_order_status_response(session, order_id)
    if not payload:
        return
    await order_realtime_manager.broadcast(
        str(order_id),
        {"event": event, "order": payload.model_dump(mode="json")},
    )


async def serialize_order(order) -> OrderResponse:
    tracking = await build_order_tracking_snapshot(order)
    return OrderResponse(
        id=order.id,
        order_reference=order.order_reference,
        status=order.status,
        subtotal_amount=order.subtotal_amount,
        delivery_fee=order.delivery_fee,
        total_amount=order.total_amount,
        payment_method=order.payment_method,
        payment_status=order.payment_status,
        payment_reference=order.payment_reference,
        tracking_note=order.tracking_note,
        created_at=order.created_at,
        updated_at=order.updated_at,
        vendor=order.vendor,
        customer=order.user,
        rider=order.rider,
        address=order.address,
        destination_latitude=order.address.latitude if order.address else None,
        destination_longitude=order.address.longitude if order.address else None,
        tracking_latitude=tracking["tracking_latitude"],
        tracking_longitude=tracking["tracking_longitude"],
        rider_location=tracking["rider_location"],
        route_geometry=tracking["route_geometry"],
        distance_meters_remaining=tracking["distance_meters_remaining"],
        duration_seconds_remaining=tracking["duration_seconds_remaining"],
        estimated_arrival_seconds=tracking["estimated_arrival_seconds"],
        items=[
            {
                "id": item.id,
                "product_id": item.product_id,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "total_price": item.total_price,
                "notes": item.notes,
                "product_name": item.product.name,
            }
            for item in order.items
        ],
    )


async def serialize_vendor_order(order) -> VendorOrderResponse:
    tracking = await build_order_tracking_snapshot(order)
    return VendorOrderResponse(
        id=order.id,
        order_reference=order.order_reference,
        status=order.status,
        subtotal_amount=order.subtotal_amount,
        delivery_fee=order.delivery_fee,
        total_amount=order.total_amount,
        payment_method=order.payment_method,
        payment_status=order.payment_status,
        payment_reference=order.payment_reference,
        tracking_note=order.tracking_note,
        created_at=order.created_at,
        updated_at=order.updated_at,
        customer=order.user,
        rider=order.rider,
        address=order.address,
        destination_latitude=order.address.latitude if order.address else None,
        destination_longitude=order.address.longitude if order.address else None,
        tracking_latitude=tracking["tracking_latitude"],
        tracking_longitude=tracking["tracking_longitude"],
        rider_location=tracking["rider_location"],
        route_geometry=tracking["route_geometry"],
        distance_meters_remaining=tracking["distance_meters_remaining"],
        duration_seconds_remaining=tracking["duration_seconds_remaining"],
        estimated_arrival_seconds=tracking["estimated_arrival_seconds"],
        items=[
            {
                "id": item.id,
                "product_id": item.product_id,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "total_price": item.total_price,
                "notes": item.notes,
                "product_name": item.product.name,
            }
            for item in order.items
        ],
    )

def _frontend_hash_url(path: str) -> str:
    base = settings.frontend_origin.rstrip("/")
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{base}/#{normalized_path}"


async def _hydrate_checkout_response(
    session: AsyncSession,
    orders: list[Order],
    current_user: User,
) -> CheckoutResponse:
    hydrated_orders = []

    for order in orders:
        hydrated = await get_order_with_relations(session, order.id, current_user.id)
        if hydrated:
            await create_notification(
                session,
                recipient_role="vendor",
                recipient_vendor_id=hydrated.vendor_id,
                title="New order received",
                message=f"Order {hydrated.order_reference} was placed by {current_user.full_name}.",
                category="order",
                action_url="/vendor/orders",
            )
            await create_notification(
                session,
                recipient_role="admin",
                title="New customer order",
                message=f"Order {hydrated.order_reference} entered the system.",
                category="order",
                action_url="/admin/orders",
            )
            hydrated_orders.append(await serialize_order(hydrated))

    return CheckoutResponse(
        order_reference=orders[0].order_reference if orders else "",
        orders=hydrated_orders,
        total_amount=sum(order.total_amount for order in hydrated_orders),
    )


async def _create_or_fetch_paystack_orders(
    session: AsyncSession,
    current_user: User,
    verified_transaction: dict,
) -> CheckoutResponse:
    reference = verified_transaction.get("reference")
    metadata = verified_transaction.get("metadata") or {}
    checkout_payload = metadata.get("quickdrop_checkout")
    expected_user_id = metadata.get("quickdrop_user_id")

    if not reference or not checkout_payload:
        raise ValueError("Paystack transaction metadata is incomplete.")
    if str(expected_user_id) != str(current_user.id):
        raise ValueError("Paystack transaction does not belong to this user.")

    existing_result = await session.execute(
        select(Order)
        .where(Order.payment_reference == reference, Order.user_id == current_user.id)
        .options(*vendor_order_options)
        .order_by(Order.created_at.asc())
    )
    existing_orders = list(existing_result.scalars().all())
    if existing_orders:
        return CheckoutResponse(
            order_reference=existing_orders[0].order_reference,
            orders=[await serialize_order(order) for order in existing_orders],
            total_amount=sum(order.total_amount for order in existing_orders),
        )

    quote_payload = CheckoutRequest(
        address_id=checkout_payload["address_id"],
        address_latitude=checkout_payload.get("address_latitude"),
        address_longitude=checkout_payload.get("address_longitude"),
        payment_method="paystack",
        payment_reference=reference,
        items=checkout_payload["items"],
    )
    quote = await build_checkout_quote(session, current_user.id, quote_payload)
    expected_amount = int(round(quote.total_amount * 100))
    paid_amount = int(verified_transaction.get("amount") or 0)
    if paid_amount != expected_amount:
        raise ValueError("Verified Paystack amount does not match the expected order total.")

    _order_reference, created_orders = await create_checkout(session, current_user.id, quote_payload)
    return await _hydrate_checkout_response(session, created_orders, current_user)


@router.post("", response_model=CheckoutResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: CheckoutRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> CheckoutResponse:
    try:
        order_reference, orders = await create_checkout(session, current_user.id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    response = await _hydrate_checkout_response(session, orders, current_user)
    return response.model_copy(update={"order_reference": order_reference})


@router.post("/paystack/initialize", response_model=CheckoutInitializationResponse, status_code=status.HTTP_200_OK)
async def initialize_checkout_payment(
    payload: CheckoutRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> CheckoutInitializationResponse:
    quote = await build_checkout_quote(session, current_user.id, payload)
    amount = int(round(quote.total_amount * 100))
    reference = f"QDPS-{uuid4().hex[:18].upper()}"
    callback_url = str(request.url_for("paystack_callback"))

    try:
        initialized = await initialize_paystack_transaction(
            {
                "email": current_user.email,
                "amount": str(amount),
                "currency": "ZAR",
                "reference": reference,
                "callback_url": callback_url,
                "metadata": {
                    "quickdrop_user_id": current_user.id,
                    "quickdrop_checkout": payload.model_dump(mode="json"),
                },
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to initialize Paystack payment right now.") from exc

    return CheckoutInitializationResponse(
        authorization_url=initialized["authorization_url"],
        access_code=initialized["access_code"],
        reference=initialized["reference"],
    )


@router.get("/paystack/callback", name="paystack_callback")
async def paystack_callback(
    reference: str = Query(..., min_length=6, max_length=120),
    session: AsyncSession = Depends(get_db_session),
) -> RedirectResponse:
    try:
        verified = await verify_paystack_transaction(reference)
        if verified.get("status") != "success":
            return RedirectResponse(_frontend_hash_url(f"/checkout?payment=failed&reference={reference}"), status_code=302)

        metadata = verified.get("metadata") or {}
        user_id = metadata.get("quickdrop_user_id")
        current_user = await session.get(User, int(user_id)) if user_id else None
        if not current_user:
            return RedirectResponse(_frontend_hash_url(f"/checkout?payment=failed&reference={reference}"), status_code=302)

        checkout_response = await _create_or_fetch_paystack_orders(session, current_user, verified)
        first_order = checkout_response.orders[0] if checkout_response.orders else None
        if not first_order:
            return RedirectResponse(_frontend_hash_url(f"/checkout?payment=failed&reference={reference}"), status_code=302)

        return RedirectResponse(_frontend_hash_url(f"/tracking/{first_order.id}"), status_code=302)
    except Exception:
        return RedirectResponse(_frontend_hash_url(f"/checkout?payment=failed&reference={reference}"), status_code=302)


@router.post("/paystack/webhook", status_code=status.HTTP_200_OK)
async def paystack_webhook(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    raw_body = await request.body()
    signature = request.headers.get("x-paystack-signature")

    try:
        if not verify_paystack_signature(raw_body, signature):
            raise HTTPException(status_code=401, detail="Invalid Paystack signature")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    event = json.loads(raw_body.decode("utf-8"))
    if event.get("event") != "charge.success":
        return {"status": "ignored"}

    data = event.get("data") or {}
    metadata = data.get("metadata") or {}
    user_id = metadata.get("quickdrop_user_id")
    if not user_id:
        return {"status": "ignored"}

    current_user = await session.get(User, int(user_id))
    if not current_user:
        return {"status": "ignored"}

    try:
        await _create_or_fetch_paystack_orders(session, current_user, data)
    except ValueError:
        return {"status": "ignored"}

    return {"status": "ok"}


@router.post("/quote", response_model=CheckoutQuoteResponse, status_code=status.HTTP_200_OK)
async def quote_order(
    payload: CheckoutRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> CheckoutQuoteResponse:
    try:
        return await build_checkout_quote(session, current_user.id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{order_id}", response_model=OrderStatusResponse)
async def get_order(
    order_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> OrderStatusResponse:
    order = await get_order_with_relations(session, order_id, current_user.id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    tracking = await build_order_tracking_snapshot(order)

    return OrderStatusResponse(
        id=order.id,
        order_reference=order.order_reference,
        status=order.status,
        tracking_note=order.tracking_note,
        updated_at=order.updated_at,
        timeline=build_timeline(order.status),
        rider=order.rider,
        destination_latitude=order.address.latitude if order.address else None,
        destination_longitude=order.address.longitude if order.address else None,
        tracking_latitude=tracking["tracking_latitude"],
        tracking_longitude=tracking["tracking_longitude"],
        rider_location=tracking["rider_location"],
        route_geometry=tracking["route_geometry"],
        distance_meters_remaining=tracking["distance_meters_remaining"],
        duration_seconds_remaining=tracking["duration_seconds_remaining"],
        estimated_arrival_seconds=tracking["estimated_arrival_seconds"],
    )


@router.get("/user/history", response_model=list[OrderResponse])
async def get_user_orders(
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> list[OrderResponse]:
    orders = await get_orders_for_user(session, current_user.id)
    return [await serialize_order(order) for order in orders]


@router.get("/vendor/history", response_model=list[VendorOrderResponse])
async def get_vendor_orders(
    session: AsyncSession = Depends(get_db_session),
    current_vendor: Vendor = Depends(get_current_vendor),
) -> list[VendorOrderResponse]:
    result = await session.execute(
        select(Order)
        .where(Order.vendor_id == current_vendor.id)
        .options(*vendor_order_options)
        .order_by(Order.created_at.desc())
    )
    orders = list(result.scalars().all())
    return [await serialize_vendor_order(order) for order in orders]


@router.patch("/vendor/{order_id}", response_model=VendorOrderResponse)
async def update_vendor_order(
    order_id: int,
    payload: VendorOrderStatusUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_vendor: Vendor = Depends(get_current_vendor),
) -> VendorOrderResponse:
    order = await session.scalar(
        select(Order)
        .where(Order.id == order_id, Order.vendor_id == current_vendor.id)
        .options(*vendor_order_options)
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    previous_status = order.status
    order.status = payload.status
    if order.vendor_responded_at is None and previous_status == OrderStatus.pending and payload.status != OrderStatus.pending:
        order.vendor_responded_at = datetime.now(timezone.utc)
    if payload.rider_id is not None:
        rider = await session.get(User, payload.rider_id)
        if not rider or rider.role != "rider" or not rider.is_active:
            raise HTTPException(status_code=400, detail="Rider not found")
        order.rider_id = rider.id
    if payload.tracking_note is not None:
        order.tracking_note = payload.tracking_note

    await create_notification(
        session,
        recipient_role="customer",
        recipient_user_id=order.user_id,
        title="Order status updated",
        message=f"Order {order.order_reference} is now {payload.status.value.replace('_', ' ')}.",
        category="order",
        action_url=f"/tracking/{order.id}",
    )
    await create_notification(
        session,
        recipient_role="admin",
        title="Vendor updated an order",
        message=f"{current_vendor.name} changed {order.order_reference} to {payload.status.value.replace('_', ' ')}.",
        category="order",
        action_url="/admin/orders",
    )
    if order.rider_id:
        await create_notification(
            session,
            recipient_role="rider",
            recipient_user_id=order.rider_id,
            title="Order workflow updated",
            message=f"{current_vendor.name} updated order {order.order_reference}.",
            category="order",
            action_url="/rider/dashboard",
        )

    await session.commit()
    await session.refresh(order)
    await broadcast_order_state(session, order.id, "order.status")

    refreshed = await session.scalar(
        select(Order)
        .where(Order.id == order.id)
        .options(*vendor_order_options)
    )
    return await serialize_vendor_order(refreshed)


@router.get("/rider/available", response_model=list[VendorOrderResponse])
async def get_available_rider_orders(
    session: AsyncSession = Depends(get_db_session),
    current_rider: User = Depends(get_current_rider),
) -> list[VendorOrderResponse]:
    result = await session.execute(
        select(Order)
        .where(Order.status == "rider_assigned", Order.rider_id == current_rider.id)
        .options(*vendor_order_options)
        .order_by(Order.updated_at.desc())
    )
    orders = list(result.scalars().all())
    return [await serialize_vendor_order(order) for order in orders]


@router.websocket("/ws")
async def orders_ws(
    websocket: WebSocket,
    token: str = Query(...),
    order_id: int = Query(...),
) -> None:
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        try:
            payload = decode_access_token(token)
        except ValueError:
            await websocket.close(code=4401)
            return

        identity_type = payload.get("type")
        subject = payload.get("sub")
        try:
            actor_id = int(subject)
        except (TypeError, ValueError):
            await websocket.close(code=4401)
            return

        order = await session.scalar(
            select(Order)
            .where(Order.id == order_id)
            .options(
                selectinload(Order.vendor),
                selectinload(Order.user),
                selectinload(Order.rider),
                selectinload(Order.address),
                selectinload(Order.items).selectinload(OrderItem.product),
            )
        )
        if not order:
            await websocket.close(code=4404)
            return

        if identity_type == "user" and order.user_id != actor_id:
            await websocket.close(code=4403)
            return
        if identity_type == "rider" and order.rider_id != actor_id:
            await websocket.close(code=4403)
            return
        if identity_type not in {"user", "rider", "admin"}:
            await websocket.close(code=4403)
            return

        connection_key = f"{identity_type}:{actor_id}:order:{order_id}"
        connected = await order_realtime_manager.connect(str(order_id), websocket, connection_key)
        if not connected:
            return

        bootstrap = await build_order_status_response(session, order_id)
        if not bootstrap or not await _send_order_socket_payload(
            websocket,
            {"event": "order.bootstrap", "order": bootstrap.model_dump(mode="json")},
        ):
            order_realtime_manager.disconnect(websocket)
            return

        try:
            while True:
                message = await websocket.receive()
                message_type = message.get("type")
                if message_type == "websocket.disconnect":
                    break
                if message_type != "websocket.receive":
                    continue
                payload_text = message.get("text")
                if not payload_text:
                    continue
                try:
                    data = json.loads(payload_text)
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
        except WebSocketDisconnect:
            pass
        finally:
            order_realtime_manager.disconnect(websocket)

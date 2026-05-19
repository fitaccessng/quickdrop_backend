import asyncio
import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import requests

from app.api.deps import get_current_rider, get_db_session
from app.models.delivery_setting import DeliverySetting
from app.models.notification import Notification
from app.models.order import Order, OrderItem, OrderStatus
from app.models.payout_request import PayoutRequest
from app.models.user import User
from app.schemas.common import PayoutRequestCreate, PayoutRequestResponse
from app.schemas.order import RiderSummary
from app.schemas.rider import (
    RiderAnalyticsResponse,
    RiderAcceptOrderRequest,
    RiderDashboardResponse,
    RiderLocationUpdateRequest,
    RiderOrderResponse,
    RiderOrderUpdateRequest,
    RiderProfileResponse,
    RiderProfileUpdateRequest,
    RiderRouteResponse,
    RiderWalletResponse,
)
from app.services.notifications import create_notification
from app.api.orders import broadcast_order_state

router = APIRouter(prefix="/rider", tags=["rider"])

order_options = (
    selectinload(Order.vendor),
    selectinload(Order.user),
    selectinload(Order.rider),
    selectinload(Order.address),
    selectinload(Order.items).selectinload(OrderItem.product),
)


def serialize_rider_order(order: Order) -> RiderOrderResponse:
    return RiderOrderResponse(
        id=order.id,
        order_reference=order.order_reference,
        status=order.status,
        total_amount=order.total_amount,
        delivery_fee=order.delivery_fee,
        tracking_note=order.tracking_note,
        created_at=order.created_at,
        updated_at=order.updated_at,
        vendor=order.vendor,
        customer=order.user,
        address=order.address,
        rider=order.rider,
        tracking_latitude=order.tracking_latitude,
        tracking_longitude=order.tracking_longitude,
        requires_rider_response=bool(order.rider_id and order.status == OrderStatus.rider_assigned),
    )


async def _get_rider_payout_percentage(session: AsyncSession) -> float:
    settings = await session.scalar(select(DeliverySetting).order_by(DeliverySetting.id.asc()))
    return float(settings.rider_payout_percentage) if settings and settings.rider_payout_percentage is not None else 30.0


async def _get_rider_profile(session: AsyncSession, rider_id: int) -> RiderProfileResponse:
    rider = await session.scalar(select(User).where(User.id == rider_id))
    return RiderProfileResponse.model_validate(rider)


@router.get("/me/profile", response_model=RiderProfileResponse)
async def get_rider_profile(
    current_rider: User = Depends(get_current_rider),
    session: AsyncSession = Depends(get_db_session),
) -> RiderProfileResponse:
    return await _get_rider_profile(session, current_rider.id)


@router.put("/me/profile", response_model=RiderProfileResponse)
async def update_rider_profile(
    payload: RiderProfileUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_rider: User = Depends(get_current_rider),
) -> RiderProfileResponse:
    rider = await session.get(User, current_rider.id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rider, field, value)

    if rider.city and rider.state and rider.street and rider.vehicle_type and rider.license_number:
        rider.is_onboarded = True

    await session.commit()
    return await _get_rider_profile(session, current_rider.id)


@router.get("/dashboard", response_model=RiderDashboardResponse)
async def get_rider_dashboard(
    session: AsyncSession = Depends(get_db_session),
    current_rider: User = Depends(get_current_rider),
) -> RiderDashboardResponse:
    payout_percentage = await _get_rider_payout_percentage(session)
    request_result = await session.execute(
        select(Order)
        .where(
            or_(
                (Order.status.in_([OrderStatus.confirmed, OrderStatus.preparing]) & Order.rider_id.is_(None)),
                (Order.status == OrderStatus.rider_assigned) & (Order.rider_id == current_rider.id),
            )
        )
        .options(*order_options)
        .order_by(Order.updated_at.desc())
    )
    requests = list(request_result.scalars().all())
    if current_rider.rider_status == "offline":
        requests = []

    active_result = await session.execute(
        select(Order)
        .where(
            Order.rider_id == current_rider.id,
            Order.status.in_([OrderStatus.rider_assigned, OrderStatus.on_the_way]),
        )
        .options(*order_options)
        .order_by(Order.updated_at.desc())
    )
    active_orders = list(active_result.scalars().all())
    active_orders.sort(key=lambda order: 0 if order.status == OrderStatus.on_the_way else 1)

    completed_result = await session.execute(
        select(Order)
        .where(Order.rider_id == current_rider.id, Order.status == OrderStatus.delivered)
        .options(*order_options)
    )
    completed_orders = list(completed_result.scalars().all())
    today_earnings = sum(round((float(order.delivery_fee or 0) * payout_percentage) / 100, 2) for order in completed_orders)

    return RiderDashboardResponse(
        rider=current_rider,
        pending_requests=len(requests),
        active_deliveries=len(active_orders),
        completed_deliveries=len(completed_orders),
        total_earnings=current_rider.total_earnings,
        wallet_balance=current_rider.wallet_balance,
        today_earnings=today_earnings,
        active_order=serialize_rider_order(active_orders[0]) if active_orders else None,
    )


@router.get("/analytics", response_model=RiderAnalyticsResponse)
async def get_rider_analytics(
    session: AsyncSession = Depends(get_db_session),
    current_rider: User = Depends(get_current_rider),
) -> RiderAnalyticsResponse:
    payout_percentage = await _get_rider_payout_percentage(session)
    active_result = await session.execute(
        select(Order)
        .where(
            Order.rider_id == current_rider.id,
            Order.status.in_([OrderStatus.rider_assigned, OrderStatus.on_the_way]),
        )
    )
    active_orders = list(active_result.scalars().all())

    pending_result = await session.execute(
        select(Order)
        .where(Order.status.in_([OrderStatus.confirmed, OrderStatus.preparing]), Order.rider_id.is_(None))
    )
    pending_requests = len(list(pending_result.scalars().all()))

    completed_result = await session.execute(
        select(Order)
        .where(Order.rider_id == current_rider.id, Order.status == OrderStatus.delivered)
        .order_by(Order.updated_at.desc())
    )
    completed_orders = list(completed_result.scalars().all())

    weekly_map: dict[str, float] = {}
    for order in completed_orders[:20]:
        key = order.updated_at.strftime("%a")
        weekly_map[key] = weekly_map.get(key, 0.0) + round((float(order.delivery_fee or 0) * payout_percentage) / 100, 2)

    delivered_count = len(completed_orders)
    assigned_count = delivered_count + len(active_orders)
    completion_rate = (delivered_count / assigned_count) * 100 if assigned_count else 0.0

    return RiderAnalyticsResponse(
        total_earnings=current_rider.total_earnings,
        wallet_balance=current_rider.wallet_balance,
        total_deliveries=current_rider.total_deliveries,
        active_deliveries=len(active_orders),
        pending_requests=pending_requests,
        today_earnings=sum(
            round((float(order.delivery_fee or 0) * payout_percentage) / 100, 2)
            for order in completed_orders
            if order.updated_at.date() == datetime.utcnow().date()
        ),
        weekly_earnings=[{"day": day, "amount": amount} for day, amount in weekly_map.items()],
        delivery_completion_rate=completion_rate,
    )


@router.get("/orders/requests", response_model=list[RiderOrderResponse])
async def get_rider_order_requests(
    session: AsyncSession = Depends(get_db_session),
    current_rider: User = Depends(get_current_rider),
) -> list[RiderOrderResponse]:
    if current_rider.rider_status == "offline":
        return []
    result = await session.execute(
        select(Order)
        .where(
            or_(
                (Order.status.in_([OrderStatus.confirmed, OrderStatus.preparing]) & Order.rider_id.is_(None)),
                (Order.status == OrderStatus.rider_assigned) & (Order.rider_id == current_rider.id),
            )
        )
        .options(*order_options)
        .order_by(Order.updated_at.desc())
    )
    return [serialize_rider_order(order) for order in result.scalars().all()]


@router.get("/orders/manage", response_model=list[RiderOrderResponse])
async def get_rider_managed_orders(
    session: AsyncSession = Depends(get_db_session),
    current_rider: User = Depends(get_current_rider),
) -> list[RiderOrderResponse]:
    result = await session.execute(
        select(Order)
        .where(
            Order.rider_id == current_rider.id,
            Order.status.in_([OrderStatus.on_the_way, OrderStatus.delivered]),
        )
        .options(*order_options)
        .order_by(Order.updated_at.desc())
    )
    return [serialize_rider_order(order) for order in result.scalars().all()]


@router.post("/orders/{order_id}/accept", response_model=RiderOrderResponse)
async def accept_rider_order(
    order_id: int,
    payload: RiderAcceptOrderRequest,
    session: AsyncSession = Depends(get_db_session),
    current_rider: User = Depends(get_current_rider),
) -> RiderOrderResponse:
    if current_rider.rider_status == "offline":
        raise HTTPException(status_code=409, detail="Go online before accepting new deliveries")
    order = await session.scalar(
        select(Order)
        .where(order_id == Order.id)
        .options(*order_options)
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.rider_id and order.rider_id != current_rider.id:
        raise HTTPException(status_code=409, detail="Order already assigned")
    if order.status not in {OrderStatus.confirmed, OrderStatus.preparing, OrderStatus.rider_assigned}:
        raise HTTPException(status_code=400, detail="Order is not ready for rider pickup")

    order.rider_id = current_rider.id
    order.status = OrderStatus.on_the_way
    order.tracking_note = f"{current_rider.full_name} is heading to the customer."
    order.tracking_latitude = payload.current_latitude
    order.tracking_longitude = payload.current_longitude
    current_rider.rider_status = "delivering"
    await create_notification(
        session,
        recipient_role="customer",
        recipient_user_id=order.user_id,
        title="Rider accepted your order",
        message=f"{current_rider.full_name} is now handling order {order.order_reference}.",
        category="order",
        action_url=f"/tracking/{order.id}",
    )
    await create_notification(
        session,
        recipient_role="admin",
        title="Order picked up by rider",
        message=f"{current_rider.full_name} accepted order {order.order_reference}.",
        category="order",
        action_url="/admin/orders",
    )

    await session.commit()
    await session.refresh(order)
    await broadcast_order_state(session, order.id, "order.accepted")
    return serialize_rider_order(order)


@router.post("/orders/{order_id}/reject", response_model=RiderOrderResponse)
async def reject_rider_order(
    order_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_rider: User = Depends(get_current_rider),
) -> RiderOrderResponse:
    order = await session.scalar(
        select(Order)
        .where(Order.id == order_id, Order.rider_id == current_rider.id)
        .options(*order_options)
    )
    if not order:
        raise HTTPException(status_code=404, detail="Assigned order not found")
    if order.status != OrderStatus.rider_assigned:
        raise HTTPException(status_code=400, detail="Only assigned orders waiting for response can be rejected")

    order.rider_id = None
    order.status = OrderStatus.preparing
    order.tracking_note = f"{current_rider.full_name} rejected the order assignment."
    order.tracking_latitude = None
    order.tracking_longitude = None
    current_rider.rider_status = "available"

    await create_notification(
        session,
        recipient_role="admin",
        title="Rider rejected an order",
        message=f"{current_rider.full_name} rejected order {order.order_reference}.",
        category="order",
        action_url="/admin/rides",
    )
    await create_notification(
        session,
        recipient_role="customer",
        recipient_user_id=order.user_id,
        title="Rider reassignment in progress",
        message=f"Your order {order.order_reference} is being reassigned to another rider.",
        category="order",
        action_url=f"/tracking/{order.id}",
    )

    await session.commit()
    await session.refresh(order)
    await broadcast_order_state(session, order.id, "order.rejected")
    return serialize_rider_order(order)


@router.patch("/orders/{order_id}", response_model=RiderOrderResponse)
async def update_rider_order(
    order_id: int,
    payload: RiderOrderUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_rider: User = Depends(get_current_rider),
) -> RiderOrderResponse:
    order = await session.scalar(
        select(Order)
        .where(Order.id == order_id, Order.rider_id == current_rider.id)
        .options(*order_options)
    )
    if not order:
        raise HTTPException(status_code=404, detail="Assigned order not found")

    order.status = payload.status
    if payload.tracking_note is not None:
        order.tracking_note = payload.tracking_note
    if payload.tracking_latitude is not None:
        order.tracking_latitude = payload.tracking_latitude
    if payload.tracking_longitude is not None:
        order.tracking_longitude = payload.tracking_longitude

    if payload.status == OrderStatus.delivered:
        payout_percentage = await _get_rider_payout_percentage(session)
        payout_amount = round((float(order.delivery_fee or 0) * payout_percentage) / 100, 2)
        current_rider.total_deliveries += 1
        current_rider.wallet_balance += payout_amount
        current_rider.total_earnings += payout_amount
        current_rider.rider_status = "available"
    elif payload.status in {OrderStatus.on_the_way, OrderStatus.rider_assigned}:
        current_rider.rider_status = "delivering"

    await create_notification(
        session,
        recipient_role="customer",
        recipient_user_id=order.user_id,
        title="Delivery status updated",
        message=f"Order {order.order_reference} is now {payload.status.value.replace('_', ' ')}.",
        category="order",
        action_url=f"/tracking/{order.id}",
    )
    await create_notification(
        session,
        recipient_role="admin",
        title="Rider updated an order",
        message=f"{current_rider.full_name} set {order.order_reference} to {payload.status.value.replace('_', ' ')}.",
        category="order",
        action_url="/admin/orders",
    )

    await session.commit()
    await session.refresh(order)
    await broadcast_order_state(session, order.id, "order.status")
    return serialize_rider_order(order)


@router.post("/orders/{order_id}/location", response_model=RiderOrderResponse)
async def update_rider_location(
    order_id: int,
    payload: RiderLocationUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_rider: User = Depends(get_current_rider),
) -> RiderOrderResponse:
    order = await session.scalar(
        select(Order)
        .where(Order.id == order_id, Order.rider_id == current_rider.id)
        .options(*order_options)
    )
    if not order:
        raise HTTPException(status_code=404, detail="Assigned order not found")

    order.tracking_latitude = payload.tracking_latitude
    order.tracking_longitude = payload.tracking_longitude
    current_rider.current_latitude = payload.tracking_latitude
    current_rider.current_longitude = payload.tracking_longitude
    if order.status == OrderStatus.rider_assigned:
        order.status = OrderStatus.on_the_way

    await session.commit()
    await session.refresh(order)
    await broadcast_order_state(session, order.id, "order.location")
    return serialize_rider_order(order)


@router.get("/wallet", response_model=RiderWalletResponse)
async def get_rider_wallet(
    session: AsyncSession = Depends(get_db_session),
    current_rider: User = Depends(get_current_rider),
) -> RiderWalletResponse:
    payout_result = await session.execute(
        select(PayoutRequest)
        .where(PayoutRequest.requester_user_id == current_rider.id, PayoutRequest.requester_role == "rider")
        .order_by(PayoutRequest.created_at.desc())
        .limit(10)
    )
    result = await session.execute(
        select(Order)
        .where(Order.rider_id == current_rider.id, Order.status == OrderStatus.delivered)
        .options(*order_options)
        .order_by(Order.updated_at.desc())
        .limit(10)
    )
    recent_deliveries = list(result.scalars().all())
    return RiderWalletResponse(
        wallet_balance=current_rider.wallet_balance,
        total_earnings=current_rider.total_earnings,
        completed_deliveries=current_rider.total_deliveries,
        available_payout=current_rider.wallet_balance,
        payout_requests=list(payout_result.scalars().all()),
        recent_deliveries=[serialize_rider_order(order) for order in recent_deliveries],
    )


@router.post("/payout-requests", response_model=PayoutRequestResponse)
async def create_rider_payout_request(
    payload: PayoutRequestCreate,
    session: AsyncSession = Depends(get_db_session),
    current_rider: User = Depends(get_current_rider),
) -> PayoutRequestResponse:
    outstanding_request_total = await session.scalar(
        select(func.coalesce(func.sum(PayoutRequest.amount), 0)).where(
            PayoutRequest.requester_user_id == current_rider.id,
            PayoutRequest.requester_role == "rider",
            PayoutRequest.status.in_(["pending", "approved"]),
        )
    )
    requestable_balance = max(float(current_rider.wallet_balance or 0) - float(outstanding_request_total or 0), 0.0)
    if payload.amount > requestable_balance:
        raise HTTPException(status_code=400, detail="Requested amount exceeds available payout balance")
    payout = PayoutRequest(
        requester_role="rider",
        requester_user_id=current_rider.id,
        requester_name=current_rider.full_name,
        requester_email=current_rider.email,
        amount=payload.amount,
        note=payload.note,
    )
    session.add(payout)
    await create_notification(
        session,
        recipient_role="admin",
        title="New rider payout request",
        message=f"{current_rider.full_name} requested {payload.amount:.2f} for payout.",
        category="payment",
    )
    await session.commit()
    await session.refresh(payout)
    return payout


@router.get("/orders/{order_id}/tracking", response_model=RiderOrderResponse)
async def get_rider_tracking_order(
    order_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_rider: User = Depends(get_current_rider),
) -> RiderOrderResponse:
    order = await session.scalar(
        select(Order)
        .where(
            Order.id == order_id,
            or_(Order.rider_id == current_rider.id, Order.rider_id.is_(None)),
        )
        .options(*order_options)
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return serialize_rider_order(order)


@router.get("/orders/{order_id}/route", response_model=RiderRouteResponse)
async def get_rider_order_route(
    order_id: int,
    start_latitude: float,
    start_longitude: float,
    session: AsyncSession = Depends(get_db_session),
    current_rider: User = Depends(get_current_rider),
) -> RiderRouteResponse:
    order = await session.scalar(
        select(Order)
        .where(
            Order.id == order_id,
            or_(Order.rider_id == current_rider.id, Order.rider_id.is_(None)),
        )
        .options(*order_options)
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.address is None or order.address.latitude is None or order.address.longitude is None:
        raise HTTPException(status_code=400, detail="Order destination is unavailable")

    api_key = os.getenv(
        "OPENROUTESERVICE_API_KEY",
        "5b3ce3597851110001cf6248b6f167f4c7e34c6d9e11bd7b92d4355a",
    ).strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="Routing service is not configured")

    start = f"{start_longitude},{start_latitude}"
    end = f"{order.address.longitude},{order.address.latitude}"
    url = "https://api.openrouteservice.org/v2/directions/driving-car"

    def _request_route() -> dict:
        response = requests.get(
            url,
            params={"api_key": api_key, "start": start, "end": end},
            timeout=15,
        )
        response.raise_for_status()
        return response.json()

    try:
        data = await asyncio.to_thread(_request_route)
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else 502
        detail = "Unable to fetch route right now"
        try:
            payload = exc.response.json() if exc.response is not None else {}
            detail = payload.get("error", {}).get("message") or payload.get("message") or detail
        except Exception:
            pass
        raise HTTPException(status_code=502 if status_code >= 500 else status_code, detail=detail) from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail="Unable to reach routing service") from exc

    features = data.get("features") or []
    if not features:
        raise HTTPException(status_code=502, detail="Routing service returned no route")

    route = features[0]
    coordinates = route.get("geometry", {}).get("coordinates") or []
    segments = route.get("properties", {}).get("segments") or []
    if not coordinates or not segments:
        raise HTTPException(status_code=502, detail="Routing service returned incomplete route data")

    return RiderRouteResponse(
        distance_meters=float(segments[0].get("distance") or 0),
        duration_seconds=float(segments[0].get("duration") or 0),
        coordinates=coordinates,
    )

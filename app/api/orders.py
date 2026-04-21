from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_rider, get_current_user, get_current_vendor, get_db_session
from app.models.order import Order, OrderItem
from app.models.user import User
from app.models.vendor import Vendor
from app.schemas.order import (
    CheckoutRequest,
    CheckoutQuoteResponse,
    CheckoutResponse,
    OrderResponse,
    OrderStatusResponse,
    RiderSummary,
    VendorOrderResponse,
    VendorOrderStatusUpdate,
)
from app.services.orders import build_checkout_quote, build_timeline, create_checkout, get_order_with_relations, get_orders_for_user
from app.services.notifications import create_notification

router = APIRouter(prefix="/orders", tags=["orders"])

vendor_order_options = (
    selectinload(Order.user),
    selectinload(Order.rider),
    selectinload(Order.address),
    selectinload(Order.items).selectinload(OrderItem.product),
)


def serialize_order(order) -> OrderResponse:
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
        tracking_latitude=order.tracking_latitude,
        tracking_longitude=order.tracking_longitude,
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


def serialize_vendor_order(order) -> VendorOrderResponse:
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
        tracking_latitude=order.tracking_latitude,
        tracking_longitude=order.tracking_longitude,
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
            )
            await create_notification(
                session,
                recipient_role="admin",
                title="New customer order",
                message=f"Order {hydrated.order_reference} entered the system.",
                category="order",
            )
            hydrated_orders.append(serialize_order(hydrated))

    return CheckoutResponse(
        order_reference=order_reference,
        orders=hydrated_orders,
        total_amount=sum(order.total_amount for order in hydrated_orders),
    )


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

    return OrderStatusResponse(
        id=order.id,
        order_reference=order.order_reference,
        status=order.status,
        tracking_note=order.tracking_note,
        updated_at=order.updated_at,
        timeline=build_timeline(order.status),
        rider=order.rider,
        tracking_latitude=order.tracking_latitude,
        tracking_longitude=order.tracking_longitude,
    )


@router.get("/user/history", response_model=list[OrderResponse])
async def get_user_orders(
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> list[OrderResponse]:
    orders = await get_orders_for_user(session, current_user.id)
    return [serialize_order(order) for order in orders]


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
    return [serialize_vendor_order(order) for order in orders]


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

    order.status = payload.status
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
    )
    await create_notification(
        session,
        recipient_role="admin",
        title="Vendor updated an order",
        message=f"{current_vendor.name} changed {order.order_reference} to {payload.status.value.replace('_', ' ')}.",
        category="order",
    )
    if order.rider_id:
        await create_notification(
            session,
            recipient_role="rider",
            recipient_user_id=order.rider_id,
            title="Order workflow updated",
            message=f"{current_vendor.name} updated order {order.order_reference}.",
            category="order",
        )

    await session.commit()
    await session.refresh(order)

    refreshed = await session.scalar(
        select(Order)
        .where(Order.id == order.id)
        .options(*vendor_order_options)
    )
    return serialize_vendor_order(refreshed)


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
    return [serialize_vendor_order(order) for order in orders]

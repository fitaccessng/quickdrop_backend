from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_admin, get_db_session
from app.models.order import Order, OrderItem, OrderStatus
from app.models.payout_request import PayoutRequest
from app.models.user import User
from app.models.vendor import Vendor
from app.schemas.admin import (
    AdminAssignRiderRequest,
    AdminOrderItem,
    AdminProfileResponse,
    AdminProfileUpdateRequest,
    AdminSummaryResponse,
    AdminUserDetailResponse,
    AdminUserItem,
    AdminVendorAnalyticsResponse,
    AdminVendorApprovalRequest,
    AdminVendorItem,
)
from app.schemas.common import PayoutRequestResponse
from app.services.notifications import create_notification

router = APIRouter(prefix="/admin", tags=["admin"])


def serialize_order(order: Order) -> AdminOrderItem:
    return AdminOrderItem(
        id=order.id,
        order_reference=order.order_reference,
        status=order.status.value if hasattr(order.status, "value") else str(order.status),
        total_amount=order.total_amount,
        delivery_fee=order.delivery_fee,
        created_at=order.created_at,
        updated_at=order.updated_at,
        vendor_name=order.vendor.name,
        customer_name=order.user.full_name,
        rider=order.rider,
        tracking_note=order.tracking_note,
        tracking_latitude=order.tracking_latitude,
        tracking_longitude=order.tracking_longitude,
    )


@router.get("/dashboard", response_model=AdminSummaryResponse)
async def get_admin_dashboard(
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> AdminSummaryResponse:
    total_users = await session.scalar(select(func.count()).select_from(User).where(User.role == "customer"))
    total_vendors = await session.scalar(select(func.count()).select_from(Vendor))
    pending_vendors = await session.scalar(select(func.count()).select_from(Vendor).where(Vendor.is_approved.is_(False)))
    total_riders = await session.scalar(select(func.count()).select_from(User).where(User.role == "rider"))
    active_orders = await session.scalar(
        select(func.count()).select_from(Order).where(Order.status.in_([OrderStatus.pending, OrderStatus.confirmed, OrderStatus.preparing, OrderStatus.rider_assigned, OrderStatus.on_the_way]))
    )
    completed_orders = await session.scalar(
        select(func.count()).select_from(Order).where(Order.status == OrderStatus.delivered)
    )
    payout_requests_pending = await session.scalar(
        select(func.count()).select_from(PayoutRequest).where(PayoutRequest.status == "pending")
    )
    payout_requests_result = await session.execute(
        select(PayoutRequest).order_by(PayoutRequest.created_at.desc()).limit(6)
    )
    return AdminSummaryResponse(
        total_users=total_users or 0,
        total_vendors=total_vendors or 0,
        pending_vendors=pending_vendors or 0,
        total_riders=total_riders or 0,
        active_orders=active_orders or 0,
        completed_orders=completed_orders or 0,
        payout_requests_pending=payout_requests_pending or 0,
        recent_payout_requests=list(payout_requests_result.scalars().all()),
    )


@router.get("/vendors", response_model=list[AdminVendorItem])
async def get_admin_vendors(
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> list[AdminVendorItem]:
    result = await session.execute(select(Vendor).order_by(Vendor.created_at.desc()))
    return list(result.scalars().all())


@router.patch("/vendors/{vendor_id}/approval", response_model=AdminVendorItem)
async def approve_vendor(
    vendor_id: int,
    payload: AdminVendorApprovalRequest,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> AdminVendorItem:
    vendor = await session.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    vendor.is_approved = payload.is_approved
    await create_notification(
        session,
        recipient_role="vendor",
        recipient_vendor_id=vendor.id,
        title="Vendor approval updated",
        message=f"Your vendor account is now {'approved' if payload.is_approved else 'under review'}.",
        category="account",
    )
    await session.commit()
    await session.refresh(vendor)
    return vendor


@router.get("/vendors/{vendor_id}/analytics", response_model=AdminVendorAnalyticsResponse)
async def get_admin_vendor_analytics(
    vendor_id: int,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> AdminVendorAnalyticsResponse:
    vendor = await session.scalar(
        select(Vendor)
        .where(Vendor.id == vendor_id)
        .options(selectinload(Vendor.orders).selectinload(Order.items).selectinload(OrderItem.product))
    )
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    orders = vendor.orders
    top_products = defaultdict(lambda: {"name": "", "units": 0, "revenue": 0.0})
    for order in orders:
        for item in order.items:
            top_products[item.product_name]["name"] = item.product_name
            top_products[item.product_name]["units"] += item.quantity
            top_products[item.product_name]["revenue"] += item.total_price
    return AdminVendorAnalyticsResponse(
        vendor_id=vendor.id,
        vendor_name=vendor.name,
        total_orders=len(orders),
        completed_orders=sum(1 for order in orders if order.status == OrderStatus.delivered),
        pending_orders=sum(1 for order in orders if order.status != OrderStatus.delivered),
        total_revenue=sum(order.total_amount for order in orders),
        average_order_value=(sum(order.total_amount for order in orders) / len(orders)) if orders else 0,
        top_products=sorted(top_products.values(), key=lambda item: item["revenue"], reverse=True)[:5],
    )


@router.get("/orders", response_model=list[AdminOrderItem])
async def get_admin_orders(
    status: Optional[str] = None,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> list[AdminOrderItem]:
    query = select(Order).options(selectinload(Order.vendor), selectinload(Order.user), selectinload(Order.rider))
    if status and status != "all":
        query = query.where(Order.status == status)
    result = await session.execute(query.order_by(Order.updated_at.desc()))
    return [serialize_order(order) for order in result.scalars().all()]


@router.get("/orders/{order_id}", response_model=AdminOrderItem)
async def get_admin_order_detail(
    order_id: int,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> AdminOrderItem:
    order = await session.scalar(
        select(Order).where(Order.id == order_id).options(selectinload(Order.vendor), selectinload(Order.user), selectinload(Order.rider))
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return serialize_order(order)


@router.patch("/orders/{order_id}/assign-rider", response_model=AdminOrderItem)
async def assign_rider_to_order(
    order_id: int,
    payload: AdminAssignRiderRequest,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> AdminOrderItem:
    order = await session.scalar(
        select(Order).where(Order.id == order_id).options(selectinload(Order.vendor), selectinload(Order.user), selectinload(Order.rider))
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    rider = await session.get(User, payload.rider_id)
    if not rider or rider.role != "rider":
        raise HTTPException(status_code=404, detail="Rider not found")
    if rider.rider_status == "offline":
        raise HTTPException(status_code=409, detail="Selected rider is offline and cannot receive orders")
    order.rider_id = rider.id
    order.status = OrderStatus.rider_assigned
    order.tracking_note = f"{rider.full_name} assigned by admin."
    rider.rider_status = "delivering"
    await create_notification(
        session,
        recipient_role="rider",
        recipient_user_id=rider.id,
        title="New order assigned",
        message=f"You were assigned to order {order.order_reference}.",
        category="order",
    )
    await create_notification(
        session,
        recipient_role="customer",
        recipient_user_id=order.user_id,
        title="Rider assigned",
        message=f"{rider.full_name} has been assigned to order {order.order_reference}.",
        category="order",
    )
    await session.commit()
    await session.refresh(order)
    return serialize_order(order)


@router.get("/users", response_model=list[AdminUserItem])
async def get_admin_users(
    role: Optional[str] = None,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> list[AdminUserItem]:
    query = select(User)
    if role and role != "all":
        query = query.where(User.role == role)
    result = await session.execute(query.order_by(User.created_at.desc()))
    return list(result.scalars().all())


@router.get("/users/{user_id}", response_model=AdminUserDetailResponse)
async def get_admin_user_detail(
    user_id: int,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> AdminUserDetailResponse:
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/riders", response_model=list[AdminUserItem])
async def get_admin_riders(
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> list[AdminUserItem]:
    result = await session.execute(select(User).where(User.role == "rider").order_by(User.created_at.desc()))
    return list(result.scalars().all())


@router.get("/payout-requests", response_model=list[PayoutRequestResponse])
async def get_admin_payout_requests(
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> list[PayoutRequestResponse]:
    result = await session.execute(select(PayoutRequest).order_by(PayoutRequest.created_at.desc()))
    return list(result.scalars().all())


@router.get("/profile", response_model=AdminProfileResponse)
async def get_admin_profile(current_admin: User = Depends(get_current_admin)) -> AdminProfileResponse:
    return current_admin


@router.put("/profile", response_model=AdminProfileResponse)
async def update_admin_profile(
    payload: AdminProfileUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_admin: User = Depends(get_current_admin),
) -> AdminProfileResponse:
    admin = await session.get(User, current_admin.id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(admin, field, value)
    await session.commit()
    await session.refresh(admin)
    return admin

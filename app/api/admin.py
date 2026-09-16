from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_admin, get_db_session
from app.models.order import Order, OrderItem, OrderStatus
from app.models.payout_request import PayoutRequest
from app.models.ride import Ride
from app.models.user import User
from app.models.vendor import Vendor, VendorPromotion
from app.models.product import Product, ProductReview
from app.schemas.admin import (
    AdminAccountStatusUpdateRequest,
    AdminProductReviewUpdateRequest,
    AdminAssignRiderRequest,
    AdminOrderItem,
    AdminOrderStatusUpdateRequest,
    AdminPaymentTransactionResponse,
    AdminProfileResponse,
    AdminProfileUpdateRequest,
    AdminRevenueSummaryResponse,
    AdminSummaryResponse,
    AdminUserDetailResponse,
    AdminUserItem,
    AdminVendorPromotionStatusUpdateRequest,
    AdminVendorAnalyticsResponse,
    AdminVendorApprovalRequest,
    AdminVendorItem,
)
from app.schemas.common import PayoutRequestResponse, PayoutRequestStatusUpdate
from app.schemas.product import ProductReviewResponse
from app.schemas.vendor import VendorPromotionResponse
from app.services.notifications import create_notification
from app.services.orders import build_order_tracking_snapshot
from app.api.orders import broadcast_order_state

router = APIRouter(prefix="/admin", tags=["admin"])


def _normalize_admin_status(value: str) -> str:
    status_value = (value or "").strip().lower()
    if status_value not in {"active", "inactive", "suspended"}:
        raise HTTPException(status_code=400, detail="Status must be one of: active, inactive, suspended")
    return status_value


def _parse_admin_datetime(value: Optional[str], *, field_name: str, is_end: bool = False) -> Optional[datetime]:
    if value is None or value == "":
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name} timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc) if is_end else parsed.astimezone(timezone.utc)


async def serialize_order(order: Order) -> AdminOrderItem:
    tracking = await build_order_tracking_snapshot(order)
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
        tracking_latitude=tracking["tracking_latitude"],
        tracking_longitude=tracking["tracking_longitude"],
        rider_location=tracking["rider_location"],
        route_geometry=tracking["route_geometry"],
        distance_meters_remaining=tracking["distance_meters_remaining"],
        duration_seconds_remaining=tracking["duration_seconds_remaining"],
        estimated_arrival_seconds=tracking["estimated_arrival_seconds"],
        destination_latitude=order.address.latitude if order.address else None,
        destination_longitude=order.address.longitude if order.address else None,
        rider_current_latitude=order.rider.current_latitude if order.rider else None,
        rider_current_longitude=order.rider.current_longitude if order.rider else None,
        items=[
            {
                "id": item.id,
                "product_id": item.product_id,
                "product_name": item.product.name if item.product else f"Product {item.product_id}",
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "total_price": item.total_price,
                "notes": item.notes,
            }
            for item in order.items
        ],
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
        action_url="/vendor/dashboard",
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
        .options(
            selectinload(Vendor.orders).selectinload(Order.items).selectinload(OrderItem.product),
            selectinload(Vendor.products).selectinload(Product.reviews),
            selectinload(Vendor.promotions).selectinload(VendorPromotion.product),
        )
    )
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    orders_result = await session.execute(
        select(Order)
        .where(Order.vendor_id == vendor_id)
        .options(
            selectinload(Order.vendor),
            selectinload(Order.user),
            selectinload(Order.rider),
            selectinload(Order.address),
            selectinload(Order.items).selectinload(OrderItem.product),
        )
        .order_by(Order.created_at.desc())
    )
    orders = list(orders_result.scalars().all())
    top_products = defaultdict(lambda: {"name": "", "units": 0, "revenue": 0.0})
    response_minutes: list[float] = []
    for order in orders:
        if order.vendor_responded_at and order.created_at:
            response_minutes.append(
                max((order.vendor_responded_at - order.created_at).total_seconds() / 60, 0.0)
            )
        for item in order.items:
            product_name = item.product.name if item.product else f"Product {item.product_id}"
            top_products[product_name]["name"] = product_name
            top_products[product_name]["units"] += item.quantity
            top_products[product_name]["revenue"] += item.total_price
    return AdminVendorAnalyticsResponse(
        vendor_id=vendor.id,
        vendor_name=vendor.name,
        vendor_slug=vendor.slug,
        vendor_email=vendor.email,
        vendor_phone=vendor.phone,
        logo_url=vendor.logo_url,
        cover_image_url=vendor.cover_image_url,
        category=vendor.category,
        city=vendor.city,
        street=vendor.street,
        po_box=vendor.po_box,
        description=vendor.description,
        business_registration_number=vendor.business_registration_number,
        vat_number=vendor.vat_number,
        south_african_id_number=vendor.south_african_id_number,
        tin=vendor.tin,
        bank_name=vendor.bank_name,
        bank_account_name=vendor.bank_account_name,
        bank_account_number=vendor.bank_account,
        permit_url=vendor.permit_url,
        opening_hours=vendor.opening_hours,
        latitude=vendor.latitude,
        longitude=vendor.longitude,
        minimum_order_amount=vendor.minimum_order_amount,
        delivery_fee=vendor.delivery_fee,
        prep_time_minutes=vendor.prep_time_minutes,
        support_email=vendor.support_email,
        support_phone=vendor.support_phone,
        delivery_radius_km=vendor.delivery_radius_km,
        auto_accept_orders=vendor.auto_accept_orders,
        notifications_enabled=vendor.notifications_enabled,
        is_onboarded=vendor.is_onboarded,
        is_approved=vendor.is_approved,
        rating=vendor.rating,
        review_count=vendor.review_count,
        created_at=vendor.created_at,
        total_orders=len(orders),
        completed_orders=sum(1 for order in orders if order.status == OrderStatus.delivered),
        pending_orders=sum(1 for order in orders if order.status == OrderStatus.pending),
        cancelled_orders=sum(1 for order in orders if order.status == OrderStatus.cancelled),
        active_orders=sum(
            1
            for order in orders
            if order.status in {OrderStatus.confirmed, OrderStatus.preparing, OrderStatus.rider_assigned, OrderStatus.on_the_way}
        ),
        total_revenue=sum(order.total_amount for order in orders),
        average_order_value=(sum(order.total_amount for order in orders) / len(orders)) if orders else 0,
        average_vendor_response_minutes=round(mean(response_minutes), 2) if response_minutes else 0,
        fastest_vendor_response_minutes=round(min(response_minutes), 2) if response_minutes else None,
        slowest_vendor_response_minutes=round(max(response_minutes), 2) if response_minutes else None,
        top_products=sorted(top_products.values(), key=lambda item: item["revenue"], reverse=True)[:5],
        uploaded_products=[
            {
                "id": product.id,
                "name": product.name,
                "category": product.category,
                "price": product.price,
                "stock_quantity": product.stock_quantity,
                "is_available": product.is_available,
                "image_url": product.image_urls[0] if product.image_urls else product.image_url,
                "rating": product.rating,
                "review_count": product.review_count,
                "created_at": product.created_at,
            }
            for product in sorted(vendor.products, key=lambda product: product.created_at, reverse=True)
        ],
        product_reviews=[
            review
            for product in vendor.products
            for review in sorted(product.reviews, key=lambda item: item.updated_at, reverse=True)
        ],
        promotions=sorted(vendor.promotions, key=lambda item: item.updated_at, reverse=True),
        recent_orders=[await serialize_order(order) for order in orders[:8]],
    )


@router.get("/orders")
async def get_admin_orders(
    status: Optional[str] = None,
    search: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: Optional[int] = None,
    page_size: Optional[int] = None,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
):
    query = select(Order).options(
        selectinload(Order.vendor),
        selectinload(Order.user),
        selectinload(Order.rider),
        selectinload(Order.address),
        selectinload(Order.items).selectinload(OrderItem.product),
    )
    if status and status != "all":
        query = query.where(Order.status == status)
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(
            or_(
                Order.order_reference.ilike(pattern),
                Order.payment_reference.ilike(pattern),
                Order.user.has(User.full_name.ilike(pattern)),
                Order.user.has(User.email.ilike(pattern)),
                Order.user.has(User.phone.ilike(pattern)),
                Order.vendor.has(Vendor.name.ilike(pattern)),
                Order.rider.has(User.full_name.ilike(pattern)),
            )
        )
    start_dt = _parse_admin_datetime(start_date, field_name="start_date") if start_date else None
    end_dt = _parse_admin_datetime(end_date, field_name="end_date") if end_date else None
    if start_dt:
        query = query.where(Order.created_at >= start_dt)
    if end_dt:
        query = query.where(Order.created_at <= end_dt)
    query = query.order_by(Order.updated_at.desc())

    if page is not None or page_size is not None:
        page_number = max(1, int(page or 1))
        page_size_value = max(1, min(100, int(page_size or 20)))
        total_query = select(func.count()).select_from(query.order_by(None).subquery())
        total = await session.scalar(total_query)
        paginated = query.offset((page_number - 1) * page_size_value).limit(page_size_value)
        result = await session.execute(paginated)
        items = [await serialize_order(order) for order in result.scalars().all()]
        total_pages = max(1, (total + page_size_value - 1) // page_size_value) if total else 1
        return {
            "items": items,
            "page": page_number,
            "page_size": page_size_value,
            "total": total or 0,
            "total_pages": total_pages,
            "has_next": page_number < total_pages,
            "has_previous": page_number > 1,
        }

    result = await session.execute(query)
    return [await serialize_order(order) for order in result.scalars().all()]


@router.patch("/orders/{order_id}/status", response_model=AdminOrderItem)
async def update_admin_order_status(
    order_id: int,
    payload: AdminOrderStatusUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> AdminOrderItem:
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
        raise HTTPException(status_code=404, detail="Order not found")
    target_status = payload.status.strip().lower()
    if target_status not in {status.value for status in OrderStatus}:
        raise HTTPException(status_code=400, detail="Invalid order status")

    allowed_transitions = {
        OrderStatus.pending: {OrderStatus.confirmed, OrderStatus.cancelled},
        OrderStatus.confirmed: {OrderStatus.preparing, OrderStatus.cancelled},
        OrderStatus.preparing: {OrderStatus.rider_assigned, OrderStatus.cancelled},
        OrderStatus.rider_assigned: {OrderStatus.on_the_way, OrderStatus.cancelled},
        OrderStatus.on_the_way: {OrderStatus.delivered, OrderStatus.cancelled},
        OrderStatus.delivered: set(),
        OrderStatus.cancelled: set(),
    }
    target_enum = OrderStatus(target_status)
    if target_enum not in allowed_transitions.get(order.status, set()):
        raise HTTPException(status_code=409, detail=f"Cannot change order from {order.status.value} to {target_enum.value}")

    order.status = target_enum
    await session.commit()
    await session.refresh(order)
    return await serialize_order(order)


@router.get("/orders/{order_id}", response_model=AdminOrderItem)
async def get_admin_order_detail(
    order_id: int,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> AdminOrderItem:
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
        raise HTTPException(status_code=404, detail="Order not found")
    return await serialize_order(order)


@router.patch("/orders/{order_id}/assign-rider", response_model=AdminOrderItem)
async def assign_rider_to_order(
    order_id: int,
    payload: AdminAssignRiderRequest,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> AdminOrderItem:
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
        raise HTTPException(status_code=404, detail="Order not found")
    rider = await session.get(User, payload.rider_id)
    if not rider or rider.role != "rider":
        raise HTTPException(status_code=404, detail="Rider not found")
    if rider.rider_status == "offline":
        raise HTTPException(status_code=409, detail="Selected rider is offline and cannot receive orders")
    previous_rider = order.rider
    previous_rider_id = order.rider_id
    order.rider_id = rider.id
    order.status = OrderStatus.rider_assigned
    order.tracking_note = f"{rider.full_name} assigned by admin. Waiting for rider acceptance."
    order.tracking_latitude = rider.current_latitude
    order.tracking_longitude = rider.current_longitude
    rider.rider_status = "available"
    if previous_rider_id and previous_rider_id != rider.id:
        active_orders_for_previous_rider = await session.scalar(
            select(func.count())
            .select_from(Order)
            .where(
                Order.rider_id == previous_rider_id,
                Order.id != order.id,
                Order.status.in_([OrderStatus.rider_assigned, OrderStatus.on_the_way]),
            )
        )
        if previous_rider and not (active_orders_for_previous_rider or 0):
            previous_rider.rider_status = "available"
        await create_notification(
            session,
            recipient_role="rider",
            recipient_user_id=previous_rider_id,
            title="Order reassigned",
            message=f"Order {order.order_reference} has been reassigned to another rider by admin.",
            category="order",
            action_url="/rider/order-requests",
        )
    await create_notification(
        session,
        recipient_role="rider",
        recipient_user_id=rider.id,
        title="New order assigned",
        message=f"You were assigned to order {order.order_reference}. Accept or reject this delivery request.",
        category="order",
        action_url="/rider/order-requests",
    )
    await create_notification(
        session,
        recipient_role="customer",
        recipient_user_id=order.user_id,
        title="Rider assigned",
        message=f"{rider.full_name} has been assigned to order {order.order_reference}.",
        category="order",
        action_url=f"/tracking/{order.id}",
    )
    await session.commit()
    await session.refresh(order)
    await broadcast_order_state(session, order.id, "order.assigned")
    return await serialize_order(order)


@router.patch("/customers/{user_id}/status", response_model=AdminUserItem)
async def update_customer_status(
    user_id: int,
    payload: AdminAccountStatusUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> AdminUserItem:
    user = await session.get(User, user_id)
    if not user or user.role != "customer":
        raise HTTPException(status_code=404, detail="Customer not found")
    next_status = _normalize_admin_status(payload.status)
    user.is_active = next_status == "active"
    await session.commit()
    await session.refresh(user)
    return user


@router.patch("/vendors/{vendor_id}/status", response_model=AdminVendorItem)
async def update_vendor_status(
    vendor_id: int,
    payload: AdminAccountStatusUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> AdminVendorItem:
    vendor = await session.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    next_status = _normalize_admin_status(payload.status)
    vendor.is_active = next_status == "active"
    await session.commit()
    await session.refresh(vendor)
    return vendor


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
    user = await session.scalar(
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.addresses))
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    orders_result = await session.execute(
        select(Order)
        .where((Order.user_id == user_id) | (Order.rider_id == user_id))
        .options(selectinload(Order.vendor), selectinload(Order.user), selectinload(Order.rider), selectinload(Order.address))
        .order_by(Order.created_at.desc())
        .limit(8)
    )
    return AdminUserDetailResponse(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        phone=user.phone,
        role=user.role,
        is_active=user.is_active,
        is_onboarded=user.is_onboarded,
        city=user.city,
        state=user.state,
        vehicle_type=user.vehicle_type,
        rider_status=user.rider_status,
        total_earnings=user.total_earnings,
        total_deliveries=user.total_deliveries,
        created_at=user.created_at,
        street=user.street,
        po_box=user.po_box,
        license_number=user.license_number,
        wallet_balance=user.wallet_balance,
        avatar_url=user.avatar_url,
        current_latitude=user.current_latitude,
        current_longitude=user.current_longitude,
        updated_at=user.updated_at,
        addresses=[
            {
                "id": address.id,
                "label": address.label,
                "recipient_name": address.recipient_name,
                "phone": address.phone,
                "line1": address.line1,
                "line2": address.line2,
                "city": address.city,
                "state": address.state,
                "postal_code": address.postal_code,
                "delivery_notes": address.delivery_notes,
                "latitude": address.latitude,
                "longitude": address.longitude,
                "is_default": address.is_default,
                "created_at": address.created_at,
            }
            for address in user.addresses
        ],
        recent_orders=[await serialize_order(order) for order in orders_result.scalars().all()],
    )


@router.get("/riders", response_model=list[AdminUserItem])
async def get_admin_riders(
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> list[AdminUserItem]:
    result = await session.execute(select(User).where(User.role == "rider").order_by(User.created_at.desc()))
    return list(result.scalars().all())


@router.get("/payments", response_model=list[AdminPaymentTransactionResponse])
async def get_admin_payments(
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> list[AdminPaymentTransactionResponse]:
    orders = await session.execute(
        select(Order)
        .options(selectinload(Order.user), selectinload(Order.vendor), selectinload(Order.rider))
        .order_by(Order.created_at.desc())
    )
    ride_rows = await session.execute(
        select(Ride)
        .options(selectinload(Ride.user), selectinload(Ride.rider))
        .order_by(Ride.created_at.desc())
    )
    records: list[AdminPaymentTransactionResponse] = []
    for order in orders.scalars().all():
        if not (order.payment_reference or order.total_amount or order.payment_status):
            continue
        records.append(
            AdminPaymentTransactionResponse(
                id=order.id,
                payment_reference=order.payment_reference,
                customer_name=order.user.full_name if order.user else None,
                customer_email=order.user.email if order.user else None,
                order_id=order.id,
                ride_id=None,
                amount=float(order.total_amount or 0),
                currency="ZAR",
                payment_provider="paystack" if bool(order.payment_reference) else "cash_on_delivery",
                payment_status=order.payment_status or "pending",
                payment_method=order.payment_method or "unknown",
                created_at=order.created_at,
                completed_at=order.updated_at if order.payment_status == "paid" else None,
                refund_status=None,
            )
        )
    for ride in ride_rows.scalars().all():
        if not ride.payment_reference and ride.payment_status == "pending" and ride.price == 0:
            continue
        records.append(
            AdminPaymentTransactionResponse(
                id=ride.id.__hash__(),
                payment_reference=ride.payment_reference,
                customer_name=ride.user.full_name if ride.user else None,
                customer_email=ride.user.email if ride.user else None,
                order_id=None,
                ride_id=ride.id,
                amount=float(ride.price or 0),
                currency=ride.currency or "ZAR",
                payment_provider="paystack" if bool(ride.payment_reference) else "cash",
                payment_status=ride.payment_status or "pending",
                payment_method="ride-payment",
                created_at=ride.created_at,
                completed_at=ride.completed_at or ride.updated_at,
                refund_status=None,
            )
        )
    records.sort(key=lambda item: item.created_at, reverse=True)
    return records


@router.get("/revenue", response_model=AdminRevenueSummaryResponse)
async def get_admin_revenue(
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> AdminRevenueSummaryResponse:
    order_result = await session.execute(
        select(Order).order_by(Order.created_at.desc())
    )
    orders = list(order_result.scalars().all())
    ride_result = await session.execute(
        select(Ride).order_by(Ride.created_at.desc())
    )
    rides = list(ride_result.scalars().all())

    gross_revenue = float(sum(order.total_amount for order in orders))
    paid_orders = [order for order in orders if order.payment_status == "paid"]
    pending_orders = [order for order in orders if order.payment_status == "pending"]
    completed_transaction_count = len(paid_orders)
    platform_fees = float(sum(order.delivery_fee for order in paid_orders))
    delivery_fees = platform_fees
    rider_earnings = float(sum(ride.rider_payout_amount or 0 for ride in rides if ride.rider_payout_amount is not None))
    vendor_earnings = float(sum(order.total_amount for order in orders if order.status == OrderStatus.delivered))
    completed_payment_amount = float(sum(order.total_amount for order in paid_orders))
    pending_amount = float(sum(order.total_amount for order in pending_orders))
    refunded_amount = 0.0

    return AdminRevenueSummaryResponse(
        gross_revenue=gross_revenue,
        platform_revenue=platform_fees,
        platform_fees=platform_fees,
        delivery_fees=delivery_fees,
        rider_earnings=rider_earnings,
        vendor_earnings=vendor_earnings,
        completed_transaction_count=completed_transaction_count,
        refunded_amount=refunded_amount,
        pending_amount=pending_amount,
        completed_payment_amount=completed_payment_amount,
    )


@router.get("/payout-requests", response_model=list[PayoutRequestResponse])
async def get_admin_payout_requests(
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> list[PayoutRequestResponse]:
    result = await session.execute(select(PayoutRequest).order_by(PayoutRequest.created_at.desc()))
    return list(result.scalars().all())


@router.patch("/payout-requests/{request_id}", response_model=PayoutRequestResponse)
async def update_admin_payout_request(
    request_id: int,
    payload: PayoutRequestStatusUpdate,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> PayoutRequestResponse:
    payout_request = await session.get(PayoutRequest, request_id)
    if not payout_request:
        raise HTTPException(status_code=404, detail="Payout request not found")

    previous_status = payout_request.status
    next_status = payload.status

    if previous_status != "paid" and next_status == "paid":
        if payout_request.requester_role == "rider":
            rider = await session.get(User, payout_request.requester_user_id)
            if not rider:
                raise HTTPException(status_code=404, detail="Rider not found for this payout request")
            if float(rider.wallet_balance or 0) < float(payout_request.amount or 0):
                raise HTTPException(status_code=409, detail="Rider wallet balance is no longer enough for this payout")
            rider.wallet_balance = float(rider.wallet_balance or 0) - float(payout_request.amount or 0)
        elif payout_request.requester_role == "vendor":
            vendor = await session.get(Vendor, payout_request.requester_vendor_id)
            if not vendor:
                raise HTTPException(status_code=404, detail="Vendor not found for this payout request")
            delivered_revenue_result = await session.execute(
                select(func.coalesce(func.sum(Order.total_amount), 0)).where(
                    Order.vendor_id == vendor.id,
                    Order.status == OrderStatus.delivered,
                )
            )
            paid_out_total_result = await session.execute(
                select(func.coalesce(func.sum(PayoutRequest.amount), 0)).where(
                    PayoutRequest.requester_vendor_id == vendor.id,
                    PayoutRequest.requester_role == "vendor",
                    PayoutRequest.status == "paid",
                    PayoutRequest.id != payout_request.id,
                )
            )
            delivered_revenue = float(delivered_revenue_result.scalar() or 0)
            paid_out_total = float(paid_out_total_result.scalar() or 0)
            if float(payout_request.amount or 0) > max(delivered_revenue - paid_out_total, 0.0):
                raise HTTPException(status_code=409, detail="Vendor balance is no longer enough for this payout")
    elif previous_status == "paid" and next_status != "paid" and payout_request.requester_role == "rider":
        rider = await session.get(User, payout_request.requester_user_id)
        if rider:
            rider.wallet_balance = float(rider.wallet_balance or 0) + float(payout_request.amount or 0)

    payout_request.status = payload.status
    recipient_role = payout_request.requester_role
    notification_recipient = {
        "recipient_role": "vendor" if recipient_role == "vendor" else "rider",
        "recipient_vendor_id": payout_request.requester_vendor_id if recipient_role == "vendor" else None,
        "recipient_user_id": payout_request.requester_user_id if recipient_role == "rider" else None,
    }
    await create_notification(
        session,
        title="Payout request updated",
        message=f"Your payout request for {payout_request.amount:.2f} is now {next_status}.",
        category="payment",
        action_url="/vendor/profile" if recipient_role == "vendor" else "/rider/wallet",
        **notification_recipient,
    )
    await session.commit()
    await session.refresh(payout_request)
    return payout_request


@router.patch("/product-reviews/{review_id}", response_model=ProductReviewResponse)
async def update_admin_product_review(
    review_id: int,
    payload: AdminProductReviewUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> dict:
    review = await session.get(ProductReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(review, field, value)

    product = await session.get(Product, review.product_id)
    rating_result = await session.execute(
        select(
            func.coalesce(func.avg(ProductReview.rating), 0),
            func.count(ProductReview.id),
        ).where(ProductReview.product_id == review.product_id)
    )
    average_rating, review_count = rating_result.one()
    product.rating = round(float(average_rating or 0), 2)
    product.review_count = int(review_count or 0)
    vendor_rating_result = await session.execute(
        select(
            func.coalesce(func.avg(Product.rating), 0),
            func.coalesce(func.sum(Product.review_count), 0),
        ).where(Product.vendor_id == product.vendor_id)
    )
    vendor_rating, vendor_review_count = vendor_rating_result.one()
    vendor = await session.get(Vendor, product.vendor_id)
    if vendor:
        vendor.rating = round(float(vendor_rating or 0), 2)
        vendor.review_count = int(vendor_review_count or 0)

    await session.commit()
    await session.refresh(review)
    return review


@router.get("/promotions", response_model=list[VendorPromotionResponse])
async def get_admin_promotions(
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> list[VendorPromotion]:
    result = await session.execute(
        select(VendorPromotion)
        .options(selectinload(VendorPromotion.product))
        .order_by(VendorPromotion.updated_at.desc())
    )
    return list(result.scalars().all())


@router.patch("/promotions/{promotion_id}", response_model=VendorPromotionResponse)
async def update_admin_promotion_status(
    promotion_id: int,
    payload: AdminVendorPromotionStatusUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> VendorPromotion:
    promotion = await session.get(VendorPromotion, promotion_id)
    if not promotion:
        raise HTTPException(status_code=404, detail="Promotion not found")
    promotion.status = payload.status
    promotion.admin_note = payload.admin_note
    await session.commit()
    await session.refresh(promotion)
    return promotion


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

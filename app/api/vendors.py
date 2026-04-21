from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_vendor, get_db_session
from app.models.payout_request import PayoutRequest
from app.models.order import Order, OrderItem, OrderStatus
from app.models.vendor import Vendor
from app.schemas.common import PayoutRequestCreate, PayoutRequestResponse
from app.schemas.vendor import (
    VendorAnalyticsResponse,
    VendorDetail,
    VendorPayoutSummaryResponse,
    VendorProfileResponse,
    VendorProfileUpdateRequest,
    VendorSummary,
)
from app.services.notifications import create_notification

router = APIRouter(prefix="/vendors", tags=["vendors"])


@router.get("", response_model=list[VendorSummary])
async def list_vendors(
    search: Optional[str] = None,
    category: Optional[str] = None,
    session: AsyncSession = Depends(get_db_session),
) -> list[VendorSummary]:
    query = select(Vendor).where(Vendor.is_active.is_(True))
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(or_(Vendor.name.ilike(pattern), Vendor.description.ilike(pattern)))
    if category and category.lower() != "all":
        query = query.where(Vendor.category.ilike(category))

    result = await session.execute(query.order_by(Vendor.rating.desc(), Vendor.review_count.desc()))
    return list(result.scalars().all())


@router.get("/me/profile", response_model=VendorProfileResponse)
async def get_my_vendor_profile(
    session: AsyncSession = Depends(get_db_session),
    current_vendor: Vendor = Depends(get_current_vendor),
) -> VendorProfileResponse:
    vendor = await session.get(Vendor, current_vendor.id)
    return vendor


@router.put("/me/profile", response_model=VendorProfileResponse)
async def update_my_vendor_profile(
    payload: VendorProfileUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_vendor: Vendor = Depends(get_current_vendor),
) -> VendorProfileResponse:
    vendor = await session.get(Vendor, current_vendor.id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(vendor, field, value)
    await session.commit()
    await session.refresh(vendor)
    return vendor


@router.get("/me/payouts", response_model=VendorPayoutSummaryResponse)
async def get_vendor_payouts(
    session: AsyncSession = Depends(get_db_session),
    current_vendor: Vendor = Depends(get_current_vendor),
) -> VendorPayoutSummaryResponse:
    payout_result = await session.execute(
        select(PayoutRequest)
        .where(PayoutRequest.requester_vendor_id == current_vendor.id, PayoutRequest.requester_role == "vendor")
        .order_by(PayoutRequest.created_at.desc())
        .limit(10)
    )
    revenue_result = await session.execute(select(func.coalesce(func.sum(Order.total_amount), 0)).where(Order.vendor_id == current_vendor.id))
    total_revenue = float(revenue_result.scalar() or 0)
    return VendorPayoutSummaryResponse(
        available_balance=total_revenue,
        total_revenue=total_revenue,
        payout_requests=list(payout_result.scalars().all()),
    )


@router.post("/me/payout-requests", response_model=PayoutRequestResponse)
async def create_vendor_payout_request(
    payload: PayoutRequestCreate,
    session: AsyncSession = Depends(get_db_session),
    current_vendor: Vendor = Depends(get_current_vendor),
) -> PayoutRequestResponse:
    revenue_result = await session.execute(select(func.coalesce(func.sum(Order.total_amount), 0)).where(Order.vendor_id == current_vendor.id))
    total_revenue = float(revenue_result.scalar() or 0)
    if payload.amount > total_revenue:
        raise HTTPException(status_code=400, detail="Requested amount exceeds current vendor balance")
    payout = PayoutRequest(
        requester_role="vendor",
        requester_vendor_id=current_vendor.id,
        requester_name=current_vendor.name,
        requester_email=current_vendor.email,
        amount=payload.amount,
        bank_name=current_vendor.bank_name,
        account_name=current_vendor.bank_account_name,
        account_number=current_vendor.bank_account,
        note=payload.note,
    )
    session.add(payout)
    await create_notification(
        session,
        recipient_role="admin",
        title="New vendor payout request",
        message=f"{current_vendor.name} requested {payload.amount:.2f} for payout.",
        category="payment",
    )
    await session.commit()
    await session.refresh(payout)
    return payout


@router.get("/me/analytics", response_model=VendorAnalyticsResponse)
async def get_my_vendor_analytics(
    session: AsyncSession = Depends(get_db_session),
    current_vendor: Vendor = Depends(get_current_vendor),
) -> VendorAnalyticsResponse:
    vendor = await session.scalar(
        select(Vendor)
        .where(Vendor.id == current_vendor.id)
        .options(selectinload(Vendor.products))
    )
    orders_result = await session.execute(
        select(Order)
        .where(Order.vendor_id == current_vendor.id)
        .options(selectinload(Order.items).selectinload(OrderItem.product))
        .order_by(Order.created_at.desc())
    )
    orders = list(orders_result.scalars().all())

    total_revenue = float(sum(order.total_amount for order in orders))
    total_orders = len(orders)
    active_products = sum(1 for product in vendor.products if product.is_available)
    average_order_value = total_revenue / total_orders if total_orders else 0.0
    pending_orders = sum(1 for order in orders if order.status in {OrderStatus.pending, OrderStatus.confirmed, OrderStatus.preparing, OrderStatus.rider_assigned, OrderStatus.on_the_way})
    completed_orders = sum(1 for order in orders if order.status == OrderStatus.delivered)

    monthly_buckets: dict[str, float] = defaultdict(float)
    status_buckets: dict[str, int] = defaultdict(int)
    product_buckets = defaultdict(lambda: {"units_sold": 0, "revenue": 0.0})

    for order in orders:
        month_key = order.created_at.strftime("%b %Y")
        monthly_buckets[month_key] += float(order.total_amount)
        status_buckets[order.status.value] += 1
        for item in order.items:
            product_name = item.product.name if item.product else f"Product {item.product_id}"
            product_buckets[product_name]["name"] = product_name
            product_buckets[product_name]["units_sold"] += int(item.quantity)
            product_buckets[product_name]["revenue"] += float(item.total_price)

    monthly_revenue = [{"month": month, "revenue": revenue} for month, revenue in monthly_buckets.items()]
    status_breakdown = [{"status": status, "count": count} for status, count in status_buckets.items()]
    top_products = sorted(product_buckets.values(), key=lambda item: item["revenue"], reverse=True)[:5]

    return VendorAnalyticsResponse(
        total_revenue=total_revenue,
        total_orders=total_orders,
        active_products=active_products,
    low_stock_count=sum(
        1
        for product in vendor.products
        if product.stock_quantity <= max(product.low_stock_threshold, 0)
    ),
        average_order_value=average_order_value,
        pending_orders=pending_orders,
        completed_orders=completed_orders,
        monthly_revenue=monthly_revenue,
        status_breakdown=status_breakdown,
        top_products=top_products,
    )


@router.get("/{vendor_id}", response_model=VendorDetail)
async def get_vendor(vendor_id: int, session: AsyncSession = Depends(get_db_session)) -> VendorDetail:
    vendor = await session.scalar(
        select(Vendor)
        .where(Vendor.id == vendor_id, Vendor.is_active.is_(True))
        .options(selectinload(Vendor.products), selectinload(Vendor.reviews))
    )
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return vendor

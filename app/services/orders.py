from collections import defaultdict
from math import asin, cos, radians, sin, sqrt
from typing import Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.address import Address
from app.models.delivery_setting import DeliverySetting
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.vendor import Vendor
from app.schemas.order import CheckoutQuoteItem, CheckoutQuoteResponse, CheckoutRequest

ORDER_STATUS_TIMELINES = {
    OrderStatus.pending: ["Checkout received", "Vendor confirmation pending"],
    OrderStatus.confirmed: ["Checkout received", "Vendor confirmed your order"],
    OrderStatus.preparing: ["Checkout received", "Vendor confirmed your order", "Preparing items"],
    OrderStatus.rider_assigned: [
        "Checkout received",
        "Vendor confirmed your order",
        "Preparing items",
        "Rider assigned",
    ],
    OrderStatus.on_the_way: [
        "Checkout received",
        "Vendor confirmed your order",
        "Preparing items",
        "Rider assigned",
        "On the way",
    ],
    OrderStatus.delivered: [
        "Checkout received",
        "Vendor confirmed your order",
        "Preparing items",
        "Rider assigned",
        "On the way",
        "Delivered",
    ],
    OrderStatus.cancelled: ["Checkout received", "Cancelled"],
}


def _haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    lat1_rad, lon1_rad, lat2_rad, lon2_rad = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    arc = sin(dlat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2) ** 2
    return 2 * radius_km * asin(sqrt(arc))


async def _get_delivery_settings(session: AsyncSession) -> DeliverySetting:
    settings = await session.scalar(select(DeliverySetting).order_by(DeliverySetting.id.asc()))
    if settings:
        return settings

    settings = DeliverySetting(base_fee=0, fee_per_km=0, free_distance_km=0)
    session.add(settings)
    await session.flush()
    return settings


def _calculate_delivery_fee(vendor: Vendor, address: Address, settings: DeliverySetting) -> tuple[float, float]:
    distance_km = 0.0
    if (
        vendor.latitude is not None
        and vendor.longitude is not None
        and address.latitude is not None
        and address.longitude is not None
    ):
        distance_km = _haversine_distance_km(vendor.latitude, vendor.longitude, address.latitude, address.longitude)

    billable_distance = max(distance_km - float(settings.free_distance_km or 0), 0)
    delivery_fee = float(settings.base_fee or 0) + billable_distance * float(settings.fee_per_km or 0)
    return round(delivery_fee, 2), round(distance_km, 2)


async def _build_grouped_checkout_data(
    session: AsyncSession, user_id: int, payload: CheckoutRequest
) -> tuple[Address, dict[int, list[tuple[Product, int, Optional[str]]]], DeliverySetting]:
    address = await session.get(Address, payload.address_id)
    if not address or address.user_id != user_id:
        raise ValueError("Delivery address not found")

    product_ids = [item.product_id for item in payload.items]
    products = (
        await session.execute(
            select(Product)
            .where(Product.id.in_(product_ids), Product.is_available.is_(True))
            .options(selectinload(Product.vendor))
        )
    ).scalars().all()
    product_map = {product.id: product for product in products}

    if len(product_map) != len(product_ids):
        raise ValueError("One or more products are unavailable")

    grouped_items: dict[int, list[tuple[Product, int, Optional[str]]]] = defaultdict(list)
    for item in payload.items:
        product = product_map[item.product_id]
        grouped_items[product.vendor_id].append((product, item.quantity, item.notes))

    settings = await _get_delivery_settings(session)
    return address, grouped_items, settings


async def build_checkout_quote(
    session: AsyncSession, user_id: int, payload: CheckoutRequest
) -> CheckoutQuoteResponse:
    address, grouped_items, settings = await _build_grouped_checkout_data(session, user_id, payload)

    quote_items: list[CheckoutQuoteItem] = []
    subtotal_amount = 0.0
    delivery_fee_total = 0.0

    for vendor_id, vendor_items in grouped_items.items():
        vendor = vendor_items[0][0].vendor
        subtotal = sum(product.price * quantity for product, quantity, _ in vendor_items)
        if subtotal < vendor.minimum_order_amount:
            raise ValueError(f"{vendor.name} requires a minimum order of {vendor.minimum_order_amount:.2f}")

        delivery_fee, distance_km = _calculate_delivery_fee(vendor, address, settings)
        subtotal_amount += subtotal
        delivery_fee_total += delivery_fee
        quote_items.append(
            CheckoutQuoteItem(
                vendor_id=vendor_id,
                vendor_name=vendor.name,
                subtotal_amount=subtotal,
                delivery_fee=delivery_fee,
                distance_km=distance_km,
                total_amount=subtotal + delivery_fee,
            )
        )

    return CheckoutQuoteResponse(
        subtotal_amount=round(subtotal_amount, 2),
        delivery_fee=round(delivery_fee_total, 2),
        total_amount=round(subtotal_amount + delivery_fee_total, 2),
        items=quote_items,
    )


async def create_checkout(session: AsyncSession, user_id: int, payload: CheckoutRequest) -> tuple[str, list[Order]]:
    address, grouped_items, settings = await _build_grouped_checkout_data(session, user_id, payload)

    order_reference = f"QD-{uuid4().hex[:10].upper()}"
    created_orders: list[Order] = []

    for vendor_id, vendor_items in grouped_items.items():
        vendor = vendor_items[0][0].vendor
        subtotal = sum(product.price * quantity for product, quantity, _ in vendor_items)
        if subtotal < vendor.minimum_order_amount:
            raise ValueError(f"{vendor.name} requires a minimum order of {vendor.minimum_order_amount:.2f}")
        delivery_fee, _distance_km = _calculate_delivery_fee(vendor, address, settings)

        order = Order(
            order_reference=order_reference,
            user_id=user_id,
            vendor_id=vendor_id,
            address_id=address.id,
            status=OrderStatus.pending,
            subtotal_amount=subtotal,
            delivery_fee=delivery_fee,
            total_amount=subtotal + delivery_fee,
            payment_method=payload.payment_method,
            payment_status="pending",
            payment_reference=payload.payment_reference,
            tracking_note="Preparing your dispatch window.",
        )
        session.add(order)
        await session.flush()

        for product, quantity, notes in vendor_items:
            session.add(
                OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    quantity=quantity,
                    unit_price=product.price,
                    total_price=product.price * quantity,
                    notes=notes,
                )
            )

        created_orders.append(order)

    await session.commit()

    for order in created_orders:
        await session.refresh(order)

    return order_reference, created_orders


def build_timeline(status: OrderStatus) -> list[dict[str, str]]:
    items = ORDER_STATUS_TIMELINES[status]
    return [
        {"label": label, "state": "complete" if index < len(items) - 1 else "current"}
        for index, label in enumerate(items)
    ]


async def get_order_with_relations(
    session: AsyncSession, order_id: int, user_id: int
) -> Optional[Order]:
    return await session.scalar(
        select(Order)
        .where(Order.id == order_id, Order.user_id == user_id)
        .options(
            selectinload(Order.vendor),
            selectinload(Order.user),
            selectinload(Order.rider),
            selectinload(Order.address),
            selectinload(Order.items).selectinload(OrderItem.product),
        )
    )


async def get_orders_for_user(session: AsyncSession, user_id: int) -> list[Order]:
    result = await session.execute(
        select(Order)
        .where(Order.user_id == user_id)
        .options(
            selectinload(Order.vendor),
            selectinload(Order.user),
            selectinload(Order.rider),
            selectinload(Order.address),
            selectinload(Order.items).selectinload(OrderItem.product),
        )
        .order_by(Order.created_at.desc())
    )
    return list(result.scalars().all())

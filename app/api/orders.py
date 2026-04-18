from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.models.user import User
from app.schemas.order import CheckoutRequest, CheckoutResponse, OrderResponse, OrderStatusResponse
from app.services.orders import build_timeline, create_checkout, get_order_with_relations, get_orders_for_user

router = APIRouter(prefix="/orders", tags=["orders"])


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
        address=order.address,
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
            hydrated_orders.append(serialize_order(hydrated))

    return CheckoutResponse(
        order_reference=order_reference,
        orders=hydrated_orders,
        total_amount=sum(order.total_amount for order in hydrated_orders),
    )


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
    )


@router.get("/user/history", response_model=list[OrderResponse])
async def get_user_orders(
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> list[OrderResponse]:
    orders = await get_orders_for_user(session, current_user.id)
    return [serialize_order(order) for order in orders]

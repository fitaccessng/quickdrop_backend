from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.order import OrderStatus


class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int = Field(ge=1, le=99)
    notes: Optional[str] = Field(default=None, max_length=255)


class CheckoutRequest(BaseModel):
    address_id: int
    payment_method: str = Field(min_length=2, max_length=50)
    payment_reference: Optional[str] = Field(default=None, max_length=120)
    items: list[OrderItemCreate] = Field(min_length=1)


class OrderItemResponse(BaseModel):
    id: int
    product_id: int
    quantity: int
    unit_price: float
    total_price: float
    notes: Optional[str] = None
    product_name: str


class OrderVendorSummary(BaseModel):
    id: int
    name: str
    category: str
    logo_url: Optional[str] = None

    class Config:
        from_attributes = True


class OrderAddressSummary(BaseModel):
    id: int
    label: str
    line1: str
    city: str
    state: str

    class Config:
        from_attributes = True


class OrderResponse(BaseModel):
    id: int
    order_reference: str
    status: OrderStatus
    subtotal_amount: float
    delivery_fee: float
    total_amount: float
    payment_method: str
    payment_status: str
    payment_reference: Optional[str] = None
    tracking_note: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    vendor: OrderVendorSummary
    address: OrderAddressSummary
    items: list[OrderItemResponse]


class CheckoutResponse(BaseModel):
    order_reference: str
    orders: list[OrderResponse]
    total_amount: float


class OrderStatusResponse(BaseModel):
    id: int
    order_reference: str
    status: OrderStatus
    tracking_note: Optional[str] = None
    updated_at: datetime
    timeline: list[dict[str, str]]

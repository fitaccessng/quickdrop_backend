from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.order import OrderStatus


class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int = Field(ge=1, le=99)
    notes: Optional[str] = Field(default=None, max_length=255)


class CheckoutRequest(BaseModel):
    address_id: int
    address_latitude: Optional[float] = None
    address_longitude: Optional[float] = None
    payment_method: str = Field(min_length=2, max_length=50)
    payment_reference: Optional[str] = Field(default=None, max_length=120)
    items: list[OrderItemCreate] = Field(min_length=1)

    @field_validator("payment_method")
    @classmethod
    def validate_payment_method(cls, value: str) -> str:
        allowed_methods = {"paystack", "cash_on_delivery"}
        normalized_value = value.strip().lower()
        if normalized_value not in allowed_methods:
            raise ValueError("Unsupported payment method.")
        return normalized_value


class CheckoutQuoteItem(BaseModel):
    vendor_id: int
    vendor_name: str
    subtotal_amount: float
    delivery_fee: float
    distance_km: float
    total_amount: float


class CheckoutQuoteResponse(BaseModel):
    subtotal_amount: float
    delivery_fee: float
    total_amount: float
    currency: str = "ZAR"
    items: list[CheckoutQuoteItem]


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
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    class Config:
        from_attributes = True


class OrderUserSummary(BaseModel):
    id: int
    full_name: str
    email: str
    phone: Optional[str] = None

    class Config:
        from_attributes = True


class RiderSummary(BaseModel):
    id: int
    full_name: str
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    vehicle_type: Optional[str] = None
    rider_status: Optional[str] = None

    class Config:
        from_attributes = True


class OrderTrackingLocation(BaseModel):
    latitude: float
    longitude: float


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
    customer: Optional[OrderUserSummary] = None
    rider: Optional[RiderSummary] = None
    address: OrderAddressSummary
    items: list[OrderItemResponse]
    tracking_latitude: Optional[float] = None
    tracking_longitude: Optional[float] = None
    destination_latitude: Optional[float] = None
    destination_longitude: Optional[float] = None
    rider_location: Optional[OrderTrackingLocation] = None
    route_geometry: list[list[float]] = []
    distance_meters_remaining: Optional[float] = None
    duration_seconds_remaining: Optional[float] = None
    estimated_arrival_seconds: Optional[int] = None


class CheckoutResponse(BaseModel):
    order_reference: str
    orders: list[OrderResponse]
    total_amount: float


class CheckoutInitializationResponse(BaseModel):
    authorization_url: str
    access_code: str
    reference: str


class OrderStatusResponse(BaseModel):
    id: int
    order_reference: str
    status: OrderStatus
    tracking_note: Optional[str] = None
    updated_at: datetime
    timeline: list[dict[str, str]]
    rider: Optional[RiderSummary] = None
    tracking_latitude: Optional[float] = None
    tracking_longitude: Optional[float] = None
    destination_latitude: Optional[float] = None
    destination_longitude: Optional[float] = None
    rider_location: Optional[OrderTrackingLocation] = None
    route_geometry: list[list[float]] = []
    distance_meters_remaining: Optional[float] = None
    duration_seconds_remaining: Optional[float] = None
    estimated_arrival_seconds: Optional[int] = None


class VendorOrderStatusUpdate(BaseModel):
    status: OrderStatus
    tracking_note: Optional[str] = Field(default=None, max_length=500)
    rider_id: Optional[int] = Field(default=None, ge=1)


class VendorOrderResponse(BaseModel):
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
    customer: OrderUserSummary
    rider: Optional[RiderSummary] = None
    address: OrderAddressSummary
    items: list[OrderItemResponse]
    tracking_latitude: Optional[float] = None
    tracking_longitude: Optional[float] = None
    destination_latitude: Optional[float] = None
    destination_longitude: Optional[float] = None
    rider_location: Optional[OrderTrackingLocation] = None
    route_geometry: list[list[float]] = []
    distance_meters_remaining: Optional[float] = None
    duration_seconds_remaining: Optional[float] = None
    estimated_arrival_seconds: Optional[int] = None

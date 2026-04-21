from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.order import OrderStatus
from app.schemas.common import PayoutRequestResponse
from app.schemas.order import OrderAddressSummary, OrderUserSummary, OrderVendorSummary, RiderSummary


class RiderProfileResponse(BaseModel):
    id: int
    full_name: str
    email: str
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    street: Optional[str] = None
    po_box: Optional[str] = None
    vehicle_type: Optional[str] = None
    license_number: Optional[str] = None
    rider_status: str
    wallet_balance: float
    total_earnings: float
    total_deliveries: int
    current_latitude: Optional[float] = None
    current_longitude: Optional[float] = None
    is_onboarded: bool

    class Config:
        from_attributes = True


class RiderProfileUpdateRequest(BaseModel):
    phone: Optional[str] = Field(default=None, max_length=30)
    avatar_url: Optional[str] = None
    city: Optional[str] = Field(default=None, min_length=2, max_length=120)
    state: Optional[str] = Field(default=None, min_length=2, max_length=120)
    street: Optional[str] = Field(default=None, min_length=2, max_length=255)
    po_box: Optional[str] = Field(default=None, max_length=50)
    vehicle_type: Optional[str] = Field(default=None, min_length=2, max_length=40)
    license_number: Optional[str] = Field(default=None, min_length=3, max_length=80)
    rider_status: Optional[str] = Field(default=None, min_length=2, max_length=40)
    current_latitude: Optional[float] = None
    current_longitude: Optional[float] = None


class RiderOrderResponse(BaseModel):
    id: int
    order_reference: str
    status: OrderStatus
    total_amount: float
    delivery_fee: float
    tracking_note: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    vendor: OrderVendorSummary
    customer: OrderUserSummary
    address: OrderAddressSummary
    rider: Optional[RiderSummary] = None
    tracking_latitude: Optional[float] = None
    tracking_longitude: Optional[float] = None


class RiderDashboardResponse(BaseModel):
    rider: RiderProfileResponse
    pending_requests: int
    active_deliveries: int
    completed_deliveries: int
    total_earnings: float
    wallet_balance: float
    today_earnings: float
    active_order: Optional[RiderOrderResponse] = None


class RiderAnalyticsResponse(BaseModel):
    total_earnings: float
    wallet_balance: float
    total_deliveries: int
    active_deliveries: int
    pending_requests: int
    today_earnings: float
    weekly_earnings: list[dict]
    delivery_completion_rate: float


class RiderWalletResponse(BaseModel):
    wallet_balance: float
    total_earnings: float
    completed_deliveries: int
    available_payout: float
    payout_requests: list[PayoutRequestResponse]
    recent_deliveries: list[RiderOrderResponse]


class RiderAcceptOrderRequest(BaseModel):
    current_latitude: Optional[float] = None
    current_longitude: Optional[float] = None


class RiderOrderUpdateRequest(BaseModel):
    status: OrderStatus
    tracking_note: Optional[str] = Field(default=None, max_length=500)
    tracking_latitude: Optional[float] = None
    tracking_longitude: Optional[float] = None


class RiderLocationUpdateRequest(BaseModel):
    tracking_latitude: float
    tracking_longitude: float

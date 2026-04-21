from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr

from app.schemas.common import PayoutRequestResponse
from app.schemas.order import RiderSummary


class AdminSummaryResponse(BaseModel):
    total_users: int
    total_vendors: int
    pending_vendors: int
    total_riders: int
    active_orders: int
    completed_orders: int
    payout_requests_pending: int
    recent_payout_requests: list[PayoutRequestResponse]


class AdminVendorItem(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str] = None
    category: str
    city: str
    is_onboarded: bool
    is_approved: bool
    created_at: datetime

    class Config:
        from_attributes = True


class AdminVendorApprovalRequest(BaseModel):
    is_approved: bool


class AdminVendorAnalyticsResponse(BaseModel):
    vendor_id: int
    vendor_name: str
    total_orders: int
    completed_orders: int
    pending_orders: int
    total_revenue: float
    average_order_value: float
    top_products: list[dict]


class AdminUserItem(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    phone: Optional[str] = None
    role: str
    is_active: bool
    is_onboarded: bool
    city: Optional[str] = None
    state: Optional[str] = None
    vehicle_type: Optional[str] = None
    rider_status: Optional[str] = None
    total_earnings: float = 0
    total_deliveries: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class AdminUserDetailResponse(AdminUserItem):
    street: Optional[str] = None
    po_box: Optional[str] = None
    license_number: Optional[str] = None
    wallet_balance: float = 0


class AdminOrderItem(BaseModel):
    id: int
    order_reference: str
    status: str
    total_amount: float
    delivery_fee: float
    created_at: datetime
    updated_at: datetime
    vendor_name: str
    customer_name: str
    rider: Optional[RiderSummary] = None
    tracking_note: Optional[str] = None
    tracking_latitude: Optional[float] = None
    tracking_longitude: Optional[float] = None


class AdminAssignRiderRequest(BaseModel):
    rider_id: int


class AdminProfileResponse(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    phone: Optional[str] = None
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


class AdminProfileUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None


class ServiceCategoryResponse(BaseModel):
    id: int
    name: str
    slug: str
    description: Optional[str] = None
    is_active: bool

    class Config:
        from_attributes = True


class ServiceCategoryCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    is_active: bool = True


class ServiceCategoryUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class DeliveryPricingSettingsResponse(BaseModel):
    base_fee: float
    fee_per_km: float
    free_distance_km: float

    class Config:
        from_attributes = True


class DeliveryPricingSettingsUpdateRequest(BaseModel):
    base_fee: float
    fee_per_km: float
    free_distance_km: float = 0

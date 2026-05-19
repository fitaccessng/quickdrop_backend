from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr

from app.schemas.common import PayoutRequestResponse
from app.schemas.order import RiderSummary
from app.schemas.product import ProductReviewResponse
from app.schemas.vendor import VendorPromotionResponse


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
    vendor_slug: str
    vendor_email: str
    vendor_phone: Optional[str] = None
    logo_url: Optional[str] = None
    cover_image_url: Optional[str] = None
    category: str
    city: str
    street: Optional[str] = None
    po_box: Optional[str] = None
    description: str
    business_registration_number: Optional[str] = None
    vat_number: Optional[str] = None
    south_african_id_number: Optional[str] = None
    tin: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    permit_url: Optional[str] = None
    opening_hours: Optional[dict] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    minimum_order_amount: float
    delivery_fee: float
    prep_time_minutes: int
    support_email: Optional[str] = None
    support_phone: Optional[str] = None
    delivery_radius_km: float
    auto_accept_orders: bool
    notifications_enabled: bool
    is_onboarded: bool
    is_approved: bool
    rating: float
    review_count: int
    created_at: datetime
    total_orders: int
    completed_orders: int
    pending_orders: int
    cancelled_orders: int
    active_orders: int
    total_revenue: float
    average_order_value: float
    average_vendor_response_minutes: float
    fastest_vendor_response_minutes: Optional[float] = None
    slowest_vendor_response_minutes: Optional[float] = None
    top_products: list[dict]
    uploaded_products: list[dict]
    product_reviews: list[ProductReviewResponse]
    promotions: list[VendorPromotionResponse]
    recent_orders: list["AdminOrderItem"]


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
    avatar_url: Optional[str] = None
    current_latitude: Optional[float] = None
    current_longitude: Optional[float] = None
    updated_at: Optional[datetime] = None
    addresses: list[dict] = []
    recent_orders: list["AdminOrderItem"] = []


class AdminProductReviewUpdateRequest(BaseModel):
    rating: Optional[int] = None
    comment: Optional[str] = None


class AdminVendorPromotionStatusUpdateRequest(BaseModel):
    status: str
    admin_note: Optional[str] = None


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
    rider_location: Optional[dict] = None
    route_geometry: list[list[float]] = []
    distance_meters_remaining: Optional[float] = None
    duration_seconds_remaining: Optional[float] = None
    estimated_arrival_seconds: Optional[int] = None
    destination_latitude: Optional[float] = None
    destination_longitude: Optional[float] = None
    rider_current_latitude: Optional[float] = None
    rider_current_longitude: Optional[float] = None
    items: list[dict] = []


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


class ServiceCategoryOverviewResponse(ServiceCategoryResponse):
    product_count: int = 0


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
    bike_surcharge: float
    car_surcharge: float
    xl_surcharge: float
    rider_payout_percentage: float

    class Config:
        from_attributes = True


class DeliveryPricingSettingsUpdateRequest(BaseModel):
    base_fee: float
    fee_per_km: float
    free_distance_km: float = 0
    bike_surcharge: float = 0
    car_surcharge: float = 0
    xl_surcharge: float = 0
    rider_payout_percentage: float = 30


AdminVendorAnalyticsResponse.model_rebuild()

from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.common import PayoutRequestResponse
from app.schemas.product import ProductSummary


class VendorReviewResponse(BaseModel):
    id: int
    author_name: str
    rating: int
    comment: str

    class Config:
        from_attributes = True


class VendorSummary(BaseModel):
    id: int
    name: str
    slug: str
    category: str
    description: str
    logo_url: Optional[str] = None
    cover_image_url: Optional[str] = None
    city: str
    prep_time_minutes: int
    delivery_fee: float
    minimum_order_amount: float
    rating: float
    review_count: int

    class Config:
        from_attributes = True


class VendorDetail(VendorSummary):
    products: list[ProductSummary]
    reviews: list[VendorReviewResponse]


class VendorProfileResponse(VendorSummary):
    email: str
    phone: Optional[str] = None
    street: Optional[str] = None
    po_box: Optional[str] = None
    tin: Optional[str] = None
    business_registration_number: Optional[str] = None
    vat_number: Optional[str] = None
    south_african_id_number: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account_name: Optional[str] = None
    bank_account: Optional[str] = None
    permit_url: Optional[str] = None
    opening_hours: Optional[dict] = None
    delivery_radius_km: float = 5
    auto_accept_orders: bool = False
    notifications_enabled: bool = True
    support_email: Optional[str] = None
    support_phone: Optional[str] = None
    is_onboarded: bool
    is_approved: bool


class VendorProfileUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    phone: Optional[str] = Field(default=None, max_length=30)
    category: Optional[str] = Field(default=None, min_length=2, max_length=80)
    description: Optional[str] = Field(default=None, min_length=10, max_length=2000)
    logo_url: Optional[str] = Field(default=None, max_length=500)
    cover_image_url: Optional[str] = Field(default=None, max_length=500)
    city: Optional[str] = Field(default=None, min_length=2, max_length=120)
    street: Optional[str] = Field(default=None, max_length=255)
    po_box: Optional[str] = Field(default=None, max_length=50)
    prep_time_minutes: Optional[int] = Field(default=None, ge=1, le=240)
    delivery_fee: Optional[float] = Field(default=None, ge=0)
    minimum_order_amount: Optional[float] = Field(default=None, ge=0)
    tin: Optional[str] = Field(default=None, max_length=50)
    business_registration_number: Optional[str] = Field(default=None, max_length=120)
    vat_number: Optional[str] = Field(default=None, max_length=60)
    south_african_id_number: Optional[str] = Field(default=None, max_length=30)
    bank_name: Optional[str] = Field(default=None, max_length=120)
    bank_account_name: Optional[str] = Field(default=None, max_length=120)
    bank_account: Optional[str] = Field(default=None, max_length=50)
    permit_url: Optional[str] = Field(default=None, max_length=500)
    opening_hours: Optional[dict] = None
    delivery_radius_km: Optional[float] = Field(default=None, ge=0, le=100)
    auto_accept_orders: Optional[bool] = None
    notifications_enabled: Optional[bool] = None
    support_email: Optional[str] = Field(default=None, max_length=255)
    support_phone: Optional[str] = Field(default=None, max_length=30)


class VendorRevenuePoint(BaseModel):
    month: str
    revenue: float


class VendorStatusPoint(BaseModel):
    status: str
    count: int


class VendorTopProductPoint(BaseModel):
    name: str
    units_sold: int
    revenue: float


class VendorAnalyticsResponse(BaseModel):
    total_revenue: float
    total_orders: int
    active_products: int
    low_stock_count: int
    average_order_value: float
    pending_orders: int
    completed_orders: int
    monthly_revenue: list[VendorRevenuePoint]
    status_breakdown: list[VendorStatusPoint]
    top_products: list[VendorTopProductPoint]


class VendorPayoutSummaryResponse(BaseModel):
    available_balance: float
    total_revenue: float
    payout_requests: list[PayoutRequestResponse]

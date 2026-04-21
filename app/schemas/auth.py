from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=30)
    password: str = Field(min_length=8, max_length=128)


class UnifiedSignupRequest(BaseModel):
    """Unified signup for customers, vendors, and riders"""
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=30)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="customer")  # customer, vendor, rider
    # For vendors
    business_name: Optional[str] = Field(default=None, min_length=5, max_length=160)
    category: Optional[str] = Field(default=None, min_length=2, max_length=80)
    city: Optional[str] = Field(default=None, min_length=2, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=8, max_length=2048)
    password: str = Field(min_length=8, max_length=128)


class ForgotPasswordResponse(BaseModel):
    message: str
    reset_token: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    account_type: str = "user"


class AuthUser(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    phone: Optional[str] = None

    class Config:
        from_attributes = True


class AuthResponse(TokenResponse):
    user: AuthUser


class UnifiedAuthUser(BaseModel):
    """User data for unified login - works for both customer and vendor"""
    id: int
    email: EmailStr
    phone: Optional[str] = None
    # Customer fields
    full_name: Optional[str] = None
    # Vendor fields
    name: Optional[str] = None
    slug: Optional[str] = None
    category: Optional[str] = None
    city: Optional[str] = None
    avatar_url: Optional[str] = None
    vehicle_type: Optional[str] = None
    role: Optional[str] = None
    is_onboarded: Optional[bool] = None

    class Config:
        from_attributes = True


class UnifiedAuthResponse(TokenResponse):
    """Unified response for both customer and vendor login"""
    account_type: str  # "user" or "vendor"
    user: UnifiedAuthUser


class VendorRegisterRequest(BaseModel):
    business_name: str = Field(min_length=5, max_length=160)
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=30)
    password: str = Field(min_length=8, max_length=128)
    category: str = Field(min_length=2, max_length=80)
    city: str = Field(min_length=2, max_length=120)


class VendorLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class VendorForgotPasswordRequest(BaseModel):
    email: EmailStr


class VendorResetPasswordRequest(BaseModel):
    token: str = Field(min_length=8, max_length=120)
    password: str = Field(min_length=8, max_length=128)


class VendorOnboardingRequest(BaseModel):
    description: str = Field(min_length=10, max_length=1000)
    category: str = Field(min_length=2, max_length=80)
    street: str = Field(min_length=3, max_length=255)
    po_box: Optional[str] = Field(default=None, max_length=50)
    city: str = Field(min_length=2, max_length=120)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    minimum_order_amount: float = Field(ge=0)
    prep_time_minutes: int = Field(ge=1, le=240)
    logo_url: Optional[str] = Field(default=None, max_length=500)
    cover_image_url: Optional[str] = Field(default=None, max_length=500)
    tin: Optional[str] = Field(default=None, max_length=50)
    business_registration_number: Optional[str] = Field(default=None, max_length=120)
    vat_number: Optional[str] = Field(default=None, max_length=60)
    south_african_id_number: Optional[str] = Field(default=None, max_length=30)
    bank_name: Optional[str] = Field(default=None, max_length=120)
    bank_account_name: Optional[str] = Field(default=None, max_length=120)
    bank_account: Optional[str] = Field(default=None, max_length=50)
    permit_url: Optional[str] = Field(default=None, max_length=500)
    opening_hours: Optional[dict] = Field(default=None, description="Opening hours by day of week")
    delivery_radius_km: float = Field(default=5, ge=0, le=100)
    auto_accept_orders: bool = False
    notifications_enabled: bool = True
    support_email: Optional[str] = Field(default=None, max_length=255)
    support_phone: Optional[str] = Field(default=None, max_length=30)


class VendorAuthUser(BaseModel):
    id: int
    name: str
    slug: str
    email: EmailStr
    phone: Optional[str] = None
    category: str
    city: str
    is_onboarded: bool
    is_approved: bool

    class Config:
        from_attributes = True


class VendorAuthResponse(TokenResponse):
    account_type: str = "vendor"
    user: VendorAuthUser


class VendorForgotPasswordResponse(BaseModel):
    message: str
    reset_token: str


# OAuth Request Schemas
class GoogleOAuthRequest(BaseModel):
    token: str = Field(min_length=10, max_length=2000, description="Google ID token")


class AppleOAuthRequest(BaseModel):
    token: str = Field(min_length=10, max_length=5000, description="Apple ID token")
    user: Optional[dict] = Field(default=None, description="Apple user data (for first-time signup)")


class GoogleOAuthUser(BaseModel):
    """Google OAuth user data extracted from token"""

    id: str
    email: str
    name: str
    picture: Optional[str] = None


class AppleOAuthUser(BaseModel):
    """Apple OAuth user data extracted from token"""

    id: str
    email: str
    name: Optional[str] = None

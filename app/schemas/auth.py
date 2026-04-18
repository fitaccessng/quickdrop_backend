from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=30)
    password: str = Field(min_length=8, max_length=128)


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
    minimum_order_amount: float = Field(ge=0)
    prep_time_minutes: int = Field(ge=1, le=240)
    logo_url: Optional[str] = Field(default=None, max_length=500)
    cover_image_url: Optional[str] = Field(default=None, max_length=500)
    tin: Optional[str] = Field(default=None, max_length=50)
    bank_name: Optional[str] = Field(default=None, max_length=120)
    bank_account: Optional[str] = Field(default=None, max_length=50)
    permit_url: Optional[str] = Field(default=None, max_length=500)
    opening_hours: Optional[dict] = Field(default=None, description="Opening hours by day of week")


class VendorAuthUser(BaseModel):
    id: int
    name: str
    slug: str
    email: EmailStr
    phone: Optional[str] = None
    category: str
    city: str
    is_onboarded: bool

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

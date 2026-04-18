import re
from uuid import uuid4
import jwt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from google.auth.transport import requests
from google.oauth2 import id_token

from app.core.security import (
    create_password_reset_token,
    decode_password_reset_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.models.vendor import Vendor
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    VendorForgotPasswordRequest,
    VendorLoginRequest,
    VendorOnboardingRequest,
    VendorRegisterRequest,
    VendorResetPasswordRequest,
    GoogleOAuthUser,
    AppleOAuthUser,
)


async def register_user(session: AsyncSession, payload: RegisterRequest) -> User:
    existing_user = await session.scalar(select(User).where(User.email == payload.email.lower()))
    if existing_user:
        raise ValueError("An account with this email already exists")

    user = User(
        full_name=payload.full_name,
        email=payload.email.lower(),
        phone=payload.phone,
        hashed_password=hash_password(payload.password),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def authenticate_user(session: AsyncSession, payload: LoginRequest) -> User:
    user = await session.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.hashed_password):
        raise ValueError("Invalid email or password")
    return user


async def create_user_reset_token(session: AsyncSession, payload: ForgotPasswordRequest) -> str:
    user = await session.scalar(select(User).where(User.email == payload.email.lower()))
    if not user:
        raise ValueError("User account not found")

    return create_password_reset_token(str(user.id), "user")


async def reset_user_password(session: AsyncSession, payload: ResetPasswordRequest) -> User:
    token_payload = decode_password_reset_token(payload.token, "user")

    try:
        user_id = int(token_payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid or expired reset token") from exc

    user = await session.get(User, user_id)
    if not user or not user.is_active:
        raise ValueError("User not found")

    user.hashed_password = hash_password(payload.password)
    await session.commit()
    await session.refresh(user)
    return user


def slugify(value: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return base or "vendor"


async def build_unique_vendor_slug(session: AsyncSession, business_name: str) -> str:
    base_slug = slugify(business_name)
    slug = base_slug
    suffix = 1

    while await session.scalar(select(Vendor.id).where(Vendor.slug == slug)):
        suffix += 1
        slug = f"{base_slug}-{suffix}"

    return slug


async def register_vendor(session: AsyncSession, payload: VendorRegisterRequest) -> Vendor:
    existing_vendor = await session.scalar(select(Vendor).where(Vendor.email == payload.email.lower()))
    if existing_vendor:
        raise ValueError("A vendor account with this email already exists")

    vendor = Vendor(
        name=payload.business_name,
        slug=await build_unique_vendor_slug(session, payload.business_name),
        email=payload.email.lower(),
        phone=payload.phone,
        hashed_password=hash_password(payload.password),
        category=payload.category,
        description="Complete onboarding to publish your storefront.",
        city=payload.city,
        is_active=True,
        is_onboarded=False,
    )
    session.add(vendor)
    await session.commit()
    await session.refresh(vendor)
    return vendor


async def authenticate_vendor(session: AsyncSession, payload: VendorLoginRequest) -> Vendor:
    vendor = await session.scalar(select(Vendor).where(Vendor.email == payload.email.lower()))
    if not vendor or not verify_password(payload.password, vendor.hashed_password):
        raise ValueError("Invalid email or password")
    return vendor


async def create_vendor_reset_token(session: AsyncSession, payload: VendorForgotPasswordRequest) -> str:
    vendor = await session.scalar(select(Vendor).where(Vendor.email == payload.email.lower()))
    if not vendor:
        raise ValueError("Vendor account not found")

    vendor.reset_token = uuid4().hex
    await session.commit()
    return vendor.reset_token


async def reset_vendor_password(session: AsyncSession, payload: VendorResetPasswordRequest) -> Vendor:
    vendor = await session.scalar(select(Vendor).where(Vendor.reset_token == payload.token))
    if not vendor:
        raise ValueError("Invalid or expired reset token")

    vendor.hashed_password = hash_password(payload.password)
    vendor.reset_token = None
    await session.commit()
    await session.refresh(vendor)
    return vendor


async def complete_vendor_onboarding(
    session: AsyncSession, vendor: Vendor, payload: VendorOnboardingRequest
) -> Vendor:
    vendor.description = payload.description
    vendor.minimum_order_amount = payload.minimum_order_amount
    vendor.prep_time_minutes = payload.prep_time_minutes
    vendor.logo_url = payload.logo_url
    vendor.cover_image_url = payload.cover_image_url
    vendor.tin = payload.tin
    vendor.bank_name = payload.bank_name
    vendor.bank_account = payload.bank_account
    vendor.permit_url = payload.permit_url
    vendor.opening_hours = payload.opening_hours
    vendor.is_onboarded = True

    await session.commit()
    await session.refresh(vendor)
    return vendor


# ============================================
# OAuth Service Functions
# ============================================


async def validate_google_token(token: str, google_client_id: str) -> GoogleOAuthUser:
    """
    Validate Google ID token and extract user information.
    
    Args:
        token: Google ID token from frontend
        google_client_id: Google Client ID for validation
        
    Returns:
        GoogleOAuthUser with id, email, name, picture
        
    Raises:
        ValueError: If token is invalid
    """
    try:
        # Verify and decode the Google ID token
        idinfo = id_token.verify_oauth2_token(token, requests.Request(), google_client_id)
        
        # Token is valid, extract user information
        if idinfo["iss"] not in ["accounts.google.com", "https://accounts.google.com"]:
            raise ValueError("Invalid token issuer")
        
        return GoogleOAuthUser(
            id=idinfo["sub"],  # Google User ID
            email=idinfo.get("email", "").lower(),
            name=idinfo.get("name", ""),
            picture=idinfo.get("picture"),
        )
    except Exception as e:
        raise ValueError(f"Invalid Google token: {str(e)}")


async def validate_apple_token(token: str, apple_team_id: str, apple_client_id: str) -> AppleOAuthUser:
    """
    Validate Apple ID token and extract user information.
    
    Note: For production, you should verify the token's signature using Apple's public keys.
    This is a simplified version. For full implementation, fetch keys from:
    https://appleid.apple.com/auth/keys
    
    Args:
        token: Apple ID token from frontend
        apple_team_id: Apple Team ID
        apple_client_id: Apple Service ID
        
    Returns:
        AppleOAuthUser with id, email, name
        
    Raises:
        ValueError: If token is invalid
    """
    try:
        # Decode without verification for now (WARNING: In production, verify signature!)
        # For production implementation, fetch Apple's public keys and verify signature
        decoded = jwt.decode(token, options={"verify_signature": False})
        
        # Validate token claims
        if decoded.get("aud") != apple_client_id:
            raise ValueError("Invalid audience")
        
        if decoded.get("iss") != "https://appleid.apple.com":
            raise ValueError("Invalid issuer")
        
        return AppleOAuthUser(
            id=decoded.get("sub", ""),  # Apple User ID (unique per app)
            email=decoded.get("email", "").lower() if decoded.get("email") else "",
            name=decoded.get("name"),
        )
    except Exception as e:
        raise ValueError(f"Invalid Apple token: {str(e)}")


async def get_or_create_user_from_google(session: AsyncSession, google_user: GoogleOAuthUser) -> User:
    """
    Get existing user or create new user from Google OAuth data.
    
    Args:
        session: Database session
        google_user: Google OAuth user data
        
    Returns:
        User object
        
    Raises:
        ValueError: If there's a conflict with existing email
    """
    # Try to find existing user by email
    existing_user = await session.scalar(select(User).where(User.email == google_user.email))
    
    if existing_user:
        return existing_user
    
    # Create new user from Google data
    # Use a random password since OAuth users don't need password-based login
    random_password = hash_password(uuid4().hex)
    
    user = User(
        full_name=google_user.name or "User",
        email=google_user.email,
        hashed_password=random_password,
        is_active=True,
    )
    
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def get_or_create_user_from_apple(session: AsyncSession, apple_user: AppleOAuthUser) -> User:
    """
    Get existing user or create new user from Apple OAuth data.
    
    Args:
        session: Database session
        apple_user: Apple OAuth user data
        
    Returns:
        User object
        
    Raises:
        ValueError: If there's a conflict with existing email
    """
    # For Apple, email might be hidden - use apple ID as fallback
    email = apple_user.email if apple_user.email else f"{apple_user.id}@appleid.quickdrop.local"
    
    # Try to find existing user by email if available
    if apple_user.email:
        existing_user = await session.scalar(select(User).where(User.email == apple_user.email))
        if existing_user:
            return existing_user
    
    # Create new user from Apple data
    random_password = hash_password(uuid4().hex)
    
    user = User(
        full_name=apple_user.name or "User",
        email=email,
        hashed_password=random_password,
        is_active=True,
    )
    
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user

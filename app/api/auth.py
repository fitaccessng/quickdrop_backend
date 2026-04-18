from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import os

from app.api.deps import get_current_vendor, get_db_session
from app.core.security import create_access_token
from app.models.vendor import Vendor
from app.schemas.auth import (
    AuthResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    RegisterRequest,
    VendorAuthResponse,
    VendorForgotPasswordRequest,
    VendorForgotPasswordResponse,
    VendorLoginRequest,
    VendorOnboardingRequest,
    VendorRegisterRequest,
    VendorResetPasswordRequest,
    ResetPasswordRequest,
    GoogleOAuthRequest,
    AppleOAuthRequest,
)
from app.services.auth import (
    authenticate_user,
    authenticate_vendor,
    complete_vendor_onboarding,
    create_user_reset_token,
    create_vendor_reset_token,
    register_user,
    register_vendor,
    reset_user_password,
    reset_vendor_password,
    validate_google_token,
    validate_apple_token,
    get_or_create_user_from_google,
    get_or_create_user_from_apple,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, session: AsyncSession = Depends(get_db_session)) -> AuthResponse:
    try:
        user = await register_user(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return AuthResponse(access_token=create_access_token(str(user.id), "user"), user=user)


@router.post("/login", response_model=AuthResponse)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_db_session)) -> AuthResponse:
    try:
        user = await authenticate_user(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return AuthResponse(access_token=create_access_token(str(user.id), "user"), user=user)


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(
    payload: ForgotPasswordRequest, session: AsyncSession = Depends(get_db_session)
) -> ForgotPasswordResponse:
    try:
        token = await create_user_reset_token(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return ForgotPasswordResponse(
        message="Reset token generated. Connect this to email delivery in production.",
        reset_token=token,
    )


@router.post("/reset-password", response_model=AuthResponse)
async def reset_password(
    payload: ResetPasswordRequest, session: AsyncSession = Depends(get_db_session)
) -> AuthResponse:
    try:
        user = await reset_user_password(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return AuthResponse(access_token=create_access_token(str(user.id), "user"), user=user)


@router.post("/vendor/register", response_model=VendorAuthResponse, status_code=status.HTTP_201_CREATED)
async def vendor_register(
    payload: VendorRegisterRequest, session: AsyncSession = Depends(get_db_session)
) -> VendorAuthResponse:
    try:
        vendor = await register_vendor(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return VendorAuthResponse(access_token=create_access_token(str(vendor.id), "vendor"), user=vendor)


@router.post("/vendor/login", response_model=VendorAuthResponse)
async def vendor_login(
    payload: VendorLoginRequest, session: AsyncSession = Depends(get_db_session)
) -> VendorAuthResponse:
    try:
        vendor = await authenticate_vendor(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return VendorAuthResponse(access_token=create_access_token(str(vendor.id), "vendor"), user=vendor)


@router.post("/vendor/forgot-password", response_model=VendorForgotPasswordResponse)
async def vendor_forgot_password(
    payload: VendorForgotPasswordRequest, session: AsyncSession = Depends(get_db_session)
) -> VendorForgotPasswordResponse:
    try:
        token = await create_vendor_reset_token(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return VendorForgotPasswordResponse(
        message="Reset token generated. Connect this to email delivery in production.",
        reset_token=token,
    )


@router.post("/vendor/reset-password", response_model=VendorAuthResponse)
async def vendor_reset_password(
    payload: VendorResetPasswordRequest, session: AsyncSession = Depends(get_db_session)
) -> VendorAuthResponse:
    try:
        vendor = await reset_vendor_password(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return VendorAuthResponse(access_token=create_access_token(str(vendor.id), "vendor"), user=vendor)


@router.post("/vendor/onboarding", response_model=VendorAuthResponse)
async def vendor_onboarding(
    payload: VendorOnboardingRequest,
    session: AsyncSession = Depends(get_db_session),
    current_vendor: Vendor = Depends(get_current_vendor),
) -> VendorAuthResponse:
    vendor = await complete_vendor_onboarding(session, current_vendor, payload)
    return VendorAuthResponse(access_token=create_access_token(str(vendor.id), "vendor"), user=vendor)


# ============================================
# OAuth Endpoints
# ============================================


@router.post("/oauth/google", response_model=AuthResponse)
async def google_oauth(
    payload: GoogleOAuthRequest,
    session: AsyncSession = Depends(get_db_session),
) -> AuthResponse:
    """
    Google OAuth endpoint.
    
    Validates Google ID token and authenticates or registers user.
    
    Args:
        payload: GoogleOAuthRequest containing token
        session: Database session
        
    Returns:
        AuthResponse with JWT token and user data
        
    Raises:
        HTTPException 400: If token is invalid
        HTTPException 401: If token validation fails
    """
    try:
        # Get Google Client ID from environment
        google_client_id = os.getenv("GOOGLE_CLIENT_ID")
        if not google_client_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Google OAuth not configured",
            )
        
        # Validate Google token
        google_user = await validate_google_token(payload.token, google_client_id)
        
        # Get or create user
        user = await get_or_create_user_from_google(session, google_user)
        
        # Return JWT token and user data
        return AuthResponse(
            access_token=create_access_token(str(user.id), "user"),
            user=user,
        )
    
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google authentication failed",
        ) from exc


@router.post("/oauth/apple", response_model=AuthResponse)
async def apple_oauth(
    payload: AppleOAuthRequest,
    session: AsyncSession = Depends(get_db_session),
) -> AuthResponse:
    """
    Apple OAuth endpoint.
    
    Validates Apple ID token and authenticates or registers user.
    Handles Apple's private email relay feature.
    
    Args:
        payload: AppleOAuthRequest containing token and optional user data
        session: Database session
        
    Returns:
        AuthResponse with JWT token and user data
        
    Raises:
        HTTPException 400: If token is invalid
        HTTPException 401: If token validation fails
    """
    try:
        # Get Apple credentials from environment
        apple_team_id = os.getenv("APPLE_TEAM_ID")
        apple_client_id = os.getenv("APPLE_CLIENT_ID")
        
        if not apple_team_id or not apple_client_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Apple OAuth not configured",
            )
        
        # Validate Apple token
        apple_user = await validate_apple_token(
            payload.token,
            apple_team_id,
            apple_client_id,
        )
        
        # Handle Apple's user data (sent on first signup only)
        if payload.user:
            if "name" in payload.user:
                name_data = payload.user["name"]
                if isinstance(name_data, dict):
                    # Combine first and last name if available
                    first_name = name_data.get("firstName", "")
                    last_name = name_data.get("lastName", "")
                    full_name = f"{first_name} {last_name}".strip()
                    if full_name:
                        apple_user.name = full_name
        
        # Get or create user
        user = await get_or_create_user_from_apple(session, apple_user)
        
        # Return JWT token and user data
        return AuthResponse(
            access_token=create_access_token(str(user.id), "user"),
            user=user,
        )
    
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Apple authentication failed",
        ) from exc

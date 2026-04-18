from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.models.vendor import Vendor

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_db_session(session: AsyncSession = Depends(get_db)) -> AsyncSession:
    return session


async def get_current_user(
    session: AsyncSession = Depends(get_db_session), token: str = Depends(oauth2_scheme)
) -> User:
    try:
        payload = decode_access_token(token)
        if payload.get("type", "user") != "user":
            raise ValueError("Invalid authentication token")
        user_id = int(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token")

    user = await session.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def get_current_vendor(
    session: AsyncSession = Depends(get_db_session), token: str = Depends(oauth2_scheme)
) -> Vendor:
    try:
        payload = decode_access_token(token)
        if payload.get("type") != "vendor":
            raise ValueError("Invalid authentication token")
        vendor_id = int(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token")

    vendor = await session.get(Vendor, vendor_id)
    if not vendor or not vendor.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Vendor not found")
    return vendor

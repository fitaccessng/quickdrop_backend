from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin, get_current_rider, get_current_user, get_current_vendor, get_db_session
from app.models.notification import Notification
from app.models.user import User
from app.models.vendor import Vendor
from app.schemas.common import NotificationResponse

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/me", response_model=list[NotificationResponse])
async def get_my_notifications(
    session: AsyncSession = Depends(get_db_session),
    current_user: Optional[User] = Depends(get_current_user),
) -> list[NotificationResponse]:
    result = await session.execute(
        select(Notification)
        .where(Notification.recipient_role == "customer", Notification.recipient_user_id == current_user.id)
        .order_by(desc(Notification.created_at))
        .limit(50)
    )
    return list(result.scalars().all())


@router.get("/vendor/me", response_model=list[NotificationResponse])
async def get_vendor_notifications(
    session: AsyncSession = Depends(get_db_session),
    current_vendor: Vendor = Depends(get_current_vendor),
) -> list[NotificationResponse]:
    result = await session.execute(
        select(Notification)
        .where(Notification.recipient_role == "vendor", Notification.recipient_vendor_id == current_vendor.id)
        .order_by(desc(Notification.created_at))
        .limit(50)
    )
    return list(result.scalars().all())


@router.get("/rider/me", response_model=list[NotificationResponse])
async def get_rider_notifications(
    session: AsyncSession = Depends(get_db_session),
    current_rider: User = Depends(get_current_rider),
) -> list[NotificationResponse]:
    result = await session.execute(
        select(Notification)
        .where(Notification.recipient_role == "rider", Notification.recipient_user_id == current_rider.id)
        .order_by(desc(Notification.created_at))
        .limit(50)
    )
    return list(result.scalars().all())


@router.get("/admin/me", response_model=list[NotificationResponse])
async def get_admin_notifications(
    session: AsyncSession = Depends(get_db_session),
    current_admin: User = Depends(get_current_admin),
) -> list[NotificationResponse]:
    result = await session.execute(
        select(Notification)
        .where(
            Notification.recipient_role == "admin",
            (Notification.recipient_user_id == current_admin.id) | (Notification.recipient_user_id.is_(None)),
        )
        .order_by(desc(Notification.created_at))
        .limit(50)
    )
    return list(result.scalars().all())


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: Optional[User] = Depends(get_current_user),
) -> NotificationResponse:
    notification = await session.get(Notification, notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    if notification.recipient_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You cannot modify this notification")
    notification.is_read = True
    await session.commit()
    await session.refresh(notification)
    return notification

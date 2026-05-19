from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_admin,
    get_current_rider,
    get_current_user,
    get_current_vendor,
    get_db_session,
    get_optional_current_admin,
    get_optional_current_rider,
    get_optional_current_user,
    get_optional_current_vendor,
)
from app.models.notification import Notification
from app.models.user import User
from app.models.vendor import Vendor
from app.schemas.common import NotificationResponse, NotificationUnreadCountResponse

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _build_actor_filters(
    *,
    current_user: Optional[User] = None,
    current_vendor: Optional[Vendor] = None,
    current_rider: Optional[User] = None,
    current_admin: Optional[User] = None,
):
    if current_vendor:
        return [Notification.recipient_role == "vendor", Notification.recipient_vendor_id == current_vendor.id]
    if current_rider:
        return [Notification.recipient_role == "rider", Notification.recipient_user_id == current_rider.id]
    if current_admin:
        return [
            Notification.recipient_role == "admin",
            or_(Notification.recipient_user_id == current_admin.id, Notification.recipient_user_id.is_(None)),
        ]
    if current_user:
        return [Notification.recipient_role == "customer", Notification.recipient_user_id == current_user.id]
    raise HTTPException(status_code=401, detail="Authentication required")


async def _get_actor_notification(
    notification_id: int,
    session: AsyncSession,
    *,
    current_user: Optional[User] = None,
    current_vendor: Optional[Vendor] = None,
    current_rider: Optional[User] = None,
    current_admin: Optional[User] = None,
) -> Notification:
    filters = _build_actor_filters(
        current_user=current_user,
        current_vendor=current_vendor,
        current_rider=current_rider,
        current_admin=current_admin,
    )
    notification = await session.scalar(select(Notification).where(Notification.id == notification_id, *filters))
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    return notification


@router.get("/feed", response_model=list[NotificationResponse])
async def get_notification_feed(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    unread_only: bool = Query(default=False),
    category: Optional[str] = Query(default=None, max_length=40),
    session: AsyncSession = Depends(get_db_session),
    current_user: Optional[User] = Depends(get_optional_current_user),
    current_vendor: Optional[Vendor] = Depends(get_optional_current_vendor),
    current_rider: Optional[User] = Depends(get_optional_current_rider),
    current_admin: Optional[User] = Depends(get_optional_current_admin),
) -> list[NotificationResponse]:
    filters = _build_actor_filters(
        current_user=current_user,
        current_vendor=current_vendor,
        current_rider=current_rider,
        current_admin=current_admin,
    )
    if unread_only:
        filters.append(Notification.is_read.is_(False))
    if category:
        filters.append(Notification.category == category)
    result = await session.execute(
        select(Notification)
        .where(*filters)
        .order_by(desc(Notification.created_at))
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all())


@router.get("/unread-count", response_model=NotificationUnreadCountResponse)
async def get_notification_unread_count(
    session: AsyncSession = Depends(get_db_session),
    current_user: Optional[User] = Depends(get_optional_current_user),
    current_vendor: Optional[Vendor] = Depends(get_optional_current_vendor),
    current_rider: Optional[User] = Depends(get_optional_current_rider),
    current_admin: Optional[User] = Depends(get_optional_current_admin),
) -> NotificationUnreadCountResponse:
    filters = _build_actor_filters(
        current_user=current_user,
        current_vendor=current_vendor,
        current_rider=current_rider,
        current_admin=current_admin,
    )
    unread_count = await session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(*filters, Notification.is_read.is_(False))
    )
    return NotificationUnreadCountResponse(unread_count=unread_count or 0)


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
    current_user: Optional[User] = Depends(get_optional_current_user),
    current_vendor: Optional[Vendor] = Depends(get_optional_current_vendor),
    current_rider: Optional[User] = Depends(get_optional_current_rider),
    current_admin: Optional[User] = Depends(get_optional_current_admin),
) -> NotificationResponse:
    notification = await _get_actor_notification(
        notification_id,
        session,
        current_user=current_user,
        current_vendor=current_vendor,
        current_rider=current_rider,
        current_admin=current_admin,
    )
    notification.is_read = True
    await session.commit()
    await session.refresh(notification)
    return notification


@router.patch("/read-all", response_model=NotificationUnreadCountResponse)
async def mark_all_notifications_read(
    session: AsyncSession = Depends(get_db_session),
    current_user: Optional[User] = Depends(get_optional_current_user),
    current_vendor: Optional[Vendor] = Depends(get_optional_current_vendor),
    current_rider: Optional[User] = Depends(get_optional_current_rider),
    current_admin: Optional[User] = Depends(get_optional_current_admin),
) -> NotificationUnreadCountResponse:
    filters = _build_actor_filters(
        current_user=current_user,
        current_vendor=current_vendor,
        current_rider=current_rider,
        current_admin=current_admin,
    )
    result = await session.execute(
        select(Notification).where(*filters, Notification.is_read.is_(False))
    )
    for notification in result.scalars().all():
        notification.is_read = True
    await session.commit()
    return NotificationUnreadCountResponse(unread_count=0)


@router.delete("/clear", response_model=NotificationUnreadCountResponse)
async def clear_notifications(
    session: AsyncSession = Depends(get_db_session),
    current_user: Optional[User] = Depends(get_optional_current_user),
    current_vendor: Optional[Vendor] = Depends(get_optional_current_vendor),
    current_rider: Optional[User] = Depends(get_optional_current_rider),
    current_admin: Optional[User] = Depends(get_optional_current_admin),
) -> NotificationUnreadCountResponse:
    filters = _build_actor_filters(
        current_user=current_user,
        current_vendor=current_vendor,
        current_rider=current_rider,
        current_admin=current_admin,
    )
    result = await session.execute(select(Notification).where(*filters))
    for notification in result.scalars().all():
        await session.delete(notification)
    await session.commit()
    return NotificationUnreadCountResponse(unread_count=0)

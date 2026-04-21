from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification


async def create_notification(
    session: AsyncSession,
    *,
    recipient_role: str,
    title: str,
    message: str,
    category: str = "general",
    recipient_user_id: Optional[int] = None,
    recipient_vendor_id: Optional[int] = None,
    sound_enabled: bool = True,
) -> Notification:
    notification = Notification(
        recipient_role=recipient_role,
        recipient_user_id=recipient_user_id,
        recipient_vendor_id=recipient_vendor_id,
        title=title,
        message=message,
        category=category,
        sound_enabled=sound_enabled,
    )
    session.add(notification)
    await session.flush()
    return notification

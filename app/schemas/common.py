from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PayoutRequestCreate(BaseModel):
    amount: float = Field(gt=0)
    note: Optional[str] = Field(default=None, max_length=500)


class PayoutRequestStatusUpdate(BaseModel):
    status: str = Field(pattern="^(pending|approved|rejected|paid)$")


class PayoutRequestResponse(BaseModel):
    id: int
    requester_role: str
    requester_name: str
    requester_email: str
    amount: float
    bank_name: Optional[str] = None
    account_name: Optional[str] = None
    account_number: Optional[str] = None
    note: Optional[str] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationResponse(BaseModel):
    id: int
    title: str
    message: str
    category: str
    is_read: bool
    sound_enabled: bool
    recipient_role: str
    action_url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationUnreadCountResponse(BaseModel):
    unread_count: int

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr


class AddressCreate(BaseModel):
    label: str
    recipient_name: str
    phone: Optional[str] = None
    line1: str
    line2: Optional[str] = None
    city: str
    state: str
    postal_code: Optional[str] = None
    delivery_notes: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_default: bool = False


class AddressResponse(AddressCreate):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class UserProfile(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    phone: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    street: Optional[str] = None
    po_box: Optional[str] = None
    avatar_url: Optional[str] = None
    addresses: list[AddressResponse] = []

    class Config:
        from_attributes = True


class UserProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    street: Optional[str] = None
    po_box: Optional[str] = None
    avatar_url: Optional[str] = None

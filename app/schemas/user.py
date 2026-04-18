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
    addresses: list[AddressResponse] = []

    class Config:
        from_attributes = True

from typing import Optional

from pydantic import BaseModel


class ProductSummary(BaseModel):
    id: int
    vendor_id: int
    name: str
    description: str
    image_url: Optional[str] = None
    price: float
    category: str
    prep_time_minutes: int
    is_available: bool

    class Config:
        from_attributes = True

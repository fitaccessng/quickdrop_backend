from typing import Optional

from pydantic import BaseModel

from app.schemas.product import ProductSummary


class VendorReviewResponse(BaseModel):
    id: int
    author_name: str
    rating: int
    comment: str

    class Config:
        from_attributes = True


class VendorSummary(BaseModel):
    id: int
    name: str
    slug: str
    category: str
    description: str
    logo_url: Optional[str] = None
    cover_image_url: Optional[str] = None
    city: str
    prep_time_minutes: int
    delivery_fee: float
    minimum_order_amount: float
    rating: float
    review_count: int

    class Config:
        from_attributes = True


class VendorDetail(VendorSummary):
    products: list[ProductSummary]
    reviews: list[VendorReviewResponse]

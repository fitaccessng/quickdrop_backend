from typing import Optional

from pydantic import BaseModel, Field


class ProductSummary(BaseModel):
    id: int
    vendor_id: int
    name: str
    description: str
    image_url: Optional[str] = None
    image_urls: Optional[list[str]] = None
    sku: Optional[str] = None
    price: float
    category: str
    prep_time_minutes: int
    stock_quantity: int
    low_stock_threshold: int
    is_available: bool

    class Config:
        from_attributes = True


class ProductCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str = Field(min_length=10, max_length=2000)
    image_url: Optional[str] = Field(default=None, max_length=500)
    image_urls: list[str] = Field(default_factory=list, min_length=3, max_length=5)
    sku: Optional[str] = Field(default=None, max_length=64)
    price: float = Field(gt=0)
    category: str = Field(min_length=2, max_length=80)
    prep_time_minutes: int = Field(default=15, ge=1, le=240)
    stock_quantity: int = Field(default=0, ge=0, le=100000)
    low_stock_threshold: int = Field(default=5, ge=0, le=1000)
    is_available: bool = True


class ProductUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    description: Optional[str] = Field(default=None, min_length=10, max_length=2000)
    image_url: Optional[str] = Field(default=None, max_length=500)
    image_urls: Optional[list[str]] = Field(default=None, min_length=3, max_length=5)
    sku: Optional[str] = Field(default=None, max_length=64)
    price: Optional[float] = Field(default=None, gt=0)
    category: Optional[str] = Field(default=None, min_length=2, max_length=80)
    prep_time_minutes: Optional[int] = Field(default=None, ge=1, le=240)
    stock_quantity: Optional[int] = Field(default=None, ge=0, le=100000)
    low_stock_threshold: Optional[int] = Field(default=None, ge=0, le=1000)
    is_available: Optional[bool] = None

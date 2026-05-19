from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str] = mapped_column(Text)
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    image_urls: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    sku: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    price: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String(80), index=True)
    prep_time_minutes: Mapped[int] = mapped_column(default=15)
    stock_quantity: Mapped[int] = mapped_column(Integer, default=0)
    low_stock_threshold: Mapped[int] = mapped_column(Integer, default=5)
    rating: Mapped[float] = mapped_column(Float, default=0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    vendor = relationship("Vendor", back_populates="products")
    order_items = relationship("OrderItem", back_populates="product")
    reviews = relationship("ProductReview", back_populates="product", cascade="all, delete-orphan")
    promotions = relationship("VendorPromotion", back_populates="product")


class ProductReview(Base):
    __tablename__ = "product_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    author_name: Mapped[str] = mapped_column(String(120))
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    product = relationship("Product", back_populates="reviews")
    user = relationship("User")

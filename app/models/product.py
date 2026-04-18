from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str] = mapped_column(Text)
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    price: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String(80), index=True)
    prep_time_minutes: Mapped[int] = mapped_column(default=15)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    vendor = relationship("Vendor", back_populates="products")
    order_items = relationship("OrderItem", back_populates="product")

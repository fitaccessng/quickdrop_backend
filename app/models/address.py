from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Address(Base):
    __tablename__ = "addresses"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(80))
    recipient_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    line1: Mapped[str] = mapped_column(String(255))
    line2: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    city: Mapped[str] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(120))
    postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    delivery_notes: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="addresses")
    orders = relationship("Order", back_populates="address")

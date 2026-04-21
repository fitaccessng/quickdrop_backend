from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class PayoutRequest(Base):
    __tablename__ = "payout_requests"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    requester_role: Mapped[str] = mapped_column(String(20), index=True)
    requester_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    requester_vendor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vendors.id", ondelete="CASCADE"), nullable=True, index=True)
    requester_name: Mapped[str] = mapped_column(String(160))
    requester_email: Mapped[str] = mapped_column(String(255))
    amount: Mapped[float] = mapped_column(Float)
    bank_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    account_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    account_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

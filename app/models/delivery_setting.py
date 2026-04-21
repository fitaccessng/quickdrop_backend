from datetime import datetime

from sqlalchemy import DateTime, Float, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class DeliverySetting(Base):
    __tablename__ = "delivery_settings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    base_fee: Mapped[float] = mapped_column(Float, default=0)
    fee_per_km: Mapped[float] = mapped_column(Float, default=0)
    free_distance_km: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

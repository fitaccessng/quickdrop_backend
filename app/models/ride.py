from __future__ import annotations

from datetime import datetime
import enum
from typing import Any, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class RideStatus(str, enum.Enum):
    searching = "searching"
    accepted = "accepted"
    arriving = "arriving"
    on_trip = "on_trip"
    completed = "completed"
    cancelled = "cancelled"


class Ride(Base):
    __tablename__ = "rides"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    rider_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    vehicle_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default=RideStatus.searching.value, nullable=False, index=True)
    pickup_location: Mapped[str] = mapped_column(String(255), nullable=False)
    dropoff_location: Mapped[str] = mapped_column(String(255), nullable=False)
    pickup_latitude: Mapped[float] = mapped_column(Float, nullable=False)
    pickup_longitude: Mapped[float] = mapped_column(Float, nullable=False)
    dropoff_latitude: Mapped[float] = mapped_column(Float, nullable=False)
    dropoff_longitude: Mapped[float] = mapped_column(Float, nullable=False)
    distance_meters: Mapped[float] = mapped_column(Float, default=0)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    estimated_arrival_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    final_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rider_payout_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rider_payout_percentage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="ZAR")
    route_geometry: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    pickup_heading: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rider_latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rider_longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rider_heading: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rider_speed: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tracking_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    customer_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    receiver_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    receiver_phone: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    rider = relationship("User", foreign_keys=[rider_id])
    user = relationship("User", foreign_keys=[user_id])
    location_events = relationship(
        "RideLocationEvent",
        back_populates="ride",
        cascade="all, delete-orphan",
        order_by="RideLocationEvent.recorded_at.asc()",
    )


class RideLocationEvent(Base):
    __tablename__ = "ride_location_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ride_id: Mapped[str] = mapped_column(String(32), ForeignKey("rides.id", ondelete="CASCADE"), index=True)
    rider_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    heading: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    speed: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    ride = relationship("Ride", back_populates="location_events")

from datetime import datetime
from typing import List, Optional
from sqlalchemy import Column, String, Integer, Float, DateTime, Enum
from sqlalchemy.orm import relationship
import enum

from app.db.base import Base


class RideStatus(str, enum.Enum):
    """Ride status enumeration for Python 3.9 compatibility"""
    searching = "searching"
    accepted = "accepted"
    en_route = "en_route"
    arrived = "arrived"
    completed = "completed"
    cancelled = "cancelled"


class Ride(Base):
    """Ride request model"""
    __tablename__ = "rides"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    vehicle_type = Column(String, nullable=False)  # 'bike', 'car', 'xl'
    status = Column(String, default=RideStatus.searching.value, nullable=False)
    price = Column(Float, nullable=False)
    pickup_location = Column(String, nullable=False)
    dropoff_location = Column(String, nullable=False)
    driver_id = Column(Integer, nullable=True)
    driver_name = Column(String, nullable=True)
    driver_phone = Column(String, nullable=True)
    driver_rating = Column(Float, nullable=True)
    vehicle_number = Column(String, nullable=True)
    estimated_arrival = Column(Integer, nullable=True)  # in minutes
    tracking_note = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    class Config:
        from_attributes = True

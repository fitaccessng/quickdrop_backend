from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class RideRequestSchema(BaseModel):
    """Schema for requesting a new ride"""
    vehicle_type: str  # 'bike', 'car', 'xl'
    price: float
    pickup_location: str
    dropoff_location: str


class RideStatusResponse(BaseModel):
    """Schema for ride status response"""
    ride_id: str
    status: str
    vehicle_type: str
    price: float
    pickup_location: str
    dropoff_location: str
    driver_id: Optional[int] = None
    driver_name: Optional[str] = None
    driver_phone: Optional[str] = None
    driver_rating: Optional[float] = None
    vehicle_number: Optional[str] = None
    estimated_arrival: Optional[int] = None
    tracking_note: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RideResponse(BaseModel):
    """Schema for ride response"""
    ride_id: str
    status: str
    vehicle_type: str
    price: float
    estimated_arrival: int
    driver_name: Optional[str] = None
    driver_rating: Optional[float] = None

    class Config:
        from_attributes = True

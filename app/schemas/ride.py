from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


RideVehicleType = Literal["bike", "car", "xl"]
RideLifecycleStatus = Literal["searching", "accepted", "arriving", "on_trip", "completed", "cancelled"]


class RidePoint(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    address: str = Field(min_length=3, max_length=255)


class RideQuoteRequest(BaseModel):
    vehicle_type: RideVehicleType
    pickup: RidePoint
    dropoff: RidePoint


class RideRequestSchema(RideQuoteRequest):
    route_geometry: Optional[list[list[float]]] = None
    receiver_name: Optional[str] = Field(default=None, max_length=120)
    receiver_phone: Optional[str] = Field(default=None, max_length=40)
    customer_note: Optional[str] = Field(default=None, max_length=500)


class RideParticipant(BaseModel):
    id: int
    full_name: str
    phone: Optional[str] = None
    vehicle_type: Optional[str] = None
    plate_number: Optional[str] = None
    avatar_url: Optional[str] = None
    rating: Optional[float] = None


class AdminRiderSnapshot(RideParticipant):
    rider_status: Optional[str] = None
    current_latitude: Optional[float] = None
    current_longitude: Optional[float] = None


class RideLocationSnapshot(BaseModel):
    latitude: float
    longitude: float
    heading: Optional[float] = None
    speed: Optional[float] = None
    recorded_at: Optional[datetime] = None


class RideQuoteResponse(BaseModel):
    vehicle_type: RideVehicleType
    currency: str
    distance_meters: float
    duration_seconds: int
    estimated_fare: float
    eta_seconds: int


class RideResponse(BaseModel):
    ride_id: str
    status: RideLifecycleStatus
    vehicle_type: RideVehicleType
    currency: str
    price: float
    estimated_arrival_seconds: Optional[int] = None
    rider: Optional[RideParticipant] = None


class RideStatusResponse(BaseModel):
    ride_id: str
    status: RideLifecycleStatus
    vehicle_type: RideVehicleType
    currency: str
    price: float
    final_price: Optional[float] = None
    rider_payout_amount: Optional[float] = None
    rider_payout_percentage: Optional[float] = None
    pickup: RidePoint
    dropoff: RidePoint
    distance_meters: float
    duration_seconds: int
    estimated_arrival_seconds: Optional[int] = None
    tracking_note: Optional[str] = None
    route_geometry: list[list[float]] = []
    customer: Optional[RideParticipant] = None
    rider: Optional[RideParticipant] = None
    rider_location: Optional[RideLocationSnapshot] = None
    recent_locations: list[RideLocationSnapshot] = []
    created_at: datetime
    updated_at: datetime


class RiderRideActionRequest(BaseModel):
    action: Literal["accept", "reject"]


class RideStatusUpdateRequest(BaseModel):
    status: Literal["accepted", "arriving", "on_trip", "completed", "cancelled"]
    tracking_note: Optional[str] = Field(default=None, max_length=500)


class RiderLocationUpdateRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    heading: Optional[float] = None
    speed: Optional[float] = None


class AdminRideAssignRequest(BaseModel):
    rider_id: int


class RideAdminSnapshot(BaseModel):
    ride_id: str
    status: RideLifecycleStatus
    vehicle_type: RideVehicleType
    currency: str
    price: float
    pickup: RidePoint
    dropoff: RidePoint
    estimated_arrival_seconds: Optional[int] = None
    customer_note: Optional[str] = None
    receiver_name: Optional[str] = None
    receiver_phone: Optional[str] = None
    customer: Optional[RideParticipant] = None
    rider: Optional[RideParticipant] = None
    rider_location: Optional[RideLocationSnapshot] = None
    created_at: datetime
    updated_at: datetime


class AdminRideLiveResponse(BaseModel):
    active_rides: list[RideAdminSnapshot]
    active_riders: list[AdminRiderSnapshot]


class RideSocketEnvelope(BaseModel):
    event: str
    ride: Optional[RideStatusResponse] = None
    rides: Optional[list[RideAdminSnapshot]] = None

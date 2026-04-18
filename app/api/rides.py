from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.schemas.ride import RideRequestSchema, RideResponse, RideStatusResponse
from app.services.rides import (
    create_ride_request,
    get_ride_by_id,
    get_all_rides_for_user,
)

router = APIRouter(prefix="/rides", tags=["rides"])


@router.post("/request", response_model=RideResponse)
async def request_ride(
    payload: RideRequestSchema,
    current_user: User = Depends(get_current_user),
    db_session: AsyncSession = Depends(get_db),
):
    """
    Request a new ride
    
    Args:
        payload: Ride request details (vehicle_type, price, pickup_location, dropoff_location)
        current_user: Current authenticated user
        db_session: Database session
        
    Returns:
        RideResponse with ride_id, status, estimated_arrival, etc.
    """
    ride = await create_ride_request(current_user.id, payload, db_session)
    
    return RideResponse(
        ride_id=ride.id,
        status=ride.status,
        vehicle_type=ride.vehicle_type,
        price=ride.price,
        estimated_arrival=ride.estimated_arrival,
        driver_name=ride.driver_name,
        driver_rating=ride.driver_rating,
    )


@router.get("/{ride_id}", response_model=RideStatusResponse)
async def get_ride_status(
    ride_id: str,
    current_user: User = Depends(get_current_user),
    db_session: AsyncSession = Depends(get_db),
):
    """
    Get ride status and tracking information
    
    Args:
        ride_id: ID of the ride to track
        current_user: Current authenticated user
        db_session: Database session
        
    Returns:
        RideStatusResponse with detailed ride information
    """
    ride = await get_ride_by_id(ride_id, current_user.id, db_session)
    
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    
    return RideStatusResponse(
        ride_id=ride.id,
        status=ride.status,
        vehicle_type=ride.vehicle_type,
        price=ride.price,
        pickup_location=ride.pickup_location,
        dropoff_location=ride.dropoff_location,
        driver_id=ride.driver_id,
        driver_name=ride.driver_name,
        driver_phone=ride.driver_phone,
        driver_rating=ride.driver_rating,
        vehicle_number=ride.vehicle_number,
        estimated_arrival=ride.estimated_arrival,
        tracking_note=ride.tracking_note,
        created_at=ride.created_at,
        updated_at=ride.updated_at,
    )


@router.get("/user/history")
async def get_user_rides(
    current_user: User = Depends(get_current_user),
    db_session: AsyncSession = Depends(get_db),
):
    """
    Get all rides for the current user
    
    Args:
        current_user: Current authenticated user
        db_session: Database session
        
    Returns:
        List of user's rides
    """
    rides = await get_all_rides_for_user(current_user.id, db_session)
    
    return [
        RideStatusResponse(
            ride_id=ride.id,
            status=ride.status,
            vehicle_type=ride.vehicle_type,
            price=ride.price,
            pickup_location=ride.pickup_location,
            dropoff_location=ride.dropoff_location,
            driver_id=ride.driver_id,
            driver_name=ride.driver_name,
            driver_phone=ride.driver_phone,
            driver_rating=ride.driver_rating,
            vehicle_number=ride.vehicle_number,
            estimated_arrival=ride.estimated_arrival,
            tracking_note=ride.tracking_note,
            created_at=ride.created_at,
            updated_at=ride.updated_at,
        )
        for ride in rides
    ]

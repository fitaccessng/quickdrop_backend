import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.ride import Ride, RideStatus
from app.schemas.ride import RideRequestSchema


async def create_ride_request(
    user_id: int,
    payload: RideRequestSchema,
    db_session: AsyncSession
) -> Ride:
    """
    Create a new ride request
    
    Args:
        user_id: ID of the user requesting the ride
        payload: Request payload with vehicle_type, price, pickup_location, dropoff_location
        db_session: Database session
        
    Returns:
        Ride object with created ride details
    """
    ride_id = f"ride_{uuid.uuid4().hex[:12]}"
    
    # Determine estimated arrival time based on vehicle type
    estimated_arrival_map = {
        'bike': 3,
        'car': 6,
        'xl': 8,
    }
    estimated_arrival = estimated_arrival_map.get(payload.vehicle_type, 5)
    
    # Create new ride
    ride = Ride(
        id=ride_id,
        user_id=user_id,
        vehicle_type=payload.vehicle_type,
        price=payload.price,
        pickup_location=payload.pickup_location,
        dropoff_location=payload.dropoff_location,
        status=RideStatus.searching.value,
        estimated_arrival=estimated_arrival,
        tracking_note=payload.delivery_note or f"Receiver: {payload.receiver_name or 'Customer'}. Looking for nearby riders...",
    )
    
    db_session.add(ride)
    await db_session.commit()
    await db_session.refresh(ride)
    
    return ride


async def get_ride_by_id(ride_id: str, user_id: int, db_session: AsyncSession) -> Ride:
    """
    Get a ride by ID for a specific user
    
    Args:
        ride_id: ID of the ride
        user_id: ID of the user requesting the ride (for authorization)
        db_session: Database session
        
    Returns:
        Ride object or None if not found
    """
    query = select(Ride).where(
        (Ride.id == ride_id) & (Ride.user_id == user_id)
    )
    result = await db_session.execute(query)
    return result.scalar_one_or_none()


async def get_all_rides_for_user(user_id: int, db_session: AsyncSession) -> list:
    """
    Get all rides for a user
    
    Args:
        user_id: ID of the user
        db_session: Database session
        
    Returns:
        List of Ride objects
    """
    query = select(Ride).where(Ride.user_id == user_id).order_by(Ride.created_at.desc())
    result = await db_session.execute(query)
    return result.scalars().all()


async def update_ride_status(
    ride_id: str,
    status: str,
    tracking_note: str = None,
    db_session: AsyncSession = None
) -> Ride:
    """
    Update ride status (for simulation purposes)
    
    Args:
        ride_id: ID of the ride
        status: New status
        tracking_note: Optional tracking note/message
        db_session: Database session
        
    Returns:
        Updated Ride object
    """
    query = select(Ride).where(Ride.id == ride_id)
    result = await db_session.execute(query)
    ride = result.scalar_one_or_none()
    
    if ride:
        ride.status = status
        if tracking_note:
            ride.tracking_note = tracking_note
        
        # Simulate driver assignment
        if status == RideStatus.accepted.value:
            ride.driver_name = "Ahmed Hassan"
            ride.driver_rating = 4.8
            ride.vehicle_number = "KCA 123 AB"
            ride.driver_phone = "+254712345678"
        
        await db_session.commit()
        await db_session.refresh(ride)
    
    return ride

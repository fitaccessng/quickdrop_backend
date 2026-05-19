from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.delivery_setting import DeliverySetting
from app.models.ride import Ride, RideLocationEvent, RideStatus
from app.models.user import User
from app.schemas.ride import (
    AdminRiderSnapshot,
    AdminRideLiveResponse,
    RideAdminSnapshot,
    RideLocationSnapshot,
    RideParticipant,
    RidePoint,
    RideQuoteRequest,
    RideQuoteResponse,
    RideRequestSchema,
    RideStatusResponse,
)

RIDE_OPTIONS = (
    selectinload(Ride.user),
    selectinload(Ride.rider),
    selectinload(Ride.location_events),
)

VEHICLE_ETA_MULTIPLIERS = {"bike": 0.85, "car": 1.0, "xl": 1.1}

ACTIVE_RIDE_STATUSES = {
    RideStatus.searching.value,
    RideStatus.accepted.value,
    RideStatus.arriving.value,
    RideStatus.on_trip.value,
}


def haversine_distance_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def estimate_duration_seconds(distance_meters: float, vehicle_type: str) -> int:
    average_speed_kph = {"bike": 28, "car": 35, "xl": 32}.get(vehicle_type, 30)
    seconds = (distance_meters / 1000) / average_speed_kph * 3600
    return max(240, int(seconds))


async def get_delivery_settings(session: AsyncSession) -> DeliverySetting:
    settings = await session.scalar(select(DeliverySetting).order_by(DeliverySetting.id.asc()))
    if settings:
        return settings

    settings = DeliverySetting(
        base_fee=0,
        fee_per_km=0,
        free_distance_km=0,
        bike_surcharge=0,
        car_surcharge=0,
        xl_surcharge=0,
        rider_payout_percentage=30,
    )
    session.add(settings)
    await session.commit()
    await session.refresh(settings)
    return settings


def get_vehicle_surcharge(settings: DeliverySetting, vehicle_type: str) -> float:
    return {
        "bike": float(settings.bike_surcharge or 0),
        "car": float(settings.car_surcharge or 0),
        "xl": float(settings.xl_surcharge or 0),
    }.get(vehicle_type, 0.0)


def build_route_preview(
    pickup: RidePoint,
    dropoff: RidePoint,
    geometry: Optional[list[list[float]]] = None,
) -> list[list[float]]:
    if geometry:
        return geometry
    return [
        [pickup.longitude, pickup.latitude],
        [dropoff.longitude, dropoff.latitude],
    ]


def build_quote(payload: RideQuoteRequest, settings: DeliverySetting) -> RideQuoteResponse:
    distance = haversine_distance_meters(
        payload.pickup.latitude,
        payload.pickup.longitude,
        payload.dropoff.latitude,
        payload.dropoff.longitude,
    )
    duration = estimate_duration_seconds(distance, payload.vehicle_type)
    distance_km = distance / 1000
    billable_distance = max(distance_km - float(settings.free_distance_km or 0), 0)
    surcharge = get_vehicle_surcharge(settings, payload.vehicle_type)
    fare = float(settings.base_fee or 0) + (billable_distance * float(settings.fee_per_km or 0)) + surcharge
    eta = max(180, int(duration * VEHICLE_ETA_MULTIPLIERS.get(payload.vehicle_type, 1.0)))

    return RideQuoteResponse(
        vehicle_type=payload.vehicle_type,
        currency="ZAR",
        distance_meters=round(distance, 2),
        duration_seconds=duration,
        estimated_fare=round(fare, 2),
        eta_seconds=eta,
    )


def quote_ride(payload: RideQuoteRequest) -> RideQuoteResponse:
    settings = DeliverySetting(
        base_fee=0,
        fee_per_km=0,
        free_distance_km=0,
        bike_surcharge=180,
        car_surcharge=260,
        xl_surcharge=360,
        rider_payout_percentage=30,
    )
    return build_quote(payload, settings)


def serialize_participant(user: Optional[User], *, rating: Optional[float] = None) -> Optional[RideParticipant]:
    if not user:
        return None
    return RideParticipant(
        id=user.id,
        full_name=user.full_name,
        phone=user.phone,
        vehicle_type=user.vehicle_type,
        plate_number=user.license_number,
        avatar_url=user.avatar_url,
        rating=rating,
    )


def serialize_admin_rider(user: User) -> AdminRiderSnapshot:
    return AdminRiderSnapshot(
        id=user.id,
        full_name=user.full_name,
        phone=user.phone,
        vehicle_type=user.vehicle_type,
        plate_number=user.license_number,
        avatar_url=user.avatar_url,
        rating=4.9,
        rider_status=user.rider_status,
        current_latitude=user.current_latitude,
        current_longitude=user.current_longitude,
    )


def serialize_location(event: Optional[RideLocationEvent]) -> Optional[RideLocationSnapshot]:
    if not event:
        return None
    return RideLocationSnapshot(
        latitude=event.latitude,
        longitude=event.longitude,
        heading=event.heading,
        speed=event.speed,
        recorded_at=event.recorded_at,
    )


def serialize_ride(ride: Ride) -> RideStatusResponse:
    recent_events = ride.location_events[-12:] if ride.location_events else []
    latest_event = recent_events[-1] if recent_events else None
    rider_location = latest_event
    if ride.rider_latitude is not None and ride.rider_longitude is not None:
        rider_location = RideLocationEvent(
            ride_id=ride.id,
            rider_id=ride.rider_id or 0,
            latitude=ride.rider_latitude,
            longitude=ride.rider_longitude,
            heading=ride.rider_heading,
            speed=ride.rider_speed,
        )
    return RideStatusResponse(
        ride_id=ride.id,
        status=ride.status,
        vehicle_type=ride.vehicle_type,
        currency=ride.currency,
        price=ride.price,
        final_price=ride.final_price,
        rider_payout_amount=ride.rider_payout_amount,
        rider_payout_percentage=ride.rider_payout_percentage,
        pickup=RidePoint(
            latitude=ride.pickup_latitude,
            longitude=ride.pickup_longitude,
            address=ride.pickup_location,
        ),
        dropoff=RidePoint(
            latitude=ride.dropoff_latitude,
            longitude=ride.dropoff_longitude,
            address=ride.dropoff_location,
        ),
        distance_meters=ride.distance_meters,
        duration_seconds=ride.duration_seconds,
        estimated_arrival_seconds=ride.estimated_arrival_seconds,
        tracking_note=ride.tracking_note,
        route_geometry=ride.route_geometry or build_route_preview(
            RidePoint(latitude=ride.pickup_latitude, longitude=ride.pickup_longitude, address=ride.pickup_location),
            RidePoint(latitude=ride.dropoff_latitude, longitude=ride.dropoff_longitude, address=ride.dropoff_location),
        ),
        customer=serialize_participant(ride.user),
        rider=serialize_participant(ride.rider, rating=4.9 if ride.rider else None),
        rider_location=serialize_location(rider_location),
        recent_locations=[serialize_location(item) for item in recent_events if item],
        created_at=ride.created_at,
        updated_at=ride.updated_at,
    )


def serialize_admin_snapshot(ride: Ride) -> RideAdminSnapshot:
    serialized = serialize_ride(ride)
    return RideAdminSnapshot(
        ride_id=serialized.ride_id,
        status=serialized.status,
        vehicle_type=serialized.vehicle_type,
        currency=serialized.currency,
        price=serialized.price,
        pickup=serialized.pickup,
        dropoff=serialized.dropoff,
        estimated_arrival_seconds=serialized.estimated_arrival_seconds,
        customer_note=ride.customer_note,
        receiver_name=ride.receiver_name,
        receiver_phone=ride.receiver_phone,
        customer=serialized.customer,
        rider=serialized.rider,
        rider_location=serialized.rider_location,
        created_at=serialized.created_at,
        updated_at=serialized.updated_at,
    )


async def find_nearest_available_rider(session: AsyncSession, ride_request: RideRequestSchema) -> Optional[User]:
    result = await session.execute(
        select(User).where(
            User.role == "rider",
            User.is_active.is_(True),
            User.is_onboarded.is_(True),
            User.rider_status.in_(["available", "online"]),
            User.current_latitude.is_not(None),
            User.current_longitude.is_not(None),
        )
    )
    riders = list(result.scalars().all())
    if not riders:
        return None

    return min(
        riders,
        key=lambda rider: haversine_distance_meters(
            ride_request.pickup.latitude,
            ride_request.pickup.longitude,
            rider.current_latitude or 0,
            rider.current_longitude or 0,
        ),
    )


async def create_ride_request(user_id: int, payload: RideRequestSchema, db_session: AsyncSession) -> Ride:
    settings = await get_delivery_settings(db_session)
    quote = build_quote(payload, settings)
    nearest_rider = await find_nearest_available_rider(db_session, payload)
    rider_payout_percentage = float(settings.rider_payout_percentage or 0)
    rider_payout_amount = round((quote.estimated_fare * rider_payout_percentage) / 100, 2)
    ride = Ride(
        id=f"ride_{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        rider_id=nearest_rider.id if nearest_rider else None,
        vehicle_type=payload.vehicle_type,
        price=quote.estimated_fare,
        currency=quote.currency,
        pickup_location=payload.pickup.address,
        dropoff_location=payload.dropoff.address,
        pickup_latitude=payload.pickup.latitude,
        pickup_longitude=payload.pickup.longitude,
        dropoff_latitude=payload.dropoff.latitude,
        dropoff_longitude=payload.dropoff.longitude,
        distance_meters=quote.distance_meters,
        duration_seconds=quote.duration_seconds,
        estimated_arrival_seconds=quote.eta_seconds,
        rider_payout_amount=rider_payout_amount,
        rider_payout_percentage=rider_payout_percentage,
        route_geometry=build_route_preview(payload.pickup, payload.dropoff, payload.route_geometry),
        status=RideStatus.searching.value,
        tracking_note="Searching for the nearest available rider.",
        customer_note=payload.customer_note,
        receiver_name=payload.receiver_name,
        receiver_phone=payload.receiver_phone,
        rider_latitude=nearest_rider.current_latitude if nearest_rider else None,
        rider_longitude=nearest_rider.current_longitude if nearest_rider else None,
    )
    db_session.add(ride)
    await db_session.commit()
    return await get_ride_for_actor(db_session, ride.id)


async def get_ride_for_actor(db_session: AsyncSession, ride_id: str) -> Ride:
    result = await db_session.execute(select(Ride).where(Ride.id == ride_id).options(*RIDE_OPTIONS))
    ride = result.scalar_one_or_none()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    return ride


async def get_ride_by_customer(ride_id: str, user_id: int, db_session: AsyncSession) -> Ride:
    result = await db_session.execute(
        select(Ride).where(and_(Ride.id == ride_id, Ride.user_id == user_id)).options(*RIDE_OPTIONS)
    )
    ride = result.scalar_one_or_none()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    return ride


async def get_current_active_ride_for_user(user_id: int, db_session: AsyncSession) -> Optional[Ride]:
    result = await db_session.execute(
        select(Ride)
        .where(and_(Ride.user_id == user_id, Ride.status.in_(ACTIVE_RIDE_STATUSES)))
        .order_by(Ride.created_at.desc())
        .options(*RIDE_OPTIONS)
    )
    return result.scalars().first()


async def get_rider_dispatch_queue(rider_id: int, db_session: AsyncSession) -> list[Ride]:
    result = await db_session.execute(
        select(Ride)
        .where(
            or_(
                and_(Ride.rider_id == rider_id, Ride.status.in_(ACTIVE_RIDE_STATUSES)),
                and_(Ride.rider_id.is_(None), Ride.status == RideStatus.searching.value),
            )
        )
        .order_by(Ride.created_at.desc())
        .options(*RIDE_OPTIONS)
    )
    return list(result.scalars().all())


async def assign_ride_to_rider(ride: Ride, rider: User, db_session: AsyncSession) -> Ride:
    ride.rider_id = rider.id
    ride.rider_latitude = rider.current_latitude
    ride.rider_longitude = rider.current_longitude
    ride.tracking_note = f"{rider.full_name} has been assigned. Waiting for rider response."
    await db_session.commit()
    return await get_ride_for_actor(db_session, ride.id)


async def handle_rider_response(ride_id: str, rider: User, action: str, db_session: AsyncSession) -> Ride:
    ride = await get_ride_for_actor(db_session, ride_id)
    if ride.rider_id not in {None, rider.id}:
        raise HTTPException(status_code=409, detail="Ride already offered to another rider")

    if action == "reject":
        ride.rider_id = None
        ride.rider_latitude = None
        ride.rider_longitude = None
        ride.tracking_note = "First rider declined. Continuing search."
        replacement = await find_nearest_available_rider(
            db_session,
            RideRequestSchema(
                vehicle_type=ride.vehicle_type,
                pickup=RidePoint(latitude=ride.pickup_latitude, longitude=ride.pickup_longitude, address=ride.pickup_location),
                dropoff=RidePoint(latitude=ride.dropoff_latitude, longitude=ride.dropoff_longitude, address=ride.dropoff_location),
            ),
        )
        if replacement and replacement.id != rider.id:
            ride.rider_id = replacement.id
            ride.rider_latitude = replacement.current_latitude
            ride.rider_longitude = replacement.current_longitude
        await db_session.commit()
        return await get_ride_for_actor(db_session, ride.id)

    ride.rider_id = rider.id
    ride.status = RideStatus.accepted.value
    ride.accepted_at = datetime.now(timezone.utc)
    ride.tracking_note = f"{rider.full_name} accepted the ride and is heading to pickup."
    rider.rider_status = "delivering"
    await db_session.commit()
    return await get_ride_for_actor(db_session, ride.id)


async def update_ride_status(
    ride_id: str,
    rider: User,
    status: str,
    tracking_note: Optional[str],
    db_session: AsyncSession,
) -> Ride:
    ride = await get_ride_for_actor(db_session, ride_id)
    if ride.rider_id != rider.id:
        raise HTTPException(status_code=403, detail="Ride is not assigned to this rider")

    ride.status = status
    ride.tracking_note = tracking_note or {
        RideStatus.arriving.value: "Rider is arriving at the pickup point.",
        RideStatus.on_trip.value: "Trip is in progress.",
        RideStatus.completed.value: "Trip completed successfully.",
        RideStatus.cancelled.value: "Trip was cancelled.",
        RideStatus.accepted.value: "Rider accepted the request.",
    }.get(status, ride.tracking_note)

    now = datetime.now(timezone.utc)
    if status == RideStatus.on_trip.value and not ride.started_at:
        ride.started_at = now
    if status == RideStatus.completed.value:
        ride.completed_at = now
        ride.final_price = ride.price
        rider.rider_status = "available"
    elif status == RideStatus.cancelled.value:
        rider.rider_status = "available"
    else:
        rider.rider_status = "delivering"

    await db_session.commit()
    return await get_ride_for_actor(db_session, ride.id)


async def record_rider_location(
    ride_id: str,
    rider: User,
    latitude: float,
    longitude: float,
    heading: Optional[float],
    speed: Optional[float],
    db_session: AsyncSession,
) -> Ride:
    ride = await get_ride_for_actor(db_session, ride_id)
    if ride.rider_id != rider.id:
        raise HTTPException(status_code=403, detail="Ride is not assigned to this rider")

    ride.rider_latitude = latitude
    ride.rider_longitude = longitude
    ride.rider_heading = heading
    ride.rider_speed = speed
    rider.current_latitude = latitude
    rider.current_longitude = longitude

    event = RideLocationEvent(
        ride_id=ride.id,
        rider_id=rider.id,
        latitude=latitude,
        longitude=longitude,
        heading=heading,
        speed=speed,
    )
    db_session.add(event)
    await db_session.commit()
    return await get_ride_for_actor(db_session, ride.id)


async def get_all_rides_for_user(user_id: int, db_session: AsyncSession) -> list[Ride]:
    result = await db_session.execute(
        select(Ride).where(Ride.user_id == user_id).order_by(Ride.created_at.desc()).options(*RIDE_OPTIONS)
    )
    return list(result.scalars().all())


async def get_all_rides_for_rider(rider_id: int, db_session: AsyncSession) -> list[Ride]:
    result = await db_session.execute(
        select(Ride).where(Ride.rider_id == rider_id).order_by(Ride.updated_at.desc()).options(*RIDE_OPTIONS)
    )
    return list(result.scalars().all())


async def get_admin_live_overview(db_session: AsyncSession) -> AdminRideLiveResponse:
    rides_result = await db_session.execute(
        select(Ride)
        .where(Ride.status.in_(ACTIVE_RIDE_STATUSES | {RideStatus.searching.value}))
        .order_by(Ride.updated_at.desc())
        .options(*RIDE_OPTIONS)
    )
    rider_result = await db_session.execute(
        select(User).where(
            User.role == "rider",
            User.is_active.is_(True),
            User.is_onboarded.is_(True),
            User.rider_status.in_(["available", "online"]),
            User.current_latitude.is_not(None),
            User.current_longitude.is_not(None),
        )
    )
    rides = list(rides_result.scalars().all())
    riders = list(rider_result.scalars().all())
    return AdminRideLiveResponse(
        active_rides=[serialize_admin_snapshot(ride) for ride in rides],
        active_riders=[serialize_admin_rider(rider) for rider in riders if rider],
    )

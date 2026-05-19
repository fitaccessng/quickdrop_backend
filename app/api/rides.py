from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin, get_current_rider, get_current_user, get_db_session
from app.core.security import decode_access_token
from app.models.user import User
from app.schemas.ride import (
    AdminRideAssignRequest,
    AdminRideLiveResponse,
    RideQuoteRequest,
    RideQuoteResponse,
    RideRequestSchema,
    RiderLocationUpdateRequest,
    RiderRideActionRequest,
    RideResponse,
    RideSocketEnvelope,
    RideStatusResponse,
    RideStatusUpdateRequest,
)
from app.services.ride_realtime import ride_realtime_manager
from app.services.notifications import create_notification
from app.services.rides import (
    assign_ride_to_rider,
    build_quote,
    create_ride_request,
    get_all_rides_for_rider,
    get_delivery_settings,
    get_admin_live_overview,
    get_all_rides_for_user,
    get_current_active_ride_for_user,
    get_ride_by_customer,
    get_ride_for_actor,
    get_rider_dispatch_queue,
    handle_rider_response,
    quote_ride,
    record_rider_location,
    serialize_admin_snapshot,
    serialize_ride,
    update_ride_status,
)

router = APIRouter(prefix="/rides", tags=["rides"])


async def _broadcast_ride_state(ride_id: str, session: AsyncSession, event: str = "ride.updated") -> RideStatusResponse:
    ride = await get_ride_for_actor(session, ride_id)
    serialized = serialize_ride(ride)
    admin_snapshot = serialize_admin_snapshot(ride)
    await ride_realtime_manager.broadcast_ride(
        ride_id,
        RideSocketEnvelope(event=event, ride=serialized).model_dump(mode="json"),
    )
    await ride_realtime_manager.broadcast_admin(
        RideSocketEnvelope(event=event, rides=[admin_snapshot]).model_dump(mode="json")
    )
    return serialized


async def _send_socket_payload(websocket: WebSocket, payload: RideSocketEnvelope) -> bool:
    try:
        await websocket.send_text(json.dumps(payload.model_dump(mode="json"), default=str))
        return True
    except (WebSocketDisconnect, RuntimeError):
        return False


@router.post("/quote", response_model=RideQuoteResponse)
async def quote_customer_ride(
    payload: RideQuoteRequest,
    db_session: AsyncSession = Depends(get_db_session),
) -> RideQuoteResponse:
    settings = await get_delivery_settings(db_session)
    return build_quote(payload, settings)


@router.post("", response_model=RideResponse)
async def request_ride(
    payload: RideRequestSchema,
    current_user: User = Depends(get_current_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> RideResponse:
    ride = await create_ride_request(
        current_user.id,
        payload,
        db_session,
    )
    serialized = serialize_ride(ride)
    await ride_realtime_manager.broadcast_admin(
        RideSocketEnvelope(event="ride.created", rides=[serialize_admin_snapshot(ride)]).model_dump(mode="json")
    )
    return RideResponse(
        ride_id=serialized.ride_id,
        status=serialized.status,
        vehicle_type=serialized.vehicle_type,
        currency=serialized.currency,
        price=serialized.price,
        estimated_arrival_seconds=serialized.estimated_arrival_seconds,
        rider=serialized.rider,
    )


@router.post("/request", response_model=RideResponse)
async def request_ride_alias(
    payload: RideRequestSchema,
    current_user: User = Depends(get_current_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> RideResponse:
    return await request_ride(payload, current_user, db_session)


@router.get("/active/current", response_model=Optional[RideStatusResponse])
async def get_current_ride(
    current_user: User = Depends(get_current_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> Optional[RideStatusResponse]:
    ride = await get_current_active_ride_for_user(current_user.id, db_session)
    return serialize_ride(ride) if ride else None


@router.get("/user/history", response_model=list[RideStatusResponse])
async def get_user_rides(
    current_user: User = Depends(get_current_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> list[RideStatusResponse]:
    rides = await get_all_rides_for_user(current_user.id, db_session)
    return [serialize_ride(ride) for ride in rides]


@router.get("/{ride_id}", response_model=RideStatusResponse)
async def get_ride_status(
    ride_id: str,
    current_user: User = Depends(get_current_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> RideStatusResponse:
    ride = await get_ride_by_customer(ride_id, current_user.id, db_session)
    return serialize_ride(ride)


@router.get("/rider/queue", response_model=list[RideStatusResponse])
async def get_rider_queue(
    current_rider: User = Depends(get_current_rider),
    db_session: AsyncSession = Depends(get_db_session),
) -> list[RideStatusResponse]:
    rides = await get_rider_dispatch_queue(current_rider.id, db_session)
    return [serialize_ride(ride) for ride in rides]


@router.get("/rider/history", response_model=list[RideStatusResponse])
async def get_rider_ride_history(
    current_rider: User = Depends(get_current_rider),
    db_session: AsyncSession = Depends(get_db_session),
) -> list[RideStatusResponse]:
    rides = await get_all_rides_for_rider(current_rider.id, db_session)
    return [serialize_ride(ride) for ride in rides]


@router.post("/{ride_id}/rider-response", response_model=RideStatusResponse)
async def rider_response(
    ride_id: str,
    payload: RiderRideActionRequest,
    current_rider: User = Depends(get_current_rider),
    db_session: AsyncSession = Depends(get_db_session),
) -> RideStatusResponse:
    ride = await handle_rider_response(ride_id, current_rider, payload.action, db_session)
    return await _broadcast_ride_state(ride.id, db_session, "ride.rider_response")


@router.post("/{ride_id}/status", response_model=RideStatusResponse)
async def rider_update_status(
    ride_id: str,
    payload: RideStatusUpdateRequest,
    current_rider: User = Depends(get_current_rider),
    db_session: AsyncSession = Depends(get_db_session),
) -> RideStatusResponse:
    ride = await update_ride_status(ride_id, current_rider, payload.status, payload.tracking_note, db_session)
    return await _broadcast_ride_state(ride.id, db_session, "ride.status")


@router.post("/{ride_id}/location", response_model=RideStatusResponse)
async def rider_push_location(
    ride_id: str,
    payload: RiderLocationUpdateRequest,
    current_rider: User = Depends(get_current_rider),
    db_session: AsyncSession = Depends(get_db_session),
) -> RideStatusResponse:
    ride = await record_rider_location(
        ride_id,
        current_rider,
        payload.latitude,
        payload.longitude,
        payload.heading,
        payload.speed,
        db_session,
    )
    return await _broadcast_ride_state(ride.id, db_session, "ride.location")


@router.get("/admin/live", response_model=AdminRideLiveResponse)
async def admin_live_rides(
    _: User = Depends(get_current_admin),
    db_session: AsyncSession = Depends(get_db_session),
) -> AdminRideLiveResponse:
    return await get_admin_live_overview(db_session)


@router.post("/admin/{ride_id}/assign", response_model=RideStatusResponse)
async def admin_assign_ride(
    ride_id: str,
    payload: AdminRideAssignRequest,
    _: User = Depends(get_current_admin),
    db_session: AsyncSession = Depends(get_db_session),
) -> RideStatusResponse:
    ride = await get_ride_for_actor(db_session, ride_id)
    rider = await db_session.get(User, payload.rider_id)
    if not rider or rider.role != "rider":
        raise HTTPException(status_code=404, detail="Rider not found")
    if rider.rider_status not in {"available", "online"}:
        raise HTTPException(status_code=409, detail="Only online riders can be assigned in ride ops")
    if rider.current_latitude is None or rider.current_longitude is None:
        raise HTTPException(status_code=409, detail="Rider must turn on location before assignment")
    ride = await assign_ride_to_rider(ride, rider, db_session)
    await create_notification(
        db_session,
        recipient_role="rider",
        recipient_user_id=rider.id,
        title="New ride assigned",
        message=f"You were assigned a {ride.vehicle_type} delivery from {ride.pickup_location}.",
        category="ride",
        action_url="/rider/navigate",
    )
    await create_notification(
        db_session,
        recipient_role="customer",
        recipient_user_id=ride.user_id,
        title="Rider assigned",
        message=f"{rider.full_name} was assigned to your ride request.",
        category="ride",
        action_url=f"/tracking/{ride.id}",
    )
    await db_session.commit()
    return await _broadcast_ride_state(ride.id, db_session, "ride.assigned")


@router.websocket("/ws")
async def rides_ws(
    websocket: WebSocket,
    token: str = Query(...),
    ride_id: Optional[str] = Query(default=None),
) -> None:
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        try:
            payload = decode_access_token(token)
        except ValueError:
            await websocket.close(code=4401)
            return

        identity_type = payload.get("type")
        subject = payload.get("sub")
        try:
            actor_id = int(subject)
        except (TypeError, ValueError):
            await websocket.close(code=4401)
            return

        connection_key = f"{identity_type}:{actor_id}:{ride_id or 'admin'}"

        if identity_type == "admin":
            connected = await ride_realtime_manager.connect_admin(websocket, connection_key)
            if not connected:
                return
            overview = await get_admin_live_overview(session)
            if not await _send_socket_payload(
                websocket,
                RideSocketEnvelope(event="ride.bootstrap", rides=overview.active_rides),
            ):
                ride_realtime_manager.disconnect(websocket)
                return
        else:
            if not ride_id:
                await websocket.close(code=4400)
                return
            ride = await get_ride_for_actor(session, ride_id)
            if identity_type == "user" and ride.user_id != actor_id:
                await websocket.close(code=4403)
                return
            if identity_type == "rider" and ride.rider_id != actor_id:
                await websocket.close(code=4403)
                return
            connected = await ride_realtime_manager.connect_ride(ride_id, websocket, connection_key)
            if not connected:
                return
            if not await _send_socket_payload(
                websocket,
                RideSocketEnvelope(event="ride.bootstrap", ride=serialize_ride(ride)),
            ):
                ride_realtime_manager.disconnect(websocket)
                return

        try:
            while True:
                message = await websocket.receive()
                message_type = message.get("type")
                if message_type == "websocket.disconnect":
                    break
                if message_type != "websocket.receive":
                    continue

                payload_text = message.get("text")
                if not payload_text:
                    continue

                try:
                    payload = json.loads(payload_text)
                except json.JSONDecodeError:
                    continue

                if payload.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
        except WebSocketDisconnect:
            pass
        finally:
            ride_realtime_manager.disconnect(websocket)

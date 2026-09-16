from __future__ import annotations

import asyncio
import os
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict

import requests
from fastapi import HTTPException

from app.core.config import settings as app_settings
from app.models.delivery_setting import DeliverySetting
from app.schemas.ride import RidePoint

_CURRENCY = "ZAR"
_CENT = Decimal("0.01")


def _money(value: Decimal | float | int) -> float:
    return float(Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP))


async def fetch_real_route(pickup: RidePoint, destination: RidePoint) -> Dict[str, Any]:
    if pickup.latitude == destination.latitude and pickup.longitude == destination.longitude:
        raise HTTPException(status_code=400, detail="Pickup and destination must be different")

    api_key = app_settings.openrouteservice_api_key.strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="Routing service is not configured")

    def request_route() -> Dict[str, Any]:
        response = requests.get(
            "https://api.openrouteservice.org/v2/directions/driving-car",
            params={
                "api_key": api_key,
                "start": f"{pickup.longitude},{pickup.latitude}",
                "end": f"{destination.longitude},{destination.latitude}",
            },
            timeout=15,
        )
        response.raise_for_status()
        feature = (response.json().get("features") or [None])[0]
        if not feature:
            raise ValueError("No route returned")
        segment = (feature.get("properties", {}).get("segments") or [None])[0]
        geometry = feature.get("geometry", {}).get("coordinates") or []
        if not segment or not geometry or not segment.get("distance") or not segment.get("duration"):
            raise ValueError("Incomplete route returned")
        return {
            "distance_meters": float(segment["distance"]),
            "duration_seconds": float(segment["duration"]),
            "coordinates": geometry,
        }

    try:
        return await asyncio.to_thread(request_route)
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else 502
        raise HTTPException(status_code=502 if status_code >= 500 else status_code, detail="Routing service request failed") from exc
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Unable to calculate route") from exc


def calculate_fare(route: Dict[str, Any], settings: DeliverySetting, vehicle_type: str) -> Dict[str, Any]:
    distance_km = Decimal(str(route["distance_meters"])) / Decimal("1000")
    duration_minutes = Decimal(str(route["duration_seconds"])) / Decimal("60")
    vehicle_surcharge = {
        "bike": Decimal(str(settings.bike_surcharge or 0)),
        "car": Decimal(str(settings.car_surcharge or 0)),
        "xl": Decimal(str(settings.xl_surcharge or 0)),
    }.get(vehicle_type, Decimal("0"))
    base_fare = Decimal(str(settings.base_fare or 0))
    distance_fare = distance_km * Decimal(str(settings.per_km or 0))
    time_fare = duration_minutes * Decimal(str(settings.per_minute or 0))
    service_fee = Decimal(str(settings.service_fee or 0)) + vehicle_surcharge
    booking_fee = Decimal(str(settings.booking_fee or 0))
    discount = Decimal("0")
    surge_multiplier = Decimal(str(settings.surge_multiplier or 1))
    subtotal = base_fare + distance_fare + time_fare + service_fee + booking_fee
    total = max(subtotal * surge_multiplier - discount, Decimal(str(settings.minimum_fare or 0)))

    return {
        "currency": _CURRENCY,
        "distance_km": _money(distance_km),
        "duration_minutes": _money(duration_minutes),
        "base_fare": _money(base_fare),
        "distance_fare": _money(distance_fare),
        "time_fare": _money(time_fare),
        "service_fee": _money(service_fee),
        "booking_fee": _money(booking_fee),
        "discount": _money(discount),
        "surge_multiplier": float(surge_multiplier),
        "total": _money(total),
    }

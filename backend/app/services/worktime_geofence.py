"""Shared office geofence validation for web and Telegram workday starts."""
from __future__ import annotations

import math
from typing import Any


WORKTIME_GEOFENCE_KEY = "worktime_geofence"
WORKTIME_GEOFENCE_RADIUS_METERS = 150


def configured_worktime_location(settings: dict[str, Any] | None) -> tuple[float, float] | None:
    value = (settings or {}).get(WORKTIME_GEOFENCE_KEY) or {}
    try:
        latitude = float(value["latitude"])
        longitude = float(value["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(latitude) or not math.isfinite(longitude):
        return None
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return None
    return latitude, longitude


def distance_meters(latitude: float, longitude: float, target_latitude: float, target_longitude: float) -> float:
    earth_radius_meters = 6_371_000
    latitude_delta = math.radians(target_latitude - latitude)
    longitude_delta = math.radians(target_longitude - longitude)
    current_latitude = math.radians(latitude)
    target_latitude = math.radians(target_latitude)
    haversine = math.sin(latitude_delta / 2) ** 2 + math.cos(current_latitude) * math.cos(target_latitude) * math.sin(longitude_delta / 2) ** 2
    return earth_radius_meters * 2 * math.atan2(math.sqrt(haversine), math.sqrt(max(0, 1 - haversine)))


def validate_worktime_location(settings: dict[str, Any] | None, latitude: float | None, longitude: float | None) -> tuple[str | None, float | None]:
    """Return a stable failure code and measured distance for an office start."""
    office_location = configured_worktime_location(settings)
    if office_location is None:
        return "worktime_geofence_not_configured", None
    if latitude is None or longitude is None:
        return "worktime_location_required", None
    distance = distance_meters(latitude, longitude, *office_location)
    if distance > WORKTIME_GEOFENCE_RADIUS_METERS:
        return "outside_worktime_geofence", distance
    return None, distance


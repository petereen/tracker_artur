"""Shared office geofence validation for web and Telegram workday starts."""
from __future__ import annotations

import math
from typing import Any


WORKTIME_GEOFENCE_KEY = "worktime_geofence"
WORKTIME_GEOFENCE_RADIUS_METERS = 150
WORKTIME_GEOFENCE_MIN_RADIUS_METERS = 25
WORKTIME_GEOFENCE_MAX_RADIUS_METERS = 5_000
WORKTIME_METHODS_KEY = "worktime_methods"


QR_ROTATION_MIN_SECONDS = 15
QR_ROTATION_MAX_SECONDS = 300
QR_ROTATION_DEFAULT_SECONDS = 30


def qr_rotation_seconds(settings: dict[str, Any] | None, default: int = QR_ROTATION_DEFAULT_SECONDS) -> int:
    """How long one displayed QR code stays valid, clamped to 15..300 seconds."""
    value = ((settings or {}).get(WORKTIME_METHODS_KEY) or {}).get("qr_rotation_seconds")
    if isinstance(value, bool) or not isinstance(value, int):
        value = default
    return max(QR_ROTATION_MIN_SECONDS, min(QR_ROTATION_MAX_SECONDS, value))


def worktime_methods(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Which office check-in methods the organization allows; both on by default."""
    value = (settings or {}).get(WORKTIME_METHODS_KEY) or {}
    return {
        "qr_enabled": value.get("qr_enabled") is not False,
        "location_enabled": value.get("location_enabled") is not False,
        "qr_rotation_seconds": qr_rotation_seconds(settings),
    }


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


def configured_worktime_radius(settings: dict[str, Any] | None) -> int:
    value = (settings or {}).get(WORKTIME_GEOFENCE_KEY) or {}
    try:
        radius = int(value.get("radius_meters", WORKTIME_GEOFENCE_RADIUS_METERS))
    except (AttributeError, TypeError, ValueError):
        return WORKTIME_GEOFENCE_RADIUS_METERS
    if not WORKTIME_GEOFENCE_MIN_RADIUS_METERS <= radius <= WORKTIME_GEOFENCE_MAX_RADIUS_METERS:
        return WORKTIME_GEOFENCE_RADIUS_METERS
    return radius


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
    methods = worktime_methods(settings)
    if not methods["location_enabled"]:
        # With QR on, the office is entered by scanning only; with every
        # method off, an office start needs no verification.
        return ("worktime_location_disabled", None) if methods["qr_enabled"] else (None, None)
    office_location = configured_worktime_location(settings)
    if office_location is None:
        return "worktime_geofence_not_configured", None
    if latitude is None or longitude is None:
        return "worktime_location_required", None
    distance = distance_meters(latitude, longitude, *office_location)
    if distance > configured_worktime_radius(settings):
        return "outside_worktime_geofence", distance
    return None, distance

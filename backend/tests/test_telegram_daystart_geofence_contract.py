from pathlib import Path

from app.services.worktime_geofence import validate_worktime_location


ROOT = Path(__file__).resolve().parents[1]
HANDLERS = (ROOT / "app" / "bot" / "work_report_handlers.py").read_text()
SERVICE = (ROOT / "app" / "services" / "work_report_service.py").read_text()


def test_daystart_prompts_for_a_one_tap_telegram_location_and_handles_location_updates():
    for marker in (
        "class DayStartFlow(StatesGroup)",
        "KeyboardButton(text=\"📍 Байршил илгээх\", request_location=True)",
        "@router.message(Command(\"daystart\"))",
        "@router.message(DayStartFlow.awaiting_location, F.location)",
        "location.latitude if location else None",
        "location.longitude if location else None",
    ):
        assert marker in HANDLERS


def test_telegram_daystart_passes_coordinates_into_the_shared_start_service():
    assert "latitude=latitude, longitude=longitude" in HANDLERS
    assert "validate_worktime_location" in SERVICE
    assert "latitude: float | None = None" in SERVICE
    assert "longitude: float | None = None" in SERVICE


def test_shared_geofence_accepts_office_coordinates_and_rejects_a_distant_location():
    settings = {"worktime_geofence": {"latitude": 47.9184, "longitude": 106.9177}}
    assert validate_worktime_location(settings, 47.9184, 106.9177)[0] is None
    assert validate_worktime_location(settings, 48.1, 106.9177)[0] == "outside_worktime_geofence"

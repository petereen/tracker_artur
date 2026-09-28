"""Organization toggles for QR and location based office check-in."""

from pathlib import Path

from app.services.worktime_geofence import validate_worktime_location, worktime_methods

ROOT = Path(__file__).resolve().parents[1]
OFFICE = {"worktime_geofence": {"latitude": 47.9184, "longitude": 106.9177, "radius_meters": 150}}


def test_methods_default_on_and_respect_explicit_false():
    assert worktime_methods(None) == {"qr_enabled": True, "location_enabled": True}
    assert worktime_methods({"worktime_methods": {"qr_enabled": False}}) == {"qr_enabled": False, "location_enabled": True}


def test_location_start_follows_the_toggles():
    near = (47.9184, 106.9177)
    assert validate_worktime_location(OFFICE, *near)[0] is None
    assert validate_worktime_location(OFFICE, None, None)[0] == "worktime_location_required"
    qr_only = {**OFFICE, "worktime_methods": {"location_enabled": False}}
    assert validate_worktime_location(qr_only, *near)[0] == "worktime_location_disabled"
    # With every method off an office start is unverified, even unconfigured.
    assert validate_worktime_location({"worktime_methods": {"location_enabled": False, "qr_enabled": False}}, None, None) == (None, None)


def test_qr_endpoints_and_clock_start_enforce_the_toggles():
    qr = (ROOT / "app" / "routers" / "worktime_qr.py").read_text()
    assert qr.count("await _require_qr_enabled(db,") == 2  # display token + scan
    enterprise = (ROOT / "app" / "routers" / "enterprise.py").read_text()
    assert '"/settings/worktime-methods"' in enterprise and "worktime_location_disabled" in enterprise
    assert "worktime_location_disabled" in (ROOT / "app" / "bot" / "work_report_handlers.py").read_text()

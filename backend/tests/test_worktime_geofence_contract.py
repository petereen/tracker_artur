import ast
from pathlib import Path

from app.services.worktime_geofence import configured_worktime_radius, validate_worktime_location


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "app" / "routers" / "enterprise.py").read_text()


def test_worktime_geofence_settings_and_clock_route_contract():
    tree = ast.parse(SOURCE)
    paths = {
        decorator.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list
        if isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr in {"get", "put", "post"}
        and decorator.args
        and isinstance(decorator.args[0], ast.Constant)
    }
    assert "/settings/worktime-geofence" in paths
    assert "/clock/start" in paths
    assert "WORKTIME_GEOFENCE_RADIUS_METERS" in SOURCE
    assert "WORKTIME_GEOFENCE_RADIUS_METERS = 150" in (ROOT / "app" / "services" / "worktime_geofence.py").read_text()
    assert "outside_worktime_geofence" in SOURCE
    assert "worktime_geofence_not_configured" in SOURCE


def test_worktime_geofence_uses_admin_settings_and_server_distance_check():
    for marker in (
        "Depends(require_roles(\"admin\"))",
        "organization.settings",
        "distance_meters",
        "data.latitude",
        "data.longitude",
        "radius_meters",
    ):
        assert marker in SOURCE


def test_worktime_geofence_uses_the_saved_radius_and_preserves_150m_legacy_default():
    office = {"worktime_geofence": {"latitude": 47.9184, "longitude": 106.9177, "radius_meters": 500}}
    assert configured_worktime_radius(office) == 500
    assert configured_worktime_radius({"worktime_geofence": {"latitude": 47.9184, "longitude": 106.9177}}) == 150
    assert validate_worktime_location(office, 47.921, 106.9177)[0] is None

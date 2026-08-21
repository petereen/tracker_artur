import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / "app" / "routers" / "worktime_reports.py").read_text()
SERVICE = (ROOT / "app" / "services" / "worktime_report_service.py").read_text()
MODEL = (ROOT / "app" / "models" / "models.py").read_text()
AUTH = (ROOT / "app" / "routers" / "enterprise_auth.py").read_text()


def test_report_routes_and_rbac_contract_are_registered_in_source():
    tree = ast.parse(ROUTER)
    paths = {
        decorator.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list
        if isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr == "get"
        and decorator.args
        and isinstance(decorator.args[0], ast.Constant)
    }
    assert {"/options", "/preview", "/export"}.issubset(paths)
    assert 'WORKTIME_REPORT_ROLES = frozenset({"admin", "manager", "hr", "team_lead"})' in (ROOT / "app" / "core" / "roles.py").read_text()
    assert "Depends(REPORT_ACCESS)" in ROUTER


def test_hr_is_a_valid_persisted_and_managed_role():
    assert "'hr'" in MODEL
    assert "SYSTEM_ROLES" in AUTH
    assert "'hr'" in (ROOT / "app" / "services" / "collaboration_permissions.py").read_text() or "SYSTEM_ROLES" in (ROOT / "app" / "services" / "collaboration_permissions.py").read_text()
    migration = (ROOT / "alembic" / "versions" / "r7s8t9u0v1w2_add_hr_role.py").read_text()
    assert "ck_role_assignments_role" in migration
    assert "'hr'" in migration


def test_report_service_contract_covers_scope_timezone_pagination_and_exports():
    for marker in (
        "TeamMember",
        "organization_id == actor.organization_id",
        "REPORT_MAX_DAYS = 366",
        "entry_type == \"work\"",
        "ZoneInfo",
        "async def iter_report_rows",
        "async def iter_worker_blocks",
        "Workday Average Hours",
        "Shift Intervals / Breakdown",
        "wrap_text",
        "column_dimensions",
        "async def csv_report",
        "async def xlsx_report",
        "average_daily_minutes_per_worker",
        "average_weekly_minutes_per_worker",
    ):
        assert marker in SERVICE

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "app" / "routers" / "worktime_qr.py").read_text()


def test_worktime_qr_router_exposes_pair_display_and_clock_contract():
    tree = ast.parse(SOURCE)
    paths = {
        decorator.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list
        if isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr in {"get", "post"}
        and decorator.args
        and isinstance(decorator.args[0], ast.Constant)
    }
    assert "/kiosks" in paths
    assert "/pair" in paths
    assert "/display-token" in paths
    assert "/clock" in paths


def test_qr_security_and_state_contract_is_present():
    assert "hmac.new" in SOURCE
    assert "IdempotencyRecord" in SOURCE
    assert 'source_channel="web_qr"' in SOURCE
    assert '"active_break"' in SOURCE
    assert '"switched_to_office"' in SOURCE
    migration = (ROOT / "alembic" / "versions" / "b7c8d9e0f1a2_worktime_qr.py").read_text()
    assert "uq_work_time_entries_employee_open" in migration
    assert "worktime_qr_kiosks" in migration


def test_kiosk_cookie_is_http_only_persistent_and_renewed_on_display_refresh():
    tree = ast.parse(SOURCE)
    cookie_helper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_set_kiosk_cookie")
    cookie_options = {
        keyword.arg: ast.unparse(keyword.value)
        for node in ast.walk(cookie_helper)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "set_cookie"
        for keyword in node.keywords
    }

    assert cookie_options["httponly"] == "True"
    assert cookie_options["secure"] == "settings.AUTH_COOKIE_SECURE"
    assert cookie_options["max_age"] == "settings.WORKTIME_QR_KIOSK_COOKIE_DAYS * 86400"
    assert cookie_options["path"] == "'/api/v1/worktime-qr'"
    assert "_set_kiosk_cookie(response, kiosk_cookie)" in SOURCE
    assert 'kiosk.status != "active"' in SOURCE


def test_employee_logout_only_clears_the_employee_refresh_cookie():
    auth_source = (ROOT / "app" / "routers" / "enterprise_auth.py").read_text()
    auth_tree = ast.parse(auth_source)
    logout = next(node for node in auth_tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "logout")
    deletion_calls = [
        node
        for node in ast.walk(logout)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "delete_cookie"
    ]

    assert len(deletion_calls) == 1
    assert isinstance(deletion_calls[0].args[0], ast.Name)
    assert deletion_calls[0].args[0].id == "REFRESH_COOKIE"
    assert next(keyword.value.value for keyword in deletion_calls[0].keywords if keyword.arg == "path") == "/api/v1/auth"

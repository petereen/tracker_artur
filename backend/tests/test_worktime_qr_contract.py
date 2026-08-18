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
    assert "TELEGRAM_BOT_USERNAME" in SOURCE
    assert "startapp" in SOURCE
    assert '"telegram_link"' in SOURCE
    assert 'source_channel="web_qr"' in SOURCE
    assert '"active_break"' in SOURCE
    assert '"switched_to_office"' in SOURCE
    migration = (ROOT / "alembic" / "versions" / "b7c8d9e0f1a2_worktime_qr.py").read_text()
    assert "uq_work_time_entries_employee_open" in migration
    assert "worktime_qr_kiosks" in migration

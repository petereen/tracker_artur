from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_unified_v2_migration_is_the_single_successor_and_contains_guardrails():
    migration = next(ROOT.glob("alembic/versions/*_unified_payroll_v2.py")).read_text()
    assert 'down_revision = "g2h3i4j5k6l7"' in migration
    assert 'revision = "h3i4j5k6l7m8"' in migration
    for marker in ("superseded_by_id", "component_master_id", "payroll_payment_reversals", "payroll_guard_immutable"):
        assert marker in migration


def test_v2_api_has_preflight_usage_preview_reversal_and_legacy_sunset():
    router = (ROOT / "app/payroll/router.py").read_text()
    service = (ROOT / "app/payroll/service.py").read_text()
    for marker in ('"/runs/preflight"', '"/components/{component_id}/usage"', '"/runs/{run_id}/posting-preview"', '"/payment-allocations/{allocation_id}/reverse"'):
        assert marker in router
    assert "payroll_legacy_write_gone" in router
    assert "payroll_worktime_overlap" in service
    assert "payroll_gl_mapping_incomplete" in service


def test_v2_frontend_only_queries_unified_runs():
    page = (ROOT.parent / "frontend/src/pages/PayrollWorkspacePage.tsx").read_text()
    api = (ROOT.parent / "frontend/src/api/enterprise.ts").read_text()
    assert "usePayrollEntries" not in page
    assert "workflow_version: 'unified_v2'" in api
    for route in ("/erp/payroll/setup", "/erp/payroll/runs/new", "/erp/payroll/runs/"):
        assert route in page

from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_hr_migration_is_single_reversible_head_and_preserves_time_off():
    migration = (ROOT / "alembic/versions/j0k1l2m3n4o5_hr_module.py").read_text()
    assert 'down_revision = "i0j1k2l3m4n5"' in migration
    assert 'op.rename_table("time_off", "leave_requests")' in migration
    assert 'op.rename_table("leave_requests", "time_off")' in migration
    assert "worker_invites" in migration and "token_hash" in migration
    assert "uq_worker_invites_active_employee" in migration


def test_hr_router_exposes_identity_leave_attendance_and_payroll_contracts():
    router = (ROOT / "app/hr/router.py").read_text()
    for path in (
        '"/leave-requests"',
        '"/attendance"',
        '"/attendance/export.csv"',
        '"/payroll/generate"',
        '"/invites/bind"',
        '"/employees/{employee_id}/invite/revoke"',
    ):
        assert path in router
    assert "async def create_hr_employee" in router
    assert "with_for_update()" in router
    assert "leave_balance_insufficient" in router
    assert "MANAGER_ROLES," in router


def test_telegram_login_paths_synchronize_profile_claims():
    auth = (ROOT / "app/routers/enterprise_auth.py").read_text()
    assert "profile: dict | None = None" in auth
    assert "employee.photo_url" in auth
    assert "first_name" in auth and "last_name" in auth

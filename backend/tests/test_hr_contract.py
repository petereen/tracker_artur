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
    assert '@router.patch("/leave-requests/{request_id}")' in router
    assert "Only pending or approved leave requests can be edited" in router
    assert "Only HR can edit approved leave requests" in router
    assert "Only HR can change leave request status" in router
    assert 'status: Literal["approved", "rejected"] | None' in (ROOT / "app/hr/schemas.py").read_text()


def test_telegram_login_paths_synchronize_profile_claims():
    auth = (ROOT / "app/routers/enterprise_auth.py").read_text()
    assert "profile: dict | None = None" in auth
    assert "employee.photo_url" in auth
    assert "first_name" in auth and "last_name" in auth


def test_worktime_start_paths_persist_hr_attendance_without_overwriting_manual_status():
    attendance = (ROOT / "app/services/attendance_service.py").read_text()
    work_report = (ROOT / "app/services/work_report_service.py").read_text()
    enterprise = (ROOT / "app/routers/enterprise.py").read_text()
    qr = (ROOT / "app/routers/worktime_qr.py").read_text()
    assert 'source="worktime"' in attendance
    assert 'if not log.confirmed_at:' in attendance
    assert "_sync_worktime_attendance(s, employee, local_day, started_at)" in work_report
    assert "await sync_worktime_attendance(db, employee, local_day, at=now)" in enterprise
    assert "await sync_worktime_attendance(db, employee, active.local_work_date, at=now)" in enterprise
    assert "await sync_worktime_attendance(db, employee, local_day, at=now)" in qr
    assert "_sync_worktime_attendance(s, employee, local_day, ended_at)" in work_report
    assert "_sync_worktime_attendance(s, employee, local_day, paused_at)" in work_report


def test_leave_lifecycle_notifies_requester_and_hr_and_emits_hr_events():
    router = (ROOT / "app/hr/router.py").read_text()
    frontend_api = (ROOT.parent / "frontend/src/api/enterprise.ts").read_text()
    realtime = (ROOT.parent / "frontend/src/components/EnterpriseShell.tsx").read_text()
    page = (ROOT.parent / "frontend/src/pages/HRWorkspacePage.tsx").read_text()

    assert "async def _hr_account_ids" in router
    assert 'kind="hr_leave_requested"' in router
    assert 'kind=f"hr_leave_{row.status}"' in router
    assert 'target_url="/hr?tab=leave"' in router
    assert "immediate=True" in router
    assert "['v1', 'hr']" in frontend_api
    assert "hr: 'hr'" in realtime
    assert "detail.code === 'leave_balance_insufficient'" in page
    assert "useUpdateHRLeave" in frontend_api
    assert "Edit leave request" in page
    assert "isHR && editing.status === 'approved'" in page
    assert "value: 'rejected', label: 'Татгалзсан'" in page


def test_hr_ui_can_set_annual_leave_days_for_new_and_existing_workers():
    api = (ROOT.parent / "frontend/src/api/enterprise.ts").read_text()
    page = (ROOT.parent / "frontend/src/pages/HRWorkspacePage.tsx").read_text()
    ui = (ROOT.parent / "frontend/src/components/ui.tsx").read_text()

    assert "useSetHRLeaveBalance" in api
    assert "/leave-balance" in api
    assert "annual_leave_days" in page
    assert "Баланс тохируулах" in page
    assert "entitled_days" in page
    assert "min?: string | number" in ui

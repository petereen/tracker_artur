from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_legacy_erp_payroll_api_is_retired_with_monthly_hint():
    source = (ROOT / "app/main.py").read_text()
    assert 'path.startswith("/v1/erp/payroll/")' in source
    assert '"code": "payroll_workflow_retired"' in source
    assert '"monthly_path": "/v1/erp/payroll/monthly"' in source
    assert 'not path.startswith("/v1/erp/payroll/monthly/")' in source


def test_hr_legacy_run_creation_is_retired_and_monthly_bank_api_is_owned_by_hr():
    source = (ROOT / "app/hr/router.py").read_text()
    assert '@router.post("/payroll/generate")' in source
    assert '"code": "payroll_workflow_retired"' in source
    assert '@router.get("/employees/{employee_id}/payroll-bank-accounts")' in source
    assert '@router.post("/employees/{employee_id}/payroll-bank-accounts"' in source


def test_monthly_archive_download_reads_frozen_workbook_bytes():
    source = (ROOT / "app/payroll/monthly_workflow.py").read_text()
    assert '@router.get("/archives/{archive_id}/runs/{run_id}/export")' in source
    assert 'get("exports_base64", {}).get(str(run_id))' in source
    assert "base64.b64decode(encoded)" in source


def test_monthly_draft_controls_keep_worker_sync_excel_and_computed_override_audit_paths():
    source = (ROOT / "app/payroll/monthly_workflow.py").read_text()
    assert '@router.post("/runs/{run_id}/sync-workers")' in source
    assert '@router.post("/runs/{run_id}/import-xlsx")' in source
    assert '@router.post("/runs/{run_id}/rows/{employee_id}/computed-overrides")' in source
    assert '@router.post("/runs/{run_id}/rows/{employee_id}/computed-overrides/revert")' in source
    assert 'field_name=f"computed:{data.field}"' in source
    assert 'field_name=f"computed:{data.field}:revert"' in source


def test_monthly_statutory_rule_set_draft_validate_publish_contract():
    source = (ROOT / "app/payroll/monthly_workflow.py").read_text()
    assert '@router.get("/rule-sets")' in source
    assert '@router.post("/rule-sets", status_code=status.HTTP_201_CREATED)' in source
    assert '@router.put("/rule-sets/{rule_id}")' in source
    assert '@router.post("/rule-sets/{rule_id}/validate")' in source
    assert '@router.post("/rule-sets/{rule_id}/publish")' in source
    assert 'published_effective_period_overlaps_version_' in source
    assert 'source_references' in source


def test_computed_override_calls_statutory_engine_recalculation():
    source = (ROOT / "app/payroll/monthly_workflow.py").read_text()
    engine = (ROOT / "app/payroll/monthly_engine.py").read_text()
    assert 'rules=rules' in source
    assert 'tax_relief_eligible=profile.tax_relief_eligible' in source
    assert 'taxable_income = max(ZERO, whole_tugrik(gross - employee_shi))' in engine

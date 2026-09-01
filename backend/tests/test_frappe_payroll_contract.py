from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_frappe_payroll_routes_cover_document_lifecycle():
    source = (ROOT / "app/payroll/router.py").read_text()
    required = (
        '"/payroll-periods"',
        '"/salary-components"',
        '"/salary-structure-assignments/bulk-assign"',
        '"/additional-salaries/{salary_id}/submit"',
        '"/payroll-entries/{entry_id}/get-employees"',
        '"/payroll-entries/{entry_id}/create-salary-slips"',
        '"/payroll-entries/{entry_id}/submit-salary-slips"',
        '"/payroll-entries/{entry_id}/make-bank-entry"',
        '"/payroll-entries/{entry_id}/cancel"',
        '"/payroll-entries/{entry_id}/amend"',
        '"/salary-slips"',
        '"/reports/salary-register"',
        '"/reports/bank-remittance"',
        '"/bank-entries/{bank_entry_id}/submit"',
    )
    for route in required:
        assert route in source


def test_new_migration_backfills_legacy_records_without_recalculation():
    source = (ROOT / "alembic/versions/i0j1k2l3m4n5_frappe_style_payroll.py").read_text()
    assert 'down_revision: Union[str, Sequence[str], None] = "h0c1d2e3f4g5"' in source
    assert "source_salary_component_id" in source
    assert '"source_salary_component_id": row.id' in source
    assert "legacy suffix" in source
    assert "UPDATE payroll_runs SET document_status" in source
    assert "SELECT DISTINCT ON (organization_id, period_start, period_end)" in source


def test_frappe_documents_have_tenant_and_lifecycle_boundaries():
    source = (ROOT / "app/models/models.py").read_text()
    for model in ("class PayrollPeriod", "class PayrollSalaryComponentMaster", "class AdditionalSalary", "class PayrollBankEntry"):
        assert model in source
    assert 'workflow_version = Column(String(16)' in source
    assert 'document_status = Column(String(16)' in source
    assert 'bank_entry_id = Column(Integer, ForeignKey("payroll_bank_entries.id"' in source


def test_salary_structure_lines_reference_reusable_component_masters():
    schemas = (ROOT / "app/payroll/schemas.py").read_text()
    service = (ROOT / "app/payroll/service.py").read_text()
    router = (ROOT / "app/payroll/router.py").read_text()
    assert "component_master_id: int | None = None" in schemas
    assert "PayrollSalaryComponentMaster.id.in_(master_ids)" in service
    assert '"component_master_id": row.component_master_id' in router

from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_stabilization_migration_is_additive_and_single_head_successor():
    migration = (ROOT / "alembic/versions/f1g2h3i4j5k6_erp_payroll_stabilization.py").read_text()
    assert 'down_revision: Union[str, Sequence[str], None] = "n1o2p3q4r5s6"' in migration
    assert 'CREATE TRIGGER erp_gl_immutable' in migration
    assert 'payroll_payment_allocations' in migration
    assert 'UPDATE employee_bank_accounts a' in migration


def test_payroll_api_exposes_frozen_lifecycle_and_treasury_resources():
    router = (ROOT / "app/payroll/router.py").read_text()
    service = (ROOT / "app/payroll/service.py").read_text()
    assert '"/runs/{run_id}/return"' in router
    assert '"/runs/{run_id}/payments"' in router
    assert '"/payment-allocations"' in router
    assert '"/bank-statement-imports"' in router
    assert 'workflow_version="unified_v2"' in service
    assert 'payroll_accrual_reversal_requires_payment_reversal' in service


def test_bank_exports_reject_unverified_provisional_templates():
    router = (ROOT / "app/payroll/router.py").read_text()
    assert "payroll_bank_template_requires_verified_sample" in router
    assert "PayrollBankExportProfile.is_provisional.is_(False)" in router


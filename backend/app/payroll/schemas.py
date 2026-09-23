from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class SHIRateInput(BaseModel):
    payer: Literal["employee", "employer"]
    insurance_fund: str = Field(min_length=1, max_length=32)
    insured_category: str = Field(default="employee", max_length=32)
    hazard_class: str = Field(default="standard", max_length=16)
    rate: Decimal = Field(ge=0, le=1)
    base_floor: Decimal = Field(default=Decimal("0"), ge=0)
    lower_bound: Decimal = Field(default=Decimal("0"), ge=0)
    upper_bound: Decimal | None = Field(default=None, gt=0)
    calculation_mode: Literal["flat_percent", "marginal_tiers", "band_rate", "formula"] = "flat_percent"
    fixed_amount: Decimal = Field(default=Decimal("0"), ge=0)
    base_tax: Decimal = Field(default=Decimal("0"), ge=0)
    base_ceiling_policy: Literal["profile", "none"] = "profile"
    formula: str | None = Field(default=None, max_length=1000)
    exemption_code: str | None = Field(default=None, max_length=64)
    position: int = Field(default=0, ge=0)


class PITBracketInput(BaseModel):
    lower_bound: Decimal = Field(ge=0)
    upper_bound: Decimal | None = Field(default=None, gt=0)
    marginal_rate: Decimal = Field(ge=0, le=1)
    base_tax: Decimal = Field(default=Decimal("0"), ge=0)
    period_basis: Literal["monthly", "annual", "period"] = "annual"
    position: int = Field(default=0, ge=0)


class ReliefTierInput(BaseModel):
    eligibility_code: str = Field(min_length=1, max_length=64)
    lower_bound: Decimal = Field(ge=0)
    upper_bound: Decimal | None = Field(default=None, gt=0)
    fixed_amount: Decimal = Field(ge=0)
    amount_basis: Literal["monthly", "annual", "period"] = "annual"
    formula: str | None = None
    position: int = Field(default=0, ge=0)


class StatutoryProfileInput(BaseModel):
    code: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    version: int = Field(default=1, ge=1)
    effective_from: date
    effective_to: date | None = None
    tax_point_basis: Literal["payment_date", "period_end"] = "payment_date"
    currency: str = Field(default="MNT", min_length=3, max_length=3)
    minimum_wage: Decimal = Field(ge=0)
    shi_ceiling_multiplier: Decimal = Field(ge=0)
    pit_withholding_method: Literal["ytd_cumulative", "isolated_period"] = "ytd_cumulative"
    pit_calculation_mode: Literal["flat_percent", "marginal_tiers", "band_rate", "formula"] = "marginal_tiers"
    pit_formula: str | None = Field(default=None, max_length=1000)
    standard_daily_hours: Decimal = Field(default=Decimal("8"), gt=0, le=24)
    standard_weekly_hours: Decimal = Field(default=Decimal("40"), gt=0, le=168)
    standard_workweek: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5], min_length=1, max_length=7)
    rounding_policy: dict[str, Any] = Field(default_factory=dict)
    leave_policy: dict[str, Any] = Field(default_factory=lambda: {"lookback_months": 12, "missing_history_fallback": "error"})
    source_references: list[str] = Field(default_factory=list)
    is_example: bool = False
    shi_rates: list[SHIRateInput] = Field(default_factory=list)
    pit_brackets: list[PITBracketInput] = Field(default_factory=list)
    relief_tiers: list[ReliefTierInput] = Field(default_factory=list)


class PublishProfileInput(BaseModel):
    acknowledge_example: bool = False


class SalaryComponentInput(BaseModel):
    # A structure line may point at a reusable Salary Component master while
    # retaining the submitted line fields as its frozen calculation snapshot.
    component_master_id: int | None = None
    code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=160)
    component_kind: Literal["earning", "deduction", "employer_cost"]
    formula: str = Field(min_length=1, max_length=1000)
    amount_mode: Literal["fixed", "percentage", "formula"] = "formula"
    percentage_basis: str | None = Field(default=None, max_length=80)
    proration_basis: Literal["none", "working_days", "calendar_days", "hours"] = "none"
    is_taxable: bool = True
    is_shi_subject: bool = True
    is_non_taxable_allowance: bool = False
    is_leave_average_eligible: bool = True
    is_flexible_benefit: bool = False
    max_benefit_amount_yearly: Decimal = Field(default=Decimal("0"), ge=0)
    pay_against_benefit_claim: bool = False
    only_tax_impact: bool = False
    payer: Literal["employee", "employer"] = "employee"
    position: int = Field(default=0, ge=0)
    account_id: int | None = None
    cost_center_id: int | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ContributorTypeInput(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=2000)
    effective_from: date
    effective_to: date | None = None
    source_references: list[str] = Field(default_factory=list)
    status: Literal["draft", "active", "archived"] = "draft"


class WorkPolicyInput(BaseModel):
    code: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=160)
    scope_type: Literal["organization", "job_title", "employee"] = "organization"
    scope_key: str = Field(default="*", max_length=160)
    effective_from: date
    effective_to: date | None = None
    daily_hours: Decimal = Field(gt=0, le=24)
    weekly_hours: Decimal = Field(gt=0, le=168)
    workweek: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5], min_length=1, max_length=7)
    hazard_class: str = Field(default="standard", min_length=1, max_length=16)
    overtime_rules: dict[str, Any] = Field(default_factory=dict)
    stacking_policy: Literal["exclusive", "stack"] = "stack"
    source_references: list[str] = Field(default_factory=list)


class FormulaValidationInput(BaseModel):
    formula: str = Field(min_length=1, max_length=1000)
    variables: dict[str, Decimal | int | float | str | bool] = Field(default_factory=dict)


class FormulaPreviewInput(BaseModel):
    formula: str = Field(min_length=1, max_length=1000)
    context: dict[str, Decimal | int | float | str | bool] = Field(default_factory=dict)
    quantum: Decimal = Field(default=Decimal("0.01"), gt=0)


class FormulaVariableInput(BaseModel):
    code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=200)
    data_type: Literal["decimal", "integer", "boolean", "text"] = "decimal"
    default_value: str | None = None
    source: Literal["manual", "attendance", "leave", "ytd", "statutory"] = "manual"
    required: bool = False
    minimum: Decimal | None = None
    maximum: Decimal | None = None


class StatutorySimulationInput(BaseModel):
    base_salary: Decimal = Field(default=Decimal("0"), ge=0)
    taxable_income: Decimal = Field(ge=0)
    shi_subject_gross: Decimal = Field(ge=0)
    components: list[dict[str, Any]] = Field(default_factory=list)
    context: dict[str, Decimal | int | float | str | bool] = Field(default_factory=dict)
    other_deductions: Decimal = Field(default=Decimal("0"), ge=0)
    insured_category: str = Field(default="employee", max_length=32)
    hazard_class: str = Field(default="standard", max_length=32)
    prior_month_shi_base: Decimal = Field(default=Decimal("0"), ge=0)
    relief_eligibilities: list[str] = Field(default_factory=list)
    exemption_codes: list[str] = Field(default_factory=list)


class ReportTemplateInput(BaseModel):
    kind: Literal["salary_register", "nd7a", "nd7b", "nd8", "tt11"]
    version: int = Field(default=1, ge=1)
    template: dict[str, Any] = Field(default_factory=dict)
    required_keys: list[str] = Field(default_factory=list)
    source_references: list[str] = Field(default_factory=list)


class SalaryStructureInput(BaseModel):
    code: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=160)
    effective_from: date
    effective_to: date | None = None
    currency: str = Field(default="MNT", min_length=3, max_length=3)
    components: list[SalaryComponentInput] = Field(default_factory=list)


class EmployeePayrollInput(BaseModel):
    employee_id: int
    salary_structure_id: int
    effective_from: date
    effective_to: date | None = None
    base_salary: Decimal = Field(ge=0)
    insured_category: str = "01001"
    hazard_class: str = "standard"
    residency_status: str = "resident"
    tax_relief_eligibility: list[str] = Field(default_factory=list)
    exemption_flags: dict[str, Any] = Field(default_factory=dict)
    taxpayer_number: str | None = None
    social_insurance_number: str | None = None
    payment_method: Literal["bank", "cash", "other"] = "bank"


class BankAccountInput(BaseModel):
    bank_code: str = Field(min_length=1, max_length=32)
    account_number: str = Field(min_length=4, max_length=64)
    account_holder: str | None = Field(default=None, max_length=240)
    is_primary: bool = True
    valid_from: date
    valid_to: date | None = None


class PostingProfileInput(BaseModel):
    code: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    account_roles: dict[str, int]


class PayrollAccountTagsInput(BaseModel):
    purposes: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("purposes")
    @classmethod
    def unique_purposes(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("Payroll account purposes must be unique")
        return values


class BankExportProfileInput(BaseModel):
    bank_code: str = Field(min_length=1, max_length=32)
    version: int = Field(default=1, ge=1)
    format: Literal["csv", "json", "xlsx"] = "csv"
    template: dict[str, Any] = Field(default_factory=dict)
    is_provisional: bool = True


class BankTemplateSampleInput(BaseModel):
    bank_sample_reference: str = Field(min_length=1, max_length=255)
    sample_rows: list[dict[str, str]] = Field(min_length=1, max_length=100)
    expected_content_base64: str = Field(min_length=1, max_length=1400000)


class BankExportRequest(BaseModel):
    bank_code: str = Field(min_length=1, max_length=32)
    format: Literal["csv", "json", "xlsx"] | None = None
    version: int | None = Field(default=None, ge=1)


class VariablePayInput(BaseModel):
    employee_id: int
    code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=160)
    amount: Decimal = Field(gt=0)
    component_kind: Literal["earning", "deduction"]
    taxable: bool = True
    shi_subject: bool = True
    source: Literal["manual", "commission", "reimbursement", "bonus", "loan", "import"] = "manual"
    reference: str | None = Field(default=None, max_length=255)


class PayrollRunInput(BaseModel):
    run_type: Literal["advance", "final", "single", "off_cycle"]
    payroll_period_id: int = Field(gt=0)
    period_start: date
    period_end: date
    posting_date: date | None = None
    tax_point_date: date
    statutory_profile_id: int | None = None
    employee_ids: list[int] = Field(default_factory=list)
    employee_filter: dict[str, str | int | None] = Field(default_factory=dict)
    validate_attendance: bool = True
    attendance_policy: dict[str, Any] = Field(default_factory=dict)
    cost_center_id: int | None = None
    input_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    variable_inputs: list[VariablePayInput] = Field(default_factory=list)


class PayrollCycleInputCorrection(BaseModel):
    employee_id: int
    actual_worked_hours: Decimal = Field(ge=0)
    overtime_by_type: dict[Literal["weekday", "rest_day", "public_holiday", "night"], Decimal] = Field(default_factory=dict)
    evidence_reference: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=1000)


class CalculateRunInput(BaseModel):
    acknowledge_example: bool = False


class ReconciliationResolutionInput(BaseModel):
    issue_keys: list[str] = Field(default_factory=list)
    note: str = Field(min_length=1, max_length=1000)


class PayrollApprovalInput(BaseModel):
    stage: Literal["payroll_manager", "hr_director", "finance"] | None = None
    comment: str | None = Field(default=None, max_length=1000)


class PayrollReturnInput(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class VersionBumpInput(BaseModel):
    effective_from: date


class PayrollPaymentReversalInput(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    transaction_reference: str = Field(min_length=1, max_length=160)
    evidence: dict[str, Any] = Field(default_factory=dict)


class PayrollRunReversalInput(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    posting_date: date | None = None


class PayslipPublicationInput(BaseModel):
    notify_employees: bool = True


class ProtectedPayslipInput(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class ReplacementRunInput(PayrollRunInput):
    """Inputs for a replacement run linked to a finalized run."""

    acknowledge_example: bool = False


class TaxExemptionCategoryInput(BaseModel):
    code: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=160)
    treatment: Literal["tax_deduction", "tax_credit"] = "tax_deduction"
    annual_limit: Decimal = Field(default=Decimal("0"), ge=0)
    requires_proof: bool = True


class TaxExemptionCategoryUpdateInput(BaseModel):
    code: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=160)
    treatment: Literal["tax_deduction", "tax_credit"] = "tax_deduction"
    annual_limit: Decimal = Field(default=Decimal("0"), ge=0)
    requires_proof: bool = True
    is_active: bool = True


class TaxDeclarationInput(BaseModel):
    employee_id: int | None = None
    category_id: int
    tax_year: int = Field(ge=2000, le=2200)
    declared_amount: Decimal = Field(gt=0)
    note: str | None = Field(default=None, max_length=1000)


class TaxProofInput(BaseModel):
    amount: Decimal = Field(gt=0)
    reference: str = Field(min_length=1, max_length=500)


class BenefitApplicationInput(BaseModel):
    employee_id: int | None = None
    salary_component_id: int
    tax_year: int = Field(ge=2000, le=2200)
    requested_amount: Decimal = Field(gt=0)
    note: str | None = Field(default=None, max_length=1000)


class BenefitApplicationReviewInput(BaseModel):
    approved_amount: Decimal = Field(ge=0)
    approve: bool = True


class BenefitClaimInput(BaseModel):
    application_id: int
    claim_date: date
    amount: Decimal = Field(gt=0)
    reference: str = Field(min_length=1, max_length=500)


class ReviewDecisionInput(BaseModel):
    approve: bool = True


# Frappe-style document contracts.  The legacy PayrollRun contracts above are
# intentionally kept for compatibility with existing clients and history.
class PayrollPeriodInput(BaseModel):
    code: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=160)
    start_date: date
    end_date: date
    tax_year: int = Field(ge=2000, le=2200)
    payroll_frequency: Literal["monthly"] = "monthly"
    statutory_profile_id: int


class SalaryComponentMasterInput(BaseModel):
    code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=160)
    component_kind: Literal["earning", "deduction", "employer_cost"]
    formula: str = Field(min_length=1, max_length=1000)
    amount_mode: Literal["fixed", "percentage", "formula"] = "formula"
    percentage_basis: str | None = Field(default=None, max_length=80)
    proration_basis: Literal["none", "working_days", "calendar_days", "hours"] = "none"
    is_taxable: bool = True
    is_shi_subject: bool = True
    is_non_taxable_allowance: bool = False
    is_leave_average_eligible: bool = True
    is_flexible_benefit: bool = False
    max_benefit_amount_yearly: Decimal = Field(default=Decimal("0"), ge=0)
    pay_against_benefit_claim: bool = False
    only_tax_impact: bool = False
    payer: Literal["employee", "employer"] = "employee"
    account_id: int | None = None
    cost_center_id: int | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    description: str | None = Field(default=None, max_length=1000)


class SalaryStructureAssignmentInput(EmployeePayrollInput):
    document_status: Literal["draft", "submitted"] = "submitted"


class BulkSalaryStructureAssignmentInput(BaseModel):
    employee_ids: list[int] = Field(min_length=1)
    salary_structure_id: int
    effective_from: date
    effective_to: date | None = None
    base_salary: Decimal = Field(ge=0)
    insured_category: str = "employee"
    hazard_class: str = "standard"
    residency_status: str = "resident"
    tax_relief_eligibility: list[str] = Field(default_factory=list)
    exemption_flags: dict[str, Any] = Field(default_factory=dict)
    payment_method: Literal["bank", "cash", "other"] = "bank"


class AdditionalSalaryInput(BaseModel):
    employee_id: int
    salary_component_id: int
    payroll_date: date
    amount: Decimal = Field(gt=0)
    component_kind: Literal["earning", "deduction"] = "earning"
    taxable: bool = True
    shi_subject: bool = True
    source: Literal["manual", "commission", "reimbursement", "bonus", "loan", "import"] = "manual"
    reference: str | None = Field(default=None, max_length=500)


class PayrollEntryInput(BaseModel):
    run_type: Literal["advance", "final", "single", "off_cycle"] = "single"
    payroll_period_id: int = Field(gt=0)
    period_start: date
    period_end: date
    posting_date: date
    tax_point_date: date
    payroll_frequency: Literal["monthly"] = "monthly"
    statutory_profile_id: int | None = None
    employee_ids: list[int] = Field(default_factory=list)
    employee_filter: dict[str, str | None] = Field(default_factory=dict)
    input_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    validate_attendance: bool = True
    payment_account_id: int | None = None
    cost_center_id: int | None = None
    variable_inputs: list[VariablePayInput] = Field(default_factory=list)


class GetEmployeesInput(BaseModel):
    employee_ids: list[int] = Field(default_factory=list)
    work_branch: str | None = None
    work_direction: str | None = None
    job_title: str | None = None
    validate_attendance: bool | None = None


class BankEntryInput(BaseModel):
    payment_account_id: int | None = None
    posting_date: date | None = None


class PaymentAllocationInput(BaseModel):
    payslip_id: int
    amount: Decimal = Field(gt=0)


class PaymentBatchInput(BaseModel):
    payment_account_id: int | None = None
    posting_date: date | None = None
    allocations: list[PaymentAllocationInput] = Field(default_factory=list)
    retry_of_batch_id: int | None = None


class PaymentSettlementInput(BaseModel):
    transaction_reference: str = Field(min_length=1, max_length=160)
    settled_at: date | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class PaymentRejectInput(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class StatementLineInput(BaseModel):
    transaction_reference: str | None = None
    transaction_date: date
    amount: Decimal
    currency: str = Field(default="MNT", min_length=3, max_length=3)
    description: str | None = None
    fee_amount: Decimal = Field(default=Decimal("0"), ge=0)


class StatementImportInput(BaseModel):
    payment_account_id: int
    source_checksum: str = Field(min_length=64, max_length=64)
    statement_start: date | None = None
    statement_end: date | None = None
    lines: list[StatementLineInput] = Field(default_factory=list)


class PayrollCancelInput(BaseModel):
    reason: str = Field(default="Cancelled by payroll administrator", min_length=1, max_length=1000)


# Public document names used by the Frappe-style API.  The input contracts
# retain the explicit ``Input`` suffix while these aliases keep generated
# clients and integration tests aligned with ERP document terminology.
class SalarySlip(BaseModel):
    id: int
    payroll_run_id: int
    employee_id: int
    gross: Decimal
    employee_shi: Decimal
    employer_shi: Decimal
    pit: Decimal
    net_pay: Decimal
    document_status: Literal["draft", "submitted", "cancelled"] = "draft"


PayrollEntry = PayrollEntryInput
SalaryStructureAssignment = SalaryStructureAssignmentInput
AdditionalSalary = AdditionalSalaryInput
PayrollPeriod = PayrollPeriodInput
BankEntry = BankEntryInput

# OYUNS Mongolia payroll architecture

> **Current workflow:** `/erp/payroll` and `/erp/payroll/monthly` use the run-based monthly payroll module described below. The earlier Frappe-style Payroll Entry, salary slip, payslip, setup, and tax-benefit product routes are retired. Legacy payroll API calls return HTTP `410` with code `payroll_workflow_retired` and a monthly route hint. Historical legacy tables and posted accounting records remain in PostgreSQL and are not exposed through the product. Bank-account operations required by HR are owned by the HR API.

The monthly workflow freezes each month's statutory rules, work calendar, worker inputs, salary segments, approval actors, calculation results, and generated workbooks. It reads confirmed attendance, approved work-time entries and leave, holidays, schedules, and employment dates. Final runs contain the full eligible worker set and preserve worker-specific pay dates. Month close checks run and row approvals, profile completeness, gross-to-net equations, negative net, and advance reconciliation, then saves a versioned snapshot with exact workbook bytes. Unlocking a month creates a later archive version; prior versions remain readable.

Draft controls include schedule-based advance creation, one-off worker advances, HR worker synchronization, time refresh that preserves edited inputs, reasoned row flags, input and computed-cell overrides with per-field revert, row audit history, and Excel input import. Computed-cell overrides rebuild total deductions and net pay to retain the gross-to-net equation. Advance reconciliation compares each employee's approved advance IDs, amounts, and scheduled pay dates before final approval. Legacy payroll read/write endpoints return an explicit retirement response.

Payroll administrators can draft effective-dated statutory rule versions, record source references, validate contribution rates and tax/relief tiers, check for overlap with published periods, and publish a successor version. Publishing a later-dated successor closes the predecessor's effective period on the prior day and records that boundary adjustment in the audit log. New months select the published rule effective on their first day; an existing month retains its frozen rule snapshot. A gross override recalculates SHI bases and contributions, taxable income, PIT relief, PIT, deductions, and net pay. An explicitly overridden contribution or PIT value remains fixed while its downstream values are recalculated.

Rollout still requires the deployment operator to take and verify a PostgreSQL backup, rehearse migration and restore against an isolated database, and complete the browser acceptance journey against migrated PostgreSQL. Those operational steps are not run from a developer checkout without a configured target database.

This document describes the configurable Mongolia payroll domain. Monetary
values are calculated with Python `Decimal` and persisted as PostgreSQL
`numeric(20,4)`. The prompt figures are seeded as an inactive example profile
with an unverified placeholder checksum and are not legal advice. A payroll administrator must review source documents,
enter relief tiers, configure accounts, and publish a profile before a run can
be calculated.

Compliance references (verify against the current issuer templates before
activation): [PIT law](https://legalinfo.mn/mn/detail?lawId=14410),
[social-insurance law](https://legalinfo.mn/mn/detail?lawId=16760148379551),
[НД reporting rules](https://legalinfo.mn/mn/detail?lawId=17048251350081), and
[ТТ-11 order](https://legalinfo.mn/mn/detail?lawId=16532671533721). These links
are references, not a certification that an export is accepted by a government
portal or commercial bank.

## Database contract

The Alembic revision `f0a1b2c3d4e5_mongolia_payroll.py` is the base executable
DDL; `i0j1k2l3m4n5_frappe_style_payroll.py` adds the document workflow without
rewriting historical rows.
The following is the public shape (all tables also carry tenant keys where
applicable):

```sql
create table statutory_config_profiles (
  id integer primary key, organization_id integer not null references organizations(id),
  code varchar(80) not null, jurisdiction varchar(8) not null default 'MN',
  version integer not null, status varchar(16) not null, effective_from date not null,
  effective_to date, tax_point_basis varchar(24) not null default 'payment_date',
  currency char(3) not null default 'MNT', minimum_wage numeric(20,4) not null,
  shi_ceiling_multiplier numeric(12,6) not null,
  pit_withholding_method varchar(24) not null default 'ytd_cumulative',
  rounding_policy jsonb not null default '{}', leave_policy jsonb not null default '{}',
  source_references jsonb not null default '[]', is_example boolean not null default false,
  checksum char(64) not null, approved_by_account_id integer, approved_at timestamptz
);
create table shi_rate_tiers (
  id integer primary key, profile_id integer not null references statutory_config_profiles(id),
  payer varchar(12) not null, insurance_fund varchar(32) not null,
  insured_category varchar(32) not null, hazard_class varchar(16) not null,
  rate numeric(12,8) not null, base_floor numeric(20,4) not null default 0,
  base_ceiling_policy varchar(24) not null default 'profile', exemption_code varchar(64),
  position integer not null default 0
);
create table pit_bracket_tiers (
  id integer primary key, profile_id integer not null references statutory_config_profiles(id),
  period_basis varchar(16) not null, lower_bound numeric(20,4) not null,
  upper_bound numeric(20,4), marginal_rate numeric(12,8) not null,
  base_tax numeric(20,4) not null default 0, position integer not null
);
create table tax_relief_tiers (
  id integer primary key, profile_id integer not null references statutory_config_profiles(id),
  eligibility_code varchar(64) not null, lower_bound numeric(20,4) not null,
  upper_bound numeric(20,4), fixed_amount numeric(20,4) not null,
  amount_basis varchar(16) not null, formula text, position integer not null
);
create table salary_structures (
  id integer primary key, organization_id integer not null references organizations(id),
  code varchar(80) not null, name text not null, version integer not null,
  status varchar(16) not null, effective_from date not null, effective_to date,
  currency char(3) not null, checksum char(64) not null
);
create table salary_structure_versions (
  id integer primary key, salary_structure_id integer not null references salary_structures(id),
  version integer not null, status varchar(16) not null, effective_from date not null,
  effective_to date, component_snapshot jsonb not null, checksum char(64) not null,
  published_by_account_id integer, published_at timestamptz
);
create table salary_components (
  id integer primary key, salary_structure_id integer not null references salary_structures(id),
  code varchar(80) not null, name text not null, component_kind varchar(24) not null,
  formula text not null, proration_basis varchar(24) not null,
  is_taxable boolean not null, is_shi_subject boolean not null,
  is_non_taxable_allowance boolean not null, is_leave_average_eligible boolean not null,
  payer varchar(12) not null, position integer not null, account_id integer, cost_center_id integer
);
```

`employee_payroll_profiles` stores effective-dated salary and classification;
taxpayer/social-insurance numbers and `employee_bank_accounts` account numbers
are encrypted with the application secret. Only a last-four display value and
SHA-256 duplicate-detection fingerprint are returned by APIs.

`payroll_runs` freezes the selected statutory profile, input payload, engine
version, and checksum. `payslips` and `payslip_line_items` store the employee
profile, formula trace, YTD values, SHI-subject gross/base, relief, and all
gross-to-net amounts. `payroll_employee_accumulators` is append-only and
sequences each employee’s tax-year deltas. Advances, posting profiles, bank
templates, and export artifacts are separate tables. Export content is encrypted
at rest, checksum-verified, and exposed through a short-lived download URL.

## Retired Frappe-style payroll workflow (historical schema)

Revision `i0j1k2l3m4n5_frappe_style_payroll.py` adds the document boundaries
used by the new OYUNS workspace without installing Frappe.  `PayrollPeriod`,
`PayrollSalaryComponentMaster`, `AdditionalSalary`, and `PayrollBankEntry` are
tenant-scoped masters/documents.  Existing `SalaryComponent` rows point to a
master while retaining their frozen formula, tax/SHI flags, account, and cost
center; conflicting legacy definitions receive deterministic legacy codes.

Historical entries used `workflow_version=frappe_v1` and followed this sequence. This path is retired from product navigation and its legacy API returns `410`:

```text
Payroll Entry (draft)
  -> Get Employees (filters + assignment/bank/attendance validation)
  -> Create Salary Slips (Decimal engine + submitted Additional Salary)
  -> Submit Salary Slips (GL accrual, YTD/benefits/advances, ESS publication)
  -> Make Bank Entry (separate net-pay payable settlement)
```

The source run and salary slips are immutable after submission.  Cancel creates
negative reversal entries and marks the source document/slips cancelled; Amend
creates a linked replacement.  Legacy staged runs remain available through the
compatibility `/runs` routes and are never recalculated by the backfill.

## Pure calculation contract

`calculate_payslip(CalculationInput, StatutoryRules)` has no database or clock
dependency. It resolves component dependencies using an allowlisted AST (no
`eval`, attributes, subscripts, arbitrary calls, loops, or I/O), then:

```text
freeze profile, employee, approved time, overrides, prior YTD, advances
for each component in dependency order:
    amount = safe_formula(context + prior components)
    amount = prorate(amount, component.proration_basis)
gross = sum(employee earning components)
shi_subject = sum(SHI-subject employee earnings)
cap = minimum_wage * shi_ceiling_multiplier
shi_base = min(shi_subject, max(cap - prior_month_shi_base, 0))
employee/employer SHI = sum(shi_base * configured fund rates)
taxable = taxable earnings - employee SHI - configured deductions
pit_basis = prior_ytd_taxable + taxable      # ytd_cumulative
pit_due = progressive_tax(pit_basis) - prior_ytd_pit
relief_due = cumulative_relief(pit_basis) - prior_ytd_relief
pit = max(pit_due - relief_due, 0)
net_before_advance = gross - employee SHI - PIT - other deductions
advance_offset = min(advance, max(net_before_advance, 0))
net_pay = net_before_advance - advance_offset
assert every total and persisted snapshot checksum
```

An `advance` run evaluates the configured earning components but sets
`withhold_statutory=false`: it consumes neither the monthly SHI cap nor the YTD
PIT accumulator. The final/single run carries the full statutory liability and
offsets the advance once. Organisations that pay a percentage advance express
that amount in the approved component formula or audited run override.

The profile can select `isolated_period`; Mongolia’s annual progressive PIT
schedule should normally be represented as `annual` brackets with cumulative
withholding. Vacation pay uses eligible finalized earnings divided by eligible
worked days over the configured 12-month lookback, multiplied by leave days.

## Posting matrix

The dedicated posting service creates an accounting document and balanced,
append-only `erp_general_ledger_entries`:

| Event | Debit | Credit |
|---|---|---|
| Payroll accrual | Salary expense by component/cost center | Employee SHI payable, PIT payable, other deductions payable, net salary payable |
| Employer contributions | Employer SHI expense | Employer SHI payable by fund |
| Advance payment (advance run) | Employee advance clearing | Bank |
| Advance payment (bank settlement) | Employee advance clearing | Bank |
| Final advance offset | Net salary payable | Employee advance clearing |
| Net payout | Net salary payable | Bank |
| Statutory remittance | SHI/PIT payable | Bank |

Posting is blocked unless the organization’s active `payroll_posting_profiles`
maps every required logical role to an active ERP account and total debits equal
total credits. Corrections are reversal/replacement runs; finalized snapshots
are never edited. PostgreSQL triggers additionally reject updates/deletes to
published statutory profiles, published salary structures/components and
structure-version snapshots, posted/paid runs, finalized payslips/lines, and
accumulator rows. Effective-dated statutory profiles, published salary
structures, and employee payroll profiles have database overlap guards.

## Bank and state exports

The canonical payout object is:

```json
{
  "batch_reference": "PR-202608-001",
  "sequence": 1,
  "execution_date": "2026-08-31",
  "debit_account": "employer-bank-account-reference",
  "employee_reference": "123",
  "recipient_name": "Employee",
  "bank_code": "KHAN",
  "bic": "KHAN",
  "account_number": "encrypted-source-decrypted-only-at-render",
  "amount": "1234567.89",
  "currency": "MNT",
  "purpose": "Salary 2026-08",
  "reference": "PR-202608-001-123"
}
```

`payroll_bank_export_profiles` maps canonical keys to versioned CSV/JSON
columns, delimiter, encoding, line endings, date/decimal formats (including
decimal keys/places), preamble/header,
trailer rows, and filename. The generation response contains only an encrypted,
short-lived artifact handle; decrypted account values are streamed only through
the authenticated download route. Draft, provisional KHAN, GOLOMT, and XACBANK presets
are seeded with canonical columns; they remain unpublished until bank-issued
samples pass golden-file comparison.

НД-7 is generated as employer/fund totals (including each configured
`payer:insurance_fund` bucket); НД-8 is generated per employee with insured
code, payable days, insurable earnings, SHI base, and employee/employer fund
amounts. Monthly PIT source totals and selectable `period=quarter` or
`period=annual` ТТ-11 summary/annex rows include employment income, employee
SHI deduction, taxable income, relief, and PIT withheld. Canonical JSON is always available; CSV/XLSX
rendering is template-driven and never embeds statutory columns in calculator
code.

The workbook's ХЧТАТ temporary-incapacity register and maternity benefit
register are claim-based Social Insurance Fund workflows. They remain owned by
the Tax Benefits workspace and the external fund process; this payroll module
does not add duplicate payroll-run reports for them. Approved vacation records
and eligible frozen payslip history feed leave-pay calculations. The workbook's
“Листний мөнгө” column is intentionally excluded because its settlement meaning
is unresolved and the Pay stage already records partial settlements.

## Retired tax and benefits workspace (historical schema)

The former `/erp/payroll/tax-benefits` workspace adapted Frappe HR's Tax & Benefits
separation into the Mongolia calculator instead of copying India-specific tax
rules. Administrators define effective exemption categories as either taxable
income deductions or PIT credits. Employees submit annual declarations and
proof references; only reviewer-approved declarations and proofs are consumed,
with declared and category limits enforced. Applied totals and source IDs are
frozen into each payslip input snapshot.

Flexible benefits are enabled on earning components in a draft salary
structure. An employee applies against the assigned component's annual limit,
then submits claims up to the approved allocation. Approved claim-based
benefits are row-locked and reserved by the matching payroll period during
calculation, emitted as auditable payslip lines, and marked paid in the same
transaction as GL posting. `only_tax_impact` benefits increase taxable income
without increasing gross or net pay. This follows the workflow boundaries in
the [Frappe HR Tax & Benefits workspace](https://github.com/frappe/hrms/blob/develop/hrms/payroll/workspace/tax_%26_benefits/tax_%26_benefits.json)
and [Payroll Setup documentation](https://docs.frappe.io/hr/payroll-setup),
while statutory rates remain organization-controlled Mongolia configuration.

## API and security

Routes are under `/v1/erp/payroll`: profiles, salary structures, employee
profiles/bank accounts, posting and bank-template administration, Frappe-style
period/component/assignment/additional-salary/payroll-entry/salary-slip/bank-entry
documents, salary register and bank remittance reports, the legacy run lifecycle
(`create`, `calculate`, `approve`, `post`, `reverse`, `replace`), bank
exports/downloads, and `me/payslips`. Payroll permissions are separate from
module visibility. Every mutating route is tenant-scoped and audited; employees
can only read finalized, non-cancelled payslips belonging to their linked
employee record.
Export-generation and download events record only masked identifiers and
checksums; encrypted artifacts expire after a short interval.

## Unified Payroll v2 write path

Unified v2 is the write path for the accounting-integrated workflow. The Dashboard and Setup
Hub use `/runs`, `/runs/preflight`, versioned setup resources, payment
allocations, and contextual reports; the frontend never requests the legacy
Frappe execution endpoints. A run advances only forward from `draft` through
calculation, ordered approvals, posting, settlement, and payslip release.
Calculation freezes the employee/profile/structure/component snapshots,
attendance and compensation inputs, statutory configuration, totals, and
checksum. Published structures and statutory profiles are immutable; bump
version creates an effective-dated successor and records supersession without
altering the predecessor payload.

Component deletion is dependency-aware through the usage endpoint. Referenced
financial fields are locked while display names/descriptions remain editable;
archive or clone is the safe alternative. Payment allocation reversals are
append-only records linked to the original and reversing ERP documents, and a
settled accrual cannot be reversed until every settled allocation has evidenced
reversal. Legacy `/payroll-entries` writes return `410 Gone` with a successor
`/runs` route. Legacy records remain available only through read-only audit
list/detail APIs and are excluded from default unified-v2 queries.

## Run-based monthly payroll

The run-based design in `PAYROLL MODULE DESIGN PLAN.MD` is available under
`/v1/erp/payroll/monthly`. It reuses the shared Employee identity, monthly HR
payroll profiles, effective-dated salary history, effective statutory rule
sets, organization calendar, and payroll capabilities. It stores a month
snapshot, separate advance/final runs, editable worker rows, field audit
events, and immutable versioned close archives. Calculations call the pure
`monthly_engine` implementation used by the HR estimate.

Confirmed HR attendance minutes are imported into monthly rows when a run is
created; the selected calendar determines normal versus overtime buckets.
Rows remain editable in draft, all rows are recalculated before approval, and
final runs capture approved advances when created. `Урьдчилгаа дахин татах`
refreshes that snapshot. Company overtime/injury settings and the workday,
weekend, and holiday calendar are editable before a month is snapshotted.
Worker payout accounts are encrypted into each row at creation, so later bank
account changes do not rewrite the run's remittance list.

Approved runs can be exported to Excel and marked paid. Advance exports include
the register and payment list; final exports include the salary table, closing
summary, overtime, contribution breakdown, payment list, and other deductions.
Six report presets cover salary register, tax and insurance with year-to-date
totals, overtime, department cost, advance versus final, and other deductions.
Closed-month reports read the latest immutable archive; archived months have a
read-only run register, and employee payroll history can be viewed and exported
across closed months. Closing requires an
approved final run and no unapproved advance run; previewed closing statistics
are archived with every run and audit row. Administrators can unlock with a
reason while earlier archive versions stay readable.

### Review behaviour (2026-09 gap closure)

- **Approval.** «Бүгдийг батлах» approves every row without a blocking issue and
  reports the rest; the run becomes Approved only when every row is. Rows and
  unpaid runs can be unapproved («Батлалт цуцлах»); editing an approved row returns
  it to draft. Paid toggles both ways while the month is open. An administrator can
  reopen an approved or paid run with a reason.
- **Advances.** FIXED and PERCENT advances are per-pay-day instalments; only
  WORKED-TO-DATE nets earlier approved advances. Pay days beyond month end clamp to
  the last day. «Урьдчилгаа бодоогүй» is a warning; «Урьдчилгаа өөрчлөгдсөн» blocks
  the row and is flagged as soon as an advance run enters or leaves approval.
  «Ажилтан нэмэх» adds a one-off advance to an existing advance run.
- **HR changes.** «Ажилчид шинэчлэх» adds newly due workers and parks changed HR
  profiles on existing rows as «HR changed»; nothing is overwritten until the
  accountant accepts the change on that row.
- **Employment window.** Salary segments are limited to the days employed in the
  month, so a mid-month hire or leaver on a FIXED salary is prorated by working days.
- **Overtime explanation.** `overtime_day_lines` (engine) turns each overtime cell
  into dated lines at the engine's rate; the register info box, the drawer and the
  «Илүү цаг» export sheet all read these lines, and they always sum to the cell.
- **Close.** An unapproved advance run can be waived with a reason at close; it
  stays draft and uncounted, and the archive records the waiver. A closed month is
  read-only for every run. Unlock returns runs to Approved/Paid.
- **Exports.** `monthly_exports.build_run_workbook` produces the §12 workbooks: the
  Excel-ordered final register with grouped headers, department SUBTOTAL rows and
  footnote, the «Дүн» sheet with accounts A/B/C and department split, overtime, SHI
  split, payment list grouped by pay day, and other deductions.
- **Organizations without rules** get the seeded 2026 rule set on first use.

Verification: `tests/test_payroll_monthly_workflow_db.py` drives the full §18 flow
through the API against a disposable PostgreSQL when `PAYROLL_TEST_DATABASE_URL` is
set (it creates only the payroll tables, so pgvector is not required).

The monthly flow is separate from unified v2's ledger posting and payment
allocation workflow. Direct bank integration and automatic HR leave-pay
synchronization remain follow-up work. It does not change the unified-v2
`/runs` lifecycle or existing run records.

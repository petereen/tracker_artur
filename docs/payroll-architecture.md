# OYUNS Mongolia payroll architecture

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

The Alembic revision `f0a1b2c3d4e5_mongolia_payroll.py` is the executable DDL.
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

## API and security

Routes are under `/v1/erp/payroll`: profiles, salary structures, employee
profiles/bank accounts, posting and bank-template administration, run lifecycle
(`create`, `calculate`, `approve`, `post`, `reverse`, `replace`), payslip reads,
bank exports/downloads, and `me/payslips`. Run lifecycle exposes explicit
`calculate`, `review`, `approve`, and `post` actions. Payroll permissions are separate from module
visibility. Every mutating route is tenant-scoped and audited; employees can
only read finalized payslips belonging to their linked employee record.
Export-generation and download events record only masked identifiers and
checksums; encrypted artifacts expire after a short interval.

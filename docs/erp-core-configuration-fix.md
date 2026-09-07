# ERP core configuration fix: Payroll first

Audit date: 2026-09-07. Scope: local repository, existing tests, and official Frappe HR/ERPNext documentation. This is a configuration and implementation plan, not a claim that the deployed tenant has been repaired. No production data, payments, configuration, or application source were changed.

The repository is a custom React/FastAPI/PostgreSQL ERP with Frappe-inspired payroll documents. Use Frappe HR as a workflow reference; its settings and DocTypes are not automatically available here. Retain the existing calculation engine and document history while closing the gaps below.

The first usable core is **Employee/HR + Payroll + minimum Accounting**. Selling, Buying, Stock, CRM, Support, Manufacturing, and Assets & Maintenance are not payroll prerequisites. Their dedicated forms and workflows follow the first successful payroll close.

## Payroll workflow fix

### 1. Restore a complete setup path before creating another run

**Owner:** Payroll administrator and implementation team. **Type:** configuration plus required UI fixes.

Provide a setup checklist with a named owner and a direct fix link for each missing item: company, payroll policy, statutory profile, employees, components, published structure, assignments, payment details, and Accounting mappings. Show separate readiness for calculation, accrual, payment, and reconciliation. Missing bank details should be visible early; mandatory posting accounts must be complete before salary submission.

The current setup has concrete dead ends:

| Observed source behavior | Required fix | Evidence |
| --- | --- | --- |
| The new Salary Structures screen creates a draft and renders a status badge, but offers no edit/publish action. Assignment requires a published structure. | Add edit, preview, publish, and create-new-version actions. Keep published versions immutable. | `frontend/src/pages/PayrollWorkspacePage.tsx:477`; `backend/app/payroll/service.py:339` |
| Statutory profile editors and employee payroll/bank setup exist in the legacy workspace, while admin/HR routes lead to the new workspace. | Expose these existing capabilities through dedicated Settings and Employee forms. Do not require users to find a legacy route. | `frontend/src/pages/PayrollWorkspacePage.tsx:182`, `:545` |
| Component creation forces no proration, no account, and employee payer; Additional Salary creation forces taxable and SHI-subject flags. | Add conditional fields; inherit the chosen component's calculation/tax settings and validate them server-side. Include employer-cost behavior. | `frontend/src/pages/PayrollWorkspacePage.tsx:464`, `:505`; `backend/app/payroll/frappe_service.py:195` |
| The entry creation service does not preserve `validate_attendance`; the detail form starts with empty employee filters and attendance enabled. | Persist and restore the selected policy, employee IDs, and filters across save, refresh, and Get Employees. | `backend/app/payroll/frappe_service.py:230`; `frontend/src/pages/PayrollWorkspacePage.tsx:397`, `:417` |
| Get Employees returns errors, but the entry GET response omits the `employee_selection` object that the UI expects. Once employees exist, the UI hides Get Employees. | Persist/return actionable per-employee results; offer Recheck after correcting data while the run is editable. | `backend/app/payroll/router.py:666`, `:678`; `frontend/src/pages/PayrollWorkspacePage.tsx:440` |

Acceptance: an authorized HR operator can complete setup, publish a structure, assign a worker, add a bank account, correct a missing prerequisite, and refresh the checklist entirely through normal screens.

### 2. Establish one Employee master and specialized salary setup

**Owner:** HR for employment data; Payroll for compensation; Finance for mappings.

| Record | Minimum working fields | Required functions |
| --- | --- | --- |
| Employee | Employee number, legal name, organization, status, joining/leaving dates, department, employment type, work calendar | Create/edit employee, assign manager/calendar, activate or end employment; link an optional login |
| Payroll details | Employee link, statutory category, residency, required tax/insurance identifiers, payment method | Validate missing data and effective dates; restrict confidential fields |
| Employee bank account | Bank, account/IBAN as required by the selected bank, account holder, effective dates, primary flag | Validate, mask, replace with history, select for payout |
| Salary Component | Name, earning/deduction/employer-cost category, fixed amount or formula, payment-day dependency, tax/insurance treatment | Preview calculation; optional advanced formula and account mapping; archive unused master |
| Salary Structure | Name, effective dates, currency, ordered component rows | Save draft, preview sample employee, publish immutable version, clone revision |
| Structure Assignment | Employee, published structure, base salary, effective-from/to | Individual/bulk assignment, salary revision with no overlapping dates |
| Additional Salary | Employee, component, amount, payroll date, reason/reference | Draft, approve, consume once, show originating compensation/claim record |

Use one default monthly structure initially. Store base salary on the effective-dated assignment, not by creating a new structure per employee. Frappe HR similarly separates reusable salary structures from employee assignments. [Salary Structure Assignment](https://docs.frappe.io/hr/salary-structure-assignment)

Fix the current ownership mismatch: HR supports employees before they have logins, but `create_employee_profile` authorizes ownership through an active/invited `UserAccount`. Resolve ownership from the canonical organization-scoped Employee record, preserving tenant validation; a login must not be a payroll prerequisite.

Configure the organization's approved statutory profile with effective dates, withholding method, insurance categories, relief rules, rounding, and source references. The current engine/form scope is monthly MNT. Do not imply support for another currency/frequency without implementing and testing it. No statutory rates are prescribed by this audit; validate the actual operating jurisdiction and period-specific configuration with Finance.

Assignments must support closing an old version and opening a revision. Copy or explicitly revalidate bank details when an assignment changes: bank accounts currently belong to `EmployeePayrollProfile`, so a salary revision can otherwise lose payment readiness.

### 3. Make attendance, leave, and recurring pay feed every Payroll Entry consistently

**Owner:** HR/attendance approver and implementation team. **Type:** integration fix plus policy configuration.

Choose an explicit calculation policy per payroll population: attendance-based, approved-leave-based, or approved-hours-based. Configure the workweek, holiday list, missing-attendance behavior, half-day fraction, paid/unpaid leave rules, and joining/leaving-date proration. This distinction follows Frappe HR's working-day configuration. [Payroll Settings](https://docs.frappe.io/hr/payroll-settings)

Current inconsistencies:

- `get_employees` checks for at least one approved `WorkTimeEntry`, not complete approved HR `AttendanceLog` coverage. A green HR attendance register can still fail Payroll validation.
- `calculate_run` defaults to Monday–Friday and derives payment days from approved worktime dates. The presence of those dates changes the fallback that subtracts unpaid leave. There is no shared payroll-day reconciliation of holidays, paid leave, employment dates, and unmarked attendance.
- The HR Generate Payroll route adds approved unpaid leave and recurring compensation; direct Payroll Entry creation does not use that preparation path. The same employee/month can therefore have different inputs depending on where the run begins.
- Employee selection requires currently active employees and an assignment effective on the tax point date. Explicitly handle employees who left during the earning period and mid-period salary changes.

Create one input builder used by both HR and Payroll. It should:

1. Resolve eligible employment dates and effective salary assignments.
2. Build scheduled days/hours from the employee calendar in the company timezone.
3. Merge confirmed attendance and approved leave per date; count a given unpaid day once, even if attendance and leave both identify it.
4. Include paid leave correctly; apply the approved half-day and missing-record policy.
5. Bring in approved recurring and one-time pay once, retaining source references.
6. Freeze dates, approvals, amounts, policy versions, and source IDs when creating slips. Show why each payment day or adjustment was included.

Base-salary proration should apply only to components marked as dependent on payment days. Missing attendance is a named exception with a fix action, not an invisible assumption. Use local date formatting in the frontend: converting local month boundaries with `toISOString()` can shift the selected date in Ulaanbaatar.

Acceptance: a full-attendance employee, paid-leave employee, unpaid-leave employee, half-day worker, new joiner, and departing worker produce explainable payment days. HR-generated and Payroll-generated runs have identical inputs for the same scope.

### 4. Use one reviewable monthly run

**Owner:** Payroll preparer → independent payroll approver → Finance.

Recommended user flow:

```mermaid
flowchart LR
  A[Select period and employees] --> B[Check inputs]
  B --> C[Generate draft slips]
  C --> D[Review and approve]
  D --> E[Post salary accrual]
  E --> F[Prepare and record payment]
  F --> G[Confirm settlement]
  G --> H[Reconcile bank statement]
```

Before **Post salary accrual**, complete the Accounting setup in steps 6–8. The presentation starts with Payroll, but Accounting is a prerequisite to posting.

The run form needs period, posting date, payment/tax-point date, employee group, and the selected attendance policy. Fetch company, currency, structure, and default cost center automatically. Show employee count, gross earnings, deductions, net pay, employer contributions, and exceptions. Keep net pay and total employer cost distinct; the current dashboard labels a sum of net pay as payroll expense (`PayrollWorkspacePage.tsx:377–379`).

Review each employee's slip, compare with the previous comparable period, explain large variances, then approve. Repeated clicks must reuse the same slips/posting/payment; corrections require an explicit recalculation of editable drafts or a linked reversal/replacement after posting. Freeze and check the posting mappings actually used. Never silently recalculate previously released salaries.

Add a real approval gate to the new lifecycle. Currently `frappe_v1` posts directly from calculated status and automatically publishes employee payslips (`service.py:617`; `frappe_service.py:350`). A successful submit call is not evidence of independent review. Make payslip release an explicit authorized action; a released slip may correctly say payment is pending.

Keep the Frappe-inspired bulk accrual boundary: submitting the reviewed batch creates the salary expense/payable journal. The official workflow separates that accrual from the later Bank Entry. [Payroll Entry](https://docs.frappe.io/hr/payroll-entry)

### 5. Finish Bank Entry, settlement, and reconciliation

**Owner:** Treasury/Finance. **Type:** missing workflow and accounting integration.

Create a dedicated Payments screen linked from the payroll run. Required fields: source run/slips, company bank account, payment date, amount, currency, bank reference/date, employee allocations, and settlement status. Provide a versioned bank export only after validating the selected bank's current layout.

Maintain separate concepts:

- **Accrued:** salary liability exists.
- **Payment recorded:** a submitted payment voucher exists; creating/exporting it does not transfer money.
- **Bank confirmed:** accepted/settled employee amounts have evidence; rejected amounts remain due.
- **Reconciled:** bank statement lines are allocated to the existing payment vouchers, with clearance dates and no unexplained difference.

Current `submit_bank_entry` writes two GL rows and immediately sets the entire run to `paid`. The model/API has no reference fields in `BankEntryInput`, the payment is for the full run, and no bank-statement matching implementation was found in the audited Payroll/ERP paths. It also does not update the original payroll document's outstanding amount through a payment-allocation workflow. These require code changes, not a module switch.

Support partial payments, failed transfers, retries, employee-level allocation, cash payments where permitted, and cancellation/reversal of actual payment vouchers. Keep accepted employees out of a retry batch. A submitted bank payment must not vanish when the related payroll accrual is cancelled. Advances need their own tested flow: current advance submission posts against bank immediately and bypasses the separate Bank Entry sequence.

Import a bank statement with transaction identifiers and duplicate detection. Match existing payments by account, currency, amount, date, and reference; support an aggregated debit covering multiple payroll payments. Keep bank fees separate from salary amounts. Unmatched items stay in an exception queue. Do not create a second payment/GL entry when matching an already recorded transfer. ERPNext also treats bank reconciliation as matching statement transactions with vouchers. [Bank Reconciliation](https://docs.frappe.io/erpnext/bank-reconciliation)

Acceptance: after full settlement, payroll net payable for that batch is zero; statutory liabilities remain until remitted. Statement balances reconcile, partial/rejected payments remain visible, and retries cannot pay accepted employees twice.

## Essential Accounting dependency setup

### 6. Configure company and accounting controls

**Owner:** Finance. Enable Accounting for Finance and setup administrators alongside Payroll; ordinary employees need neither Accounting navigation nor ledger access.

Set the legal company, base currency, fiscal year, timezone, open posting period, default cost center, bank account, and document numbering. Establish the payroll conversion date and reconcile opening bank, unpaid salary, advance, and statutory balances to the previous records. Import employee year-to-date pay/withholding when required by the configured cumulative calculation; opening GL balances alone do not provide individual tax history.

Use the existing Chart of Accounts; add missing ledger accounts rather than replacing it. Disable obsolete unused accounts only after checking defaults/history. Group accounts organize the hierarchy; posting must target non-group ledgers. [Chart of Accounts](https://docs.frappe.io/erpnext/chart-of-accounts)

### 7. Create the minimum payroll accounts and map them

Use company-specific account numbers; the names below describe purpose. Seven ledgers cover ordinary monthly payroll with employee and employer insurance and income-tax withholding in the current implementation.

| Account | Classification | Current posting role |
| --- | --- | --- |
| Salaries and wages expense | Expense | `salary_expense` |
| Employer social-insurance expense | Expense | `employer_shi_expense` |
| Net salaries payable | Liability | `net_pay_payable` |
| Employee social insurance payable | Liability | `employee_shi_payable` |
| Employer social insurance payable | Liability | `employer_shi_payable` |
| Employee income tax payable | Liability | `pit_payable` |
| Company payroll bank ledger | Asset / bank | `bank`, plus the actual Bank Entry payment account |

Add only when used: employee advances/receivables (`advance_clearing`), other deduction payables (`other_deductions_payable`), separate allowance expenses, cash, bank charges, and insurance-fund subaccounts. Preserve existing balances and use an approved balanced opening journal for migration.

Create one active default cost center initially, then departments when useful. Frappe supports cost-center allocation without multiplying expense accounts. [Cost Center](https://docs.frappe.io/erpnext/cost-center)

Save the mappings at **Payroll → Account mapping**, backed by `/v1/erp/payroll/posting-profiles/default`. Expand the mapping form conditionally for advances/other deductions. The current seed accounts omit several statutory/employer accounts, so seeded Accounting is not a complete Payroll configuration.

Required implementation controls:

- Filter and validate organization, active status, non-group status, account purpose, and currency at save and post time. The current account schema has no dedicated `bank` account type; add a bank-purpose classification/link rather than offering every ledger as a payment account.
- Apply the posting-period guard to payroll accrual and Bank Entry. Both currently write GL directly and bypass the guard used by generic ERP posting.
- Honor the approved posting date. Payroll accrual currently writes `run.period_end` despite the entry collecting a separate posting date.
- Resolve cost-center defaults consistently and include employer costs. The run's cost center must affect ledger rows; merely storing it on the run is insufficient.
- Snapshot account mappings on approval/posting, including the payable account later cleared by payment. Changing the default mapping between accrual and payment must not clear a different liability.

### 8. Verify journals and provide real Accounting forms

Illustrative arithmetic only, in arbitrary currency units, with no prescribed statutory rates:

| Event | Debit | Credit |
| --- | --- | --- |
| Accrue gross 100 and employer insurance 10 | Salary expense 100; employer insurance expense 10 | Net salaries payable 80; employee insurance payable 10; income tax payable 10; employer insurance payable 10 |
| Record net salary payment 80 | Net salaries payable 80 | Bank 80 |
| Remit the example insurance/tax liabilities 30 | Employee insurance payable 10; employer insurance payable 10; income tax payable 10 | Bank 30 |

Each journal balances. Net pay is 80; employer cost is 110. A statement match links to these payments and does not book salary expense again. With a partial salary payment of 50, net salary payable remains 30 until settled.

Replace the universal quantity/rate/tax editor with:

| Accounting form | Working fields | Functions |
| --- | --- | --- |
| Chart account | Code, name, classification/purpose, parent, currency, active/group | Create, validate, archive unused ledger |
| Cost center | Code, name, company, parent, active | Select default, allocate expense |
| Journal | Posting date, account rows, debit, credit, cost center, reference, memo | Validate balance, approve/post, reverse, inspect ledger |
| Payment | Payee/source obligation, bank/cash account, date, amount, allocations, reference | Prepare, approve, record, track outstanding, reverse |
| Bank reconciliation | Bank account, statement dates/balances, transaction reference/date/amount, voucher allocation | Import/deduplicate, match, investigate, reconcile |

The existing generic `ERPWorkspacePage` always supplies commercial line items. A journal needs debit/credit rows; a payment needs allocations. Use dedicated components and server validation even if the database continues sharing infrastructure.

## Navigation, roles, and the remaining modules

### 9. Simplify navigation and enforce permissions consistently

Payroll navigation: **Overview · Run payroll · Employees · Reports · Settings**. Put reusable components, structures, statutory rules, assignments, calendars, and account mappings under Settings or the relevant Employee form. Keep common monthly actions on the run page. Provide one primary next action plus a clear reason when it cannot proceed.

Use one language per session with consistent business labels. Keep internal identifiers, formula traces, snapshot checksums, and migration terminology in restricted technical/audit details. Use the existing visual design system and readable tabular numbers; emphasize the pay period, outstanding exceptions, and next action. Place optional branch, designation, project, advanced formula, and localization fields behind progressive disclosure. Show loading and permission failures explicitly instead of an empty list.

Move module switches, role configuration, and form/workflow builders into Administration. Show only usable, authorized modules in normal navigation. Module switches currently control visibility only; backend capability checks remain necessary.

Remove redundant entry points, not transaction history: route HR compensation and Employee pay actions into the same effective-dated data; link Bank Entries to the Payments screen; route generic payroll creation to the dedicated workflow. Archive legacy setup and preserve old runs, slips, journals, and compatibility links. Do not delete referenced models/tables to reduce navigation clutter.

| Role | Allowed work | Restricted work |
| --- | --- | --- |
| Employee | Own profile, leave requests, released payslips | Other salaries, bank export, company ledgers |
| Manager | Team attendance and leave decisions | Team salary/bank data unless separately authorized |
| HR officer | Employee/employment master, approved leave/attendance corrections | Payment execution and Accounting configuration |
| Payroll preparer | Components/assignments within granted scope, draft runs and corrections | Approving own payroll or posting bank payments |
| Payroll approver | Review payroll/register, approve or return with reason | Editing an approved snapshot |
| Accountant | Account mappings, accrual posting, liability reports | Unnecessary personal bank/tax data and payroll-master edits |
| Treasury | Approved payout allocations, bank export, payment confirmation/reconciliation | Changing salary calculations |
| Administrator | Company setup, roles, audited support access | Routine use as the universal payroll approver |

Enforce organization, team, employee, field, and action scopes in APIs and exports as well as screens. Smaller organizations can combine responsibilities intentionally, while retaining independent approval of payment.

Current corrections needed: `canManagePayroll` admits managers while the backend rejects manager-only payroll access; custom accountant roles do not map cleanly to the UI's admin/manager/HR test; all three salary submission/bank actions use `payroll.post`; and the generic manager compatibility bridge grants broad view/create/edit access outside the dedicated Payroll wrapper. Replace these with explicit capabilities and consistently scoped queries, including dashboards and ledger/export endpoints.

### 10. Give each remaining module a specialized workflow

This is the target field/function contract, not a claim that these workflows already work. Share company, party, item, account, and employee identifiers while giving each module its own forms, validations, and states. Enable a module when its required business journey passes acceptance.

| Module | Minimal specialized fields | First complete workflow | Dependencies |
| --- | --- | --- | --- |
| Selling | Customer, item/service, quantity/UOM, price, delivery date, invoice due date | Quotation → order → delivery if needed → invoice → receipt allocation | Accounting for invoices/payments; Stock only for stocked goods; CRM optional |
| Buying | Supplier, item/service, quantity/UOM, agreed price, expected receipt, supplier invoice reference | Purchase order → receipt if needed → supplier bill → payment | Accounting; Stock only for inventory purchases |
| Stock | Item/SKU, warehouse, UOM, quantity, movement type, valuation | Receive → transfer/issue → count → adjustment with stock ledger | Items/UOM/warehouses; Accounting for valuation; Buying/Selling integrations when used |
| CRM | Contact/company, owner, stage, expected value, next follow-up date | Lead → qualified opportunity → customer/quotation handoff | Company/users; Selling only at handoff |
| Support | Requester, subject, description, priority, assignee, due/SLA target | Ticket → assignment → response → resolution/reopen | Company/users and contacts; Selling optional |
| Manufacturing | Finished item, BOM components/quantities, planned quantity, operations, warehouse, work-order status | BOM → work order → material issue → job completion → finished-goods receipt | Stock/items/UOM; Accounting for WIP/production cost; Buying when replenishing |
| Assets & Maintenance | Asset tag, category, acquisition date/value, location/custodian, useful life/depreciation policy; maintenance task/due date | Acquire/register → assign → depreciate → maintain → dispose | Accounting; Buying for procurement; Stock only if the chosen receiving flow uses it |

Recommended rollout after Payroll: Selling/Buying with Accounting, then Stock if goods are tracked; CRM and Support as needed; Manufacturing after Stock and cost accounting; Assets & Maintenance when asset control is required. Avoid asking CRM or Support users to enter quantity, rate, tax, or journal rows.

## Acceptance and execution order

### 11. Close the milestone with evidence

Implementation order: restore setup and employee ownership → unify payroll inputs and validation → configure Accounting and enforce posting guards → review/accrual → payment/reconciliation → role-based acceptance. Navigation/form work accompanies the corresponding workflow. Other modules follow Payroll acceptance.

Run a migrated staging copy with an approved expected-results fixture covering:

1. Complete setup using only normal HR/Payroll/Finance screens; refresh and resume every stage.
2. Full month, paid leave, unpaid leave, half-day, missing attendance, holidays, timezone boundaries, joining/leaving, salary revision, bonus/deduction, and advance/final settlement.
3. Gross, payment days, insurance, tax, net, and year-to-date totals; independent draft/future runs must not contaminate finalized-period calculations. The current YTD queries include calculated/review/approved runs, so specifically verify inclusion rules and reversals.
4. Balanced accrual, correct cost center and posting date, rejected closed-period/group/wrong-purpose account postings, and an unchanged payable mapping between accrual and settlement.
5. Bank export, full/partial/rejected payments, idempotent retry, duplicate statement import, aggregated statement matching, bank fees, and zero unexplained reconciliation difference.
6. Employee self-service and confidentiality; manager/HR/Payroll/Finance/Treasury permissions; direct unauthorized API/export access and cross-organization identifiers.
7. Concurrent generation/submission, linked cancellation/reversal/replacement, preserved released snapshots, and successful migration/restore rehearsal.

Record preparer, approver, posting document, payment reference, matched statement line, and any unresolved amount. The acceptance gate is one fully reconciled payroll period plus those failure cases, not the existence of module cards or a successful frontend build.

### Audit validation baseline

`TODO.md` initially contained 736 checked items and 22 pending items, including unresolved backend and migration validation. Checked implementation work is not evidence that the deployed workflow is accepted; retain that history and track the newly identified fixes separately.

- Focused frontend Payroll/ERP tests: **2 files, 6 tests passed**. These are limited policy/helper checks, not a complete browser payroll journey.
- `backend/tests/test_frappe_payroll_contract.py`: **3 passed, 1 failed**, on the expected literal migration text `UPDATE payroll_runs SET document_status`. This is a source-contract mismatch; it does not by itself prove a broken migration.
- Combined payroll-sequence and Alembic-graph test collection: blocked by missing FastAPI and Alembic packages. SQLAlchemy and asyncpg are also absent in the checked Python environment. Pytest itself is available, unlike older tracker notes.
- No Payroll-specific browser test file was found under `frontend/e2e`. Production employee data, statutory values, deployed schema revision, actual bank layouts, and live bank settlement were not verified.

Keep the implementation and live configuration tasks unchecked until their corresponding outcome is verified. This audit and plan are the completed deliverables for this request.

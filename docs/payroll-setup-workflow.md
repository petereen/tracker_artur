# Payroll setup and unified v2 run workflow

## Object model and ordering

Payroll uses the HR employee as its worker master. A salary structure contains salary component snapshots. An employee payroll profile assigns a published, effective salary structure and base salary to a worker. A separate employee bank account supplies payment details. Statutory profiles, work policies, Payroll Periods, and the default posting profile are shared configuration. Unified v2 runs require an open Payroll Period and use its statutory profile.

| Step | Owner | Required result | Next action |
| --- | --- | --- | --- |
| Workers | HR | Active worker with employment dates, department, and work calendar | Open the HR worker record |
| Salary components | Payroll setup | Active earning, deduction, or employer cost with formula, tax treatment, proration, and an optional tagged expense account | Create or revise a component |
| Salary structures | Payroll setup | Published effective version containing the required components | Preview, publish, or clone a structure |
| Assignments and payment details | Payroll setup | Effective worker profile with published structure, salary, payment method, and primary bank account when bank paid | Open the worker's assignment drawer |
| Rules and finance | Payroll and Finance | Published statutory profile and work policy; open Payroll Period; existing chart accounts tagged for payroll purposes | Publish rules, open a period, or tag and map accounts |
| Cycle inputs | HR and Payroll | Approved attendance and leave, submitted Additional Salary, applicable tax and benefit claims | Resolve cycle inputs |
| Run and approve | Payroll and ordered approvers | Fresh preflight, frozen calculation, resolved reconciliation errors, three distinct approvals | Calculate, review, approve |
| Pay, release, reconcile | Finance and authorized releaser | Balanced accrual, bank submission, real settlement references, released slips, matched statement lines | Prepare, submit, settle, release, match |

The main path is monthly MNT. Advance Clearing is only required when an advance or offset creates a clearing line. Posting requires mappings only for nonzero journal lines in the calculated run. Bank export and report layouts are optional Finance configuration; a bank export layout needs an exact bank sample comparison before publication.

## Current-state problems addressed

The former setup order placed structures before their component masters and employees before publishable structures. The setup hub now follows the dependency order and uses a worker-specific assignment action. Payroll Period has been removed from the unified v2 setup path. Tax category editing is under Rules; declarations and claims remain in Tax & Benefits. Additional Salary appears under cycle inputs. Optional bank and report layouts sit behind an advanced Finance section.

Preflight now points to the screen where each issue can be fixed. It checks explicit employee scope and tenant, effective profiles and structures, and tagged account mappings that are already configured. The final posting check uses the actual balanced journal generated from the calculated run. Employee profile resolution uses the same tax point in preflight and calculation. Changing run scope clears the earlier preflight, and creation repeats it on the server. Replacement runs allow scope edits before the new run is frozen.

The run screen shows reconciliation issues and their resolution action, with capability-based review and posting controls. Payment batches load allocation detail after refresh. The screen covers bank submission, rejection and retry, settlement with a real reference, release after full settlement, and statement line matching. Older salary slip and report routes reach their corresponding v2 views.

## Usability and validation

- Setup navigation shows the dependency order and a readiness checklist with issue codes and direct actions. Worker assignment status uses the currently effective profile and structure.
- Run dates, employee filters, and replacement scope remain editable until creation. Invalid date order blocks preflight with an inline error. Async preflight, reconciliation, reports, and statement matching announce their state.
- The calculation button explains and requires acknowledgement when the chosen statutory profile is an example. Locked actions show the missing permission or preceding stage.
- A posted run cannot be recalculated. Published structures and historical calculation snapshots remain immutable; revisions use new effective-dated versions.
- Payroll selectors only offer active, non-group MNT accounts tagged for the relevant role. Accounts are created in the ERP Chart of Accounts; Payroll Setup only edits purpose tags and posting mappings.

## Edge-case verification

1. Revise a component after assignment: clone its version and the structure, publish prospectively, then revise worker assignments. Verify old payslip checksums and totals do not change.
2. Join, leave, or revise salary mid-cycle: verify the chosen tax point selects the intended effective profile, while approved time and leave still cover the run period.
3. Expire a primary bank account, leave a component expense account unmapped, or deactivate a posting account: preflight identifies known setup issues, and calculated posting/payment independently enforce the roles their actual journal uses.
4. Leave attendance or Additional Salary in draft: preflight must identify the record; an explicit attendance waiver must surface as a warning.
5. Settle only part of an employee payment or only some employees, then prepare a batch for the unpaid remainder. Reject or reverse one allocation and retry only that amount. Require a distinct bank reference for every settled allocation; duplicate submission must be idempotent or rejected.
6. Import a statement line with the wrong account, amount, or reference: matching must reject it. Match each valid settled allocation at most once. Reversing a matched allocation must reopen its statement line.
7. Test create, review, ordered approvals, posting, payment, release, report export, and employee self-service with separate roles and tenants. A worker must see only their own released slips.

## Acceptance gate

Run a migrated PostgreSQL staging cycle through the normal browser screens and refresh at every stage. Verify balanced accrual and payment ledger entries, actual bank references, all statement lines matched, and released employee slips. Local source-contract tests and frontend component tests do not replace this staging gate.

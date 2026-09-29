# Budget module (Төсөв, гүйцэтгэл)

Built from Dayansoft ERP d161 “Төсөв, гүйцэтгэл” (`docs/Dayansoft MD/docs.dayansoft.mn_erp_budget_d161…md`, https://docs.dayansoft.mn/erp/budget/d161). The management cycle it supports: **plan → budget → actual → comparison → decision**.

## Shape

| Layer | Where |
|---|---|
| Budget account groups (Төсөвт данс бүлэг) | `budget_account_groups`: code, name, kind (`income` / `cogs` / `expense` / `other`), sort. Seeded once per org: Орлого, ББӨ, Үйл ажиллагааны зардал. |
| Budget accounts (Төсөвт данс) | `budget_accounts` plus `budget_account_links` → `erp_accounts`. One budget account can group several ledger accounts (60101 + 60102 → Маркетинг). **A ledger account belongs to at most one budget account** (`uq_budget_account_links_org_erp_account`), so actuals are never double counted. |
| Budgets (Төсөв) | `budgets`: number `BUD-0001`, name, purpose, scenario (`base` / `optimistic` / `conservative` / `other`), period type (`month` / `quarter` / `year` / `custom`), start/end, optional project, status `draft → approved → archived`, `is_primary`, `copied_from_id`, `version`. |
| Planned amounts | `budget_entries`: budget account × project × customer group (`erp_party_groups`) × period column, signed amount. |
| API | `app/budget/`, mounted in the ERP router at `/v1/erp/budget` (`settings.py` = capabilities/lookups/groups/accounts, `budgets.py` = CRUD/grid/workflow/copy/Excel, `analysis.py` = analysis/drill-down/export). Pure rules live in `service.py`, the Excel layout in `excel.py`. |
| UI | `/erp/budget` (list + editor at `/erp/budget/:id`), `/erp/budget/analysis`, `/erp/budget/accounts`: `frontend/src/pages/BudgetWorkspacePage.tsx`, `frontend/src/components/budget/*`, `frontend/src/api/budget.ts`. Built with Astryx. |
| Migration | `f6a7b8c9d0e1_budget_module` (after `e5f6a7b8c9d0`); also grants `budget_settings:*` to existing system Accountant roles. |

## Rules worth knowing

- **Sign convention (d161 🚨2):** income is planned positive; cost of sales (ББӨ) and expenses negative; `other` accepts any sign. Saving a grid that breaks this returns `422 budget_sign_mismatch` with the offending cells. The editor flags them and has a “Тэмдгийг засах” fix-all button. Profit = sum of everything.
- **Actuals** come from posted `erp_general_ledger_entries` on the linked ledger accounts, as `credit − debit`, which is the same sign convention. Project = `erp_documents.project_id`. Customer group = `erp_parties.group_id` of the line's party, falling back to the document's party. A budget with a header project measures only that project's transactions.
- **Байх ёстой (“should be by now”)** pro-rates each entry by day up to the as-of date (default: today in the org timezone, clipped to the window). Monthly or quarterly entries therefore carry any seasonality; a single yearly entry is linear.
- **Variance** is `actual − expected`. With the sign convention, positive always means favourable: income above plan, or spending below plan. Status: `favorable` / `on_track` (±5% of expected) / `unfavorable`; `unplanned` means there is an actual with no plan. Performance % = actual / expected.
- **Budget and actual are aggregated independently on the same keys** (account / group / kind / project / customer group / month / quarter / year; up to two keys for the pivot). A project-level line and the company-wide total therefore never double count.
- **Unmapped ledger activity:** analysis lists income/expense ledger accounts that have transactions in the window but no budget account link (the d161 checklist item “Төсөвт данс зөв холбогдсон”).
- **Workflow:** only drafts can be edited. Approving needs `budget.approve` and at least one non-zero amount. Reopen clears approval and the primary flag. **Primary (★, хүчин төгөлдөр):** only approved budgets can be primary, and at most one per overlapping period and project; setting one clears the others. Analysis defaults to the primary budget that covers today. Approved budgets cannot be deleted, only archived.
- **Period is locked once amounts exist** (`409 budget_period_locked`). Copy the budget to re-plan on a different calendar.
- **Copy (Хувилах):** creates a new draft scenario, optionally shifted by ±N years and scaled by ±% (signs kept).
- **Excel:** export writes the grid, with a hidden key row and a “Заавар” sheet. Import (drafts only) replaces the whole grid, and nothing is saved if any row fails; errors are listed by row number.
- **Kind is locked** on a budget account once budgets use it. Used accounts cannot be deleted; deactivate them instead.
- **Optimistic locking:** grid saves, header edits and workflow actions take `version`; a stale write gets `409 budget_version_conflict`.

## Authorization

This uses the ERP capability model with resources `budget` (view / create / edit / approve / archive / export) and `budget_settings` (view / create / edit / archive).

| Who | Access |
|---|---|
| Admins | Everything. |
| `manager` / `team_lead` | view / create / edit, through the existing ERP bridge. They cannot approve, archive or export. |
| Accountant role (`erp_accountant`) | `budget:*` and `budget_settings:*`. |
| Member workspace mode | Narrows roles, so the bridge no longer applies. |

The `budget` module toggle (Modules & Features) controls nav visibility only, like CRM.

## Tests

- `backend/tests/test_budget_contract.py`: periods, pro-rating, the d161 worked example (108% / 107% / 100% / 138%), sign rules, scenario copy, and the Excel round trip. No DB needed.
- `backend/tests/test_budget_db.py`: end-to-end against PostgreSQL. Runs only with `BUDGET_TEST_DATABASE_URL=postgresql+asyncpg://…/throwaway_db`.
- `frontend/src/pages/BudgetWorkspacePage.test.tsx`.

## Not built (deliberately)

- Excel import for budget groups and accounts (only the budget grid imports).
- Drill-down to the ERP document page (the generic ERP workspace has no per-document route); the drill-down shows the ledger lines.
- Cost-center / department dimension (d161 does not use it; `erp_general_ledger_entries.cost_center_id` exists if needed later).
- An OYUNS assistant tool for budgets.
- The legacy generic `budget` ERP document type is left untouched for compatibility.

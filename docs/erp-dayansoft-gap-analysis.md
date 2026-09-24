# Oyuns ERP vs Dayansoft ERP — Gap Analysis & Implementation Plan

_Prepared 2026-09-24. Sources: Dayansoft knowledge base export (docs.dayansoft.mn / dayansoft.mn, ~75 pages) and the Oyuns codebase at `master` + working tree._

## Context
We compared the Dayansoft ERP knowledge base (≈75 docs: core, main settings, finance, support, website) against the current Oyuns ERP codebase (`backend/app/erp`, `backend/app/payroll`, `backend/app/hr`, `backend/app/models/models.py`, docs/TODO). Goal: find what Oyuns lacks for Mongolian accounting compliance and operational efficiency, and define implementable requirements + a phased rollout.

**Oyuns baseline (verified in code):** multi-org tenancy; CoA (`erp_accounts`) + append-only double-entry GL (`erp_general_ledger_entries`, reversal via `reversal_of_id`); posting gate `validate_posting_gate` (balanced, open period, active non-group accounts, cost center on P&L lines) in `app/erp/service.py`; posting periods open/close (no reopen); generic documents (`erp_documents`, sales/purchase/stock/asset types, conversion, amend, cancel); AR/AP `outstanding_amount` + `erp_payment_allocations` + aging report; stock ledger + valuation layers; fixed-asset books/depreciation/disposal; RBAC (`erp_access_roles`, capabilities, scoped roles, approval thresholds); `audit_logs`, `erp_workflow_transitions`; CSV imports; monthly payroll engine (НДШ, ХХОАТ brackets/relief, overtime, advances, month close/archive) in `app/payroll/monthly_engine.py` / `monthly_workflow.py`; MongolBank rates in `exchange_rate_snapshots` (not wired to accounting).

**Blocker found:** `ERPDocument` (models.py:2570) has no `workflow_state` / `definition_version` columns, but `document_out` (service.py:903) and router.py:1272–1481 read/write them (migration `d5e6f7g8h9i0` added the DB column). Every document serialization would raise `AttributeError`. Must be fixed in Phase 0.

---

## 1. Workflow & Module Mapping

| Area | Dayansoft standard workflow | Typical ERP baseline | Oyuns today |
|---|---|---|---|
| **Chart of accounts** | 4-digit statutory prefix (MoF order 249) + department/business segments; hard-coded account **group** drives report row mapping; account **type** drives which screens show it; active/passive nature; **sub-ledger flag** (туслах журнал); currency locked once used; financial-note, cash-flow & tax default indicators; roll-up “үндсэн данс”; bulk creation by department×business type; deactivate not delete | Hierarchical CoA, account type, currency | Hierarchical CoA with classification/purpose/currency/is_group; no group→report mapping, no sub-ledger control, no currency lock, no indicators |
| **Journal entry** | Batches (багц) each balanced; **no many-debit↔many-credit in one batch**; cash-flow indicator on counterpart line; VAT split, reversing entry; templates with row formulas & dept/employee split; import grouped by Reference; bulk receivables by customer group | Balanced manual JE, reversal | Balanced JE via generic docs; no batches, no template formulas, no many-to-many rule |
| **Periods & close** | Single opening-balance date; close with 11 automated checks; auto closing entries to P&L summary → retained earnings (per department); reopen LIFO only; close/reopen log; per-user lock date & lock-days (0–366) | Period open/close, year-end close | Open/close only; no checks, no closing entries, no reopen, no user lock |
| **Opening balances** | GL (permanent accounts + prior-year temp amounts) + AR/AP by settlement, inventory by item, assets by item — sub-ledgers must equal GL | Opening JE | CSV opening stock/open invoices only; no GL opening |
| **AR/AP** | Open-item by **settlement no. (Тооцоо №)**, responsible employee, contract, aging by settlement date, merge settlements, reconciliation act print, payment schedules, credit limit, head-customer consolidation | Invoice-level outstanding, aging | Invoice outstanding + allocations + aging |
| **Cash & bank** | Cash/bank account settings (bank, IBAN, signatories); auto statement download (Khan/TDB/Xac/Arig/Golomt) or Excel import; auto party match by TIN(7)/register(8); bulk journal creation with templates (e.g. QPay fee split) | Bank accounts, statement import, reconciliation | Payments post to single default cash account; statement matching only for payroll |
| **FX** | Currency master (ISO); MongolBank **prior-day closing** rate; account revaluation & settlement revaluation (optionally per settlement no.); realized/unrealized gain/loss; strict chronological order | Multi-currency GL, revaluation | Document stores currency/rate; GL single-currency; no revaluation |
| **Tax / e-Barimt** | Org & party VAT/city-tax payer status auto-checked via ebarimt API; item VAT type (normal/exempt/zero) + tax code + unified classification code; city tax 2% (date-based rate), “all sales city tax” per department or per item; department-level tax accounts; e-Barimt 3.0 (B2C lottery, B2B, bulk from journals); 12-digit citizen ID for individuals; no zero-amount receipts | Configurable tax templates | Generic `erp_tax_templates`; nothing Mongolia-specific; no e-Barimt |
| **Inventory** | Sub-ledger accounts only via inventory module; account-level mapping (COGS, revenue, discount, returns, shrinkage); periodic **costing run** with freshness check; serials/expiry, stock count | Perpetual stock, valuation | Stock ledger, valuation layers, negative-stock guard; postings use “first account of type”; no costing run |
| **Fixed assets** | Account-level accumulated depreciation / expense mapping; depreciation must be run before close | Asset register, depreciation | Books, straight-line schedules, disposal — present |
| **Sales / Purchasing / POS** | Full doc chain + POS, price lists, gift cards, membership, payment terms driving due dates | Quote→order→delivery→invoice | Document chain exists (gated Phase 5); no POS |
| **Payroll / HR** | Employee register incl. citizen ID, insured type, occupation code; payroll journal templates with department split; ND-8 & PIT (ХМ-11) exports; payslip email; Timely import; user formulas; avg-daily-wage auto calc | Payroll + GL posting + statutory exports | Strong calc engine; **monthly flow has no GL posting**; no ND-8/ХМ-11 export (v2 GL posting retired) |
| **Master data & dimensions** | Org (register-locked, TIN from tax), department tree w/ codes & signatories/stamps, business center/group/type, projects↔contracts↔GL lines, locations, payment terms, statuses per register, meta fields | Dimensions, custom fields | Departments, teams, cost centers, projects, custom fields; no business dims on GL; contracts have no financial terms |
| **Security & audit** | Single admin, users never deleted; per-window CRUD + “own records only”; report & account permissions; branch scoping of accounts/price lists; special perms (edit others’ journals, see cost/profit); document log | RBAC, audit | Capability RBAC with scopes, audit_logs — mostly present; lacks account/report-level perms and own-records restriction |
| **Reporting** | Balance sheet, income statement, equity changes, cash-flow (from indicators), financial notes, trial balance by group/dimension, ledgers, VAT by document/party, AR/AP aging | Standard statements | Trial balance, GL, AR/AP outstanding, dashboard (from documents, not GL) |

---

## 2. Critical Functional Gaps

### High — core compliance / accounting integrity
| ID | Gap | Why it matters |
|---|---|---|
| H0 | `ERPDocument` model missing `workflow_state`/`definition_version` | Runtime crash on document read/transition |
| H1 | Monthly payroll → GL posting | Payroll is the live module; no ledger record of salary, НДШ, ХХОАТ liabilities |
| H2 | Account master integrity: nature, report group, sub-ledger control, currency lock, deactivate-not-delete | Reports map rows by group; sub-ledger accounts edited by hand break reconciliation |
| H3 | Journal rules: batches, no many↔many, cash-flow indicator | Required for general-journal detail report & cash-flow statement |
| H4 | Multi-currency GL (base + transaction amounts) + FX revaluation (account & settlement) + rates master | IFRS/НББ requirement; without it FC balances drift |
| H5 | Mongolian tax model: VAT types/codes, city tax, party & org payer status (ebarimt lookup), department tax accounts | Every sales/purchase posting depends on it |
| H6 | e-Barimt 3.0 issuance (PosAPI) | Legal requirement for B2C/B2B sales receipts |
| H7 | Period close engine: validations, closing entries, retained earnings, LIFO reopen, user lock date/days | Prevents closing with broken sub-ledgers; protects filed periods |
| H8 | GL opening balances + sub-ledger reconciliation (AR/AP, inventory, assets) | First usable month depends on it |
| H9 | Financial statements from GL (balance sheet, P&L, cash-flow, equity) | Dashboard currently sums documents, not ledger |
| H10 | Statutory payroll exports ND-8, ХМ-11 | Monthly legal filings |

### Medium — operational automation
| ID | Gap |
|---|---|
| M1 | Open-item AR/AP by settlement no. (responsible employee, contract), aging by settlement date, merge, reconciliation act print |
| M2 | Journal templates with row formulas and amount types (balance / department / department-employee) |
| M3 | Cash & bank module: account settings (bank, IBAN, signatories), statement import (Excel first, bank APIs later), TIN/register party matching, bulk journalize |
| M4 | Account-level posting map (inventory account → COGS/revenue/discount/returns/shrinkage; asset account → accum/expense), replacing “first account of type” |
| M5 | Accounting dimensions on GL lines: department(branch), business center/group/type, project, contract |
| M6 | Contract financials: amount, penalty %, payment terms, AR/AP by contract |
| M7 | Inventory costing run + “documents changed after costing” detection |
| M8 | Permission extensions: account-level & report-level perms, own-records-only, edit-others’-journals, view cost/profit |
| M9 | Party enrichment: head customer, credit-limit enforcement, payment terms (days/months) driving due dates, group defaults (settlement account, price list), field-change log |
| M10 | Payment schedules (installments) linked to AR/AP |

### Low — quality of life / extended
L1 per-register statuses with color/order · L2 bilingual names (`name_en`) on accounts/descriptions for bilingual reports · L3 transaction-description library · L4 signatory chain (account→department→org) + logo/stamp on printouts · L5 CRM activities (due date, responsible, overdue days, expected revenue) · L6 payslip email · L7 item variants (model/color/size), serials/expiry · L8 yearly data archiving · L9 POS, gift cards, membership (out of scope unless retail is targeted) · L10 TaxAcc export.

---

## 3. Technical Specifications

Conventions (match existing code): every table has `organization_id` FK → `organizations` (CASCADE), `public_id` UUID, `created_at/updated_at`, optimistic `version`; money `Numeric(18,4)`, rates `Numeric(24,10)`; enums as `String` + `CheckConstraint`; all mutations go through `record_change` (`app/services/enterprise_events.py`) → `audit_logs`; GL stays append-only — corrections are reversals (`reversal_of_id`), never updates/deletes. Migrations use `backfill → server_default → NOT NULL` (see PR #3 pattern) and `sa_text` alias in models.

### H0 — Document model fix
- Add to `ERPDocument`: `workflow_state String(64) NOT NULL server_default 'draft'`, `definition_version Integer NOT NULL server_default '1'`. Migration only if DB column for `definition_version` is absent (check `d5e6f7g8h9i0`). Test: serialize any document via `document_out`.

### H1 — Monthly payroll GL posting
- **Objective:** a closed payroll run produces one balanced journal.
- **Schema:** `monthly_payroll_runs.+ erp_document_id FK erp_documents SET NULL`, `+ posting_status String CHECK in ('unposted','posted','reversed')`; GL lines already carry `payroll_run_id`, `payroll_role`.
- **Mapping:** extend `monthly_payroll_company_settings` with payable accounts (employee НДШ, employer НДШ, ХХОАТ, net pay, other deductions). Reuse `build_payroll_gl_lines` logic from `app/payroll/service.py` (roles: salary expense, employer НДШ expense, НДШ payable, PIT payable, net payable, advance clearing); split expense by department cost center (Dayansoft “Салбар” amount type).
- **Trigger:** run `approved → paid` (or explicit “Post to GL” action) creates `journal_entry` doc, passes `validate_posting_gate`.
- **Reversal:** month `unlock` must post a reversing journal before resetting runs to draft; posting blocked if period closed.
- **Permissions:** capability `payroll.post`; audit on post/reverse.

### H2 — Account master integrity
- **`erp_accounts` +:** `nature String CHECK ('debit','credit')`, `report_group_code String` (FK → new `erp_report_groups` seeded from MoF statement lines, read-only), `subledger_type String CHECK ('none','party','item','asset','employee')`, `cash_flow_indicator_id FK`, `financial_note_code`, `tax_indicator_code`, `rollup_account_id FK self`, `name_en`, `is_active`.
- **Rules:** currency / nature / subledger_type / report_group immutable once any GL line exists (409 with Mongolian message); delete allowed only with zero GL/opening refs, else `is_active=false`; manual journal (`journal_entry` doc) rejects lines on accounts with `subledger_type in ('item','asset')`; party sub-ledger lines require `party_id`.
- **Bulk create:** `POST /accounting/accounts/bulk` (template account × departments × business types, code separator).
- **New tables:** `erp_report_groups(code, name, name_en, statement CHECK ('bs','pl','cf','equity'), line_no, sign)`, `erp_cash_flow_indicators(code, name, section CHECK ('operating','investing','financing'))`.

### H3 — Journal batch rules
- **`erp_document_lines` +:** `batch_no Integer NOT NULL default 1`, `cash_flow_indicator_id FK`.
- **Gate additions** in `validate_posting_gate`: per batch Σdebit=Σcredit; per batch reject (debit lines >1 AND credit lines >1) with message “N-р багцад олон дебет олон кредитийн харьцаа үүссэн”; if batch touches a cash/bank account, counterpart lines need `cash_flow_indicator_id` (default from account).
- **Reversal:** existing cancel→reversing lines keeps batch_no.

### H4 — Multi-currency GL & FX revaluation
- **Rates:** `erp_currencies(code ISO4217, name, symbol, minor_unit, sort)`, `erp_exchange_rates(currency, rate_date, rate, source CHECK ('mongolbank','manual'))` UNIQUE(org,currency,date). Import job reuses `app/services/exchange_rate_service.py`; lookup rule = prior-day closing rate.
- **GL `erp_general_ledger_entries` +:** `currency`, `exchange_rate`, `debit_fc`, `credit_fc`; `debit/credit` become base-currency (MNT). Backfill: `fc = amount`, `base = amount × document.exchange_rate` where account currency ≠ base (audit before migrating).
- **Revaluation:** `erp_fx_revaluations(revaluation_date, scope CHECK ('account','settlement'), by_settlement bool, status CHECK ('draft','posted','reversed'), journal_document_id)`, `erp_fx_revaluation_lines(account_id, party_id, settlement_no, currency, fc_balance, book_base, rate, revalued_base, difference, gain_loss_account_id)`.
- **Rules:** revaluation date must be > last posted revaluation for same scope (chronological); deleting only the latest allowed (LIFO); generates journal with realized/unrealized gain/loss accounts (org settings `fx_gain_account_id`, `fx_loss_account_id`, `unrealized_*`).

### H5 — Mongolian tax model
- **Org/department:** `erp_accounting_settings +` `vat_payer bool`, `vat_registered_on date`, `city_tax_payer bool`, `vat_payable/receivable_account_id`, `city_tax_payable/receivable_account_id`; `departments +` same four account overrides, `city_tax_all_sales bool`, `city_tax_exempt_wholesale bool` (resolution: department → org).
- **Party `erp_parties` +:** `registry_no`, `tin`, `citizen_id_12`, `is_individual`, `vat_payer`, `city_tax_payer`, `tax_status_checked_at`.
- **Item `erp_items` +:** `vat_type CHECK ('standard','exempt','zero')`, `tax_code`, `classification_code` (7-digit unified fund code), `city_tax bool`.
- **Rates:** `erp_tax_rates(tax_kind CHECK ('vat','city'), rate, valid_from, valid_to)` — city tax 1% → 2% on 2024-01-01; line computation picks rate by posting_date.
- **Lookup service:** `app/services/ebarimt_lookup.py` calling `api.ebarimt.mn/api/info/check/getTinInfo` & `getInfo`; on org login/daily job detect status change → notification + audit; manual override when offline.
- **Posting:** sales/purchase lines split net / VAT / city tax to resolved accounts; VAT only when seller is VAT payer; purchase VAT receivable only when supplier is VAT payer.

### H6 — e-Barimt 3.0
- **Tables:** `erp_ebarimt_receipts(document_id FK, receipt_type CHECK ('b2c','b2b','invoice','return'), ddtd, lottery_no, customer_tin, customer_citizen_id, amount, vat, city_tax, status CHECK ('pending','sent','failed','returned'), payload JSONB, response JSONB, error, sent_at)`; `erp_ebarimt_settings(pos_api_url, merchant_tin, district_code, branch_no, credentials_secret_ref)`.
- **Triggers:** sales invoice/delivery submit (or bulk from journal list) → create pending receipt → job queue (`job_queue`) sends with retry; cancellation of a document with sent receipt → `return` call, blocks cancel on failure.
- **Validations:** no zero-amount receipts; every line needs classification code; individuals only by 12-digit citizen ID; no back-dated B2C for prior month.
- **Permissions:** `ebarimt.issue`, `ebarimt.return`; full request/response retention for audit. Credentials in Key Vault (per CLAUDE.md secrets rule).

### H7 — Period close engine
- **Tables:** `erp_period_close_runs(period_id, close_date, status CHECK ('checking','blocked','closed','reopened'), checks JSONB, closing_journal_id, closed_by, reopened_by, reopen_reason)`.
- **`erp_accounting_settings` +:** `opening_balance_date` (single, immutable once later GL exists), `pl_summary_account_id`, `retained_earnings_account_id`; departments may override both.
- **Checks (blocking vs warning), mirroring Dayansoft’s 11:** opening GL balanced; AR/AP, inventory, asset sub-ledger opening = GL opening; unposted submitted documents; document total ≠ its journal; trial balance ≠ sub-ledger reports (AR/AP, cash, inventory, assets); FX revaluation missing for close date; depreciation not posted through close date; inventory costing not run / documents changed after costing.
- **Transitions:** open → (check) blocked|closed; closed → reopened only for the **latest** closed period (LIFO); reopen reverses the closing journal. Closing journal: all P&L accounts → summary → retained earnings, per department if overrides exist.
- **User lock:** `user_accounts +` `lock_before_date`, `lock_days Integer 0–366`; gate rejects create/edit/delete of documents dated before the lock (“Та зөвхөн N хоногийн өмнөх гүйлгээ…”), admins exempt.

### H8 — Opening balances
- **Tables:** `erp_opening_balances(account_id, department_id, currency, rate, amount_fc, amount_base, prior_year_amount)`; `erp_opening_settlements(account_id, party_id|employee_id, settlement_no, settlement_date, contract_id, responsible_employee_id, currency, rate, amount_fc, amount_base)`; inventory/asset openings reuse existing opening-stock import and asset books.
- **Rules:** posting date = `opening_balance_date`; editable only while first period open; Σ sub-ledger per account must equal GL opening (close check); Excel import templates for each.

### H9 — Financial statements
- Report endpoints `/reports/{balance-sheet,income-statement,cash-flow,equity,financial-notes}` computed from GL via `report_group_code` / `cash_flow_indicator_id`; filters: department, business center, project, contract, month columns; bilingual via `name_en`. Replace dashboard revenue/expense source with GL.

### H10 — Statutory payroll exports
- `GET /payroll/monthly/months/{id}/exports/{nd8|hm11}` → XLSX in official layout from closed month snapshot; requires employee `citizen_id_12`, `insured_type_code`, `occupation_code` (add to `employee_details`, with occupation default on position). Stored in `monthly_payroll_archives`.

### Medium specs (condensed)
- **M1** `erp_settlements(settlement_no, account_id, party_id, employee_id, origin_document_id, contract_id, responsible_employee_id, opened_on, currency, original_fc/base, open_fc/base, status CHECK ('open','closed','merged'))`; GL lines + `settlement_no`; allocation updates open amounts; merge = generated journal (same party only); aging by `opened_on`; PDF reconciliation act.
- **M2** `erp_journal_templates(code,name)`, `erp_journal_template_lines(batch_no, row_no, debit_account_id, credit_account_id, cash_flow_indicator_id, party_id, amount_type CHECK ('manual','balance','department','department_employee','payroll_component'), formula, payroll_component_code, sort)`; safe formula evaluator (row refs `[n]`, + − × ÷ only); “apply template” fills a draft journal.
- **M3** `erp_bank_accounts(account_id, bank_code, iban_prefix, account_no, account_name, signatory_1/2/3, statement_provider)`; generalize `payroll_statement_imports/lines` into `erp_bank_statements/_lines(status CHECK ('unmatched','matched','journalized','ignored'), matched_party_id, bank_txn_id UNIQUE)`; matcher: 7-digit → TIN, 8-char → registry, else party code; bulk journalize with template (e.g. QPay fee split).
- **M4** `erp_account_posting_maps(account_id, role CHECK ('cogs','revenue','discount','sales_return','purchase_return','shrinkage','accum_depr','depr_expense','material_expense'), target_account_id)`; posting code resolves by line account, errors “…дансаа тохируулна уу!” when missing.
- **M5** `erp_business_dimensions(kind CHECK ('center','group','type'), code, name)`; `erp_accounts +` dimension FKs; GL lines + `department_id`, `project_id`, `contract_id` (denormalized at post time).
- **M6** `contract_documents +` `party_id`, `contract_code`, `amount`, `currency`, `penalty_pct`, `payment_term_id`, `ends_on`, `is_active`; balances view from GL by `contract_id`; overdue days computed.
- **M7** `erp_costing_runs(period_end, status, computed_at, last_doc_change_at)`; stock documents dated ≤ period_end changed after run mark it stale → close check.
- **M8** extend `erp_capabilities` resources with `account:<id>`, `report:<code>`; capability flags `own_records_only`, `journal.edit_others`, `sales.view_cost`.
- **M9** `erp_parties +` `parent_party_id`, `settle_via_parent bool`, `payment_term_id`, `group_id`; `erp_party_groups(default_settlement_account_id, default_price_list_id)`; `erp_payment_terms(days, period_unit, period_value)`; field-level change log via `audit_logs` diff.
- **M10** `erp_payment_schedules(party_id, contract_id, settlement_no, due_date, amount, paid_amount, status)`.

---

## 4. Phased Implementation Roadmap
Consistent with TODO.md gate: Selling/Buying/Stock workflows stay gated until one payroll month is reconciled; accounting foundations come first.

| Phase | Scope | Exit criteria |
|---|---|---|
| **0 Stabilize** | H0 document model fix; commit pending monthly payroll migrations; regression tests for `document_out` and transitions | All ERP document endpoints green on PostgreSQL |
| **1 Ledger integrity** | H2 account master, H3 journal batches, report groups & cash-flow indicators seed, H8 opening balances (GL + AR/AP + stock/asset reconciliation) | Opening trial balance balanced; sub-ledgers = GL |
| **2 Payroll → GL + filings** | H1 posting/reversal, H10 ND-8 & ХМ-11, employee statutory fields; M2 journal templates (payroll department split) | One payroll month posted, reconciled to register, exports accepted by accountant |
| **3 Tax foundation** | H5 org/party/item tax model, ebarimt status lookup, city-tax rate table, VAT/city tax posting | Sample sales & purchase invoices post correct VAT/НХАТ splits |
| **4 FX & close** | H4 base/FC GL + rates + revaluation; H7 close checks, closing entries, LIFO reopen, user lock; H9 statements | Month closed with zero blocking checks; BS/P&L tie to trial balance |
| **5 e-Barimt** | H6 PosAPI integration (sandbox → production), returns, bulk issuance | Receipts issued/returned in sandbox, retry/audit verified |
| **6 AR/AP & bank** | M1 settlements, M9 party enrichment, M10 schedules, M3 bank module (Excel import first) | Settlement aging matches GL; statement auto-match rate measured |
| **7 Operational** | M4 posting maps, M5 dimensions, M6 contract financials, M7 costing run, M8 permissions — unlocks gated Phase 5 selling/buying/stock | Full sales→invoice→receipt→cash cycle passes close checks |
| **8 QoL** | L1–L10 as prioritized by users | — |

Each phase: Alembic migration (backfill → default → NOT NULL), model mirror, service + router, `backend/tests/` unit tests (engine/gate rules pure-function tested), frontend form in `ERPWorkspacePage` / new accounting screens, audit entries.

## Verification
- Confirm Phase 0 bug: run `backend/tests` via `backend/Dockerfile.test` (`az acr build` → `pytest`) with a new test calling `document_out` on a fresh `ERPDocument`.
- Per phase: pytest for gate rules (batch/many-to-many, sub-ledger lock, lock-days), payroll GL balance (Σdebit=Σcredit, ties to salary register totals), close-check matrix, FX revaluation math against Dayansoft doc examples (e.g. 1,000 USD @3,200 → @3,400 revaluation), city-tax rate by date.
- End-to-end acceptance: opening balances → payroll month post → sample invoices with VAT → revaluation → close → statements tie out; e-Barimt against PosAPI sandbox.

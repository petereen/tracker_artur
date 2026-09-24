# Payroll Module (Цалин) — Run-Based Monthly Payroll
### Design plan and planning prompt for the AI coding agent — v2

**What changed in v2:** (1) the accountant first chooses the run type, **Урьдчилгаа цалин** or **Сүүл цалин**, and the table, formulas, validations and exports all change with that choice; (2) the payment-frequency selector **Monthly / Weekly / Biweekly** is back, with HR typing the pay days; (3) several ideas from the Dayansoft ERP payroll guide are adopted (§2.3).
**v2.1:** weekly = typed fixed days of the month (confirmed); overtime uses the base-salary basis of the accountant's Excel only (no last-3-month average); new manual column **Бусад суутгал** (deductions from the worker, such as wage penalties).

---

## 0. Instructions to the coding agent (read first)

1. **Inspect the repo before designing anything.** This brief was written without being able to browse the code. Map every concept below onto what already exists (worker record, HR module, accounting accounts, auth/roles, time/attendance data) and **reuse it**. Do not create a parallel worker table, chart of accounts or role system.
2. **Do not extend any existing multi-step payroll-run lifecycle** (preflight, freeze, reconcile, post, pay, release payslips) or any salary-structure / salary-component / formula-editor concept. This module is a thin, opinionated layer: **a month contains runs; a run is one table; one row per worker.**
3. **The Dayansoft guide is a flow reference only.** Do not copy its "indicator columns with F-codes", user-written formulas, salary templates or journal templates.
4. **Mongolian first.** All UI labels in Mongolian (glossary in §7). Money is whole tugrik (₮), thousand separators, no decimals shown.
5. **One calculation engine**, used by both run types, the HR "preview", the info boxes and the Excel export. No second copy of any formula.
6. **Do not output code in your plan.** Deliver: file-level plan, data structures, calculation spec, screen specs, test cases. Then implement in the phases in §17.

---

## 1. Goal and non-goals

**Goal.** An accountant opens «Цалин → Сарын цалин», picks a month, and presses **+ Шинэ бодолт**. The first thing they choose is the type: **Урьдчилгаа цалин** or **Сүүл цалин**. The system opens a table with one row per worker, already calculated for that type. They approve rows (or fix values), press **Бүгдийг батлах**, and export. The final run exports an Excel file laid out like the accountant's existing sheet (header rows 147–148 and data rows of the tab *«Цалингийн тооцоолол (2)»*).

**Non-goals (v1).** Salary structures/components, formula editors, payslip documents, sick-leave / maternity benefit calculators, piece-rate (наряд) and KPI modules, night-hour premiums, multi-currency, multi-level approval, НД-7/НД-8 and ХХОАТ filing forms.

---

## 2. Source material and what we take from it

### 2.1 Excel (tab «Цалингийн тооцоолол (2)», header rows 147–148, example row 151)
The table is on the **second** tab. Formulas found in the sample row:

| Column | Excel formula | Meaning |
|---|---|---|
| Ажиллах цаг (I) | days × 8 | planned hours |
| Тооцсон цалин (K) | base ÷ planned hours × worked hours | proration |
| Илүү цагийн хөлс (M) | OT hours × base ÷ planned hours × 1.5 | overtime (one multiplier only) |
| Олговол зохих цалин (Q) | K + M + Ээлжийн амралт + Хоол унаа + Урамшуулал | gross |
| НДШ (R) | Q × 11.5% | worker insurance |
| ХХОАТ (T) | (Q − R) × 10% − ХХОАТ ХӨН | tax after relief |
| Суутгалын дүн (V) | Урьдчилгаа + ХХОАТ + НДШ | total deductions |
| Гарт олгох цалин (X) | Q − V | remaining balance = **сүүл цалин** |
| БНДШ (Y) | Q × 12.5% | employer insurance |

The Excel column «Листний мөнгө» is **dropped** (confirmed).

### 2.2 Gaps between the Excel and the suray.mn rules (the engine must close these)
1. **НДШ cap is missing in Excel.** suray.mn caps the base at 10 × minimum wage (792,000 ₮ → **7,920,000 ₮**), so worker НДШ is at most 910,800 ₮/month.
2. **Tax is flat 10% in Excel.** suray.mn brackets: up to 10,000,000 → 10%; 10,000,001–15,000,000 → 1,000,000 + 15% of the excess over 10M; above 15,000,000 → 1,750,000 + 20% of the excess over 15M.
3. **ХХОАТ ХӨН (relief) is typed by hand in Excel.** It must be automatic, by taxable income (= gross − worker НДШ): 0–500k → 20,000; –1M → 18,000; –1.5M → 16,000; –2M → 14,000; –2.5M → 12,000; –3M → 10,000; above 3M → 0. Relief applied never exceeds the tax before relief (the Dayansoft guide makes the same point).
4. **Employer rate.** Excel uses a flat 12.5%; the «НД-н хувь хэмжээ» tab and suray.mn show **12.5–14.5%** depending on the company's occupational-accident rate (ҮОМШӨ 0.5–2.5%). Company setting, default 12.5%.
5. **One overtime multiplier** in Excel; the rules need three (§6.1).
6. **Урьдчилгаа is typed by hand** in Excel; it now comes from a real **advance run** (§5).
7. **2027 change:** suray.mn states income up to 792,000 ₮/month becomes ХХОАТ-exempt from 2027-01-01 (2026 rules stay). All statutory numbers live in **effective-dated rule sets** editable by an admin.

### 2.3 Dayansoft ERP payroll guide — adopted and not adopted
**Adopted:**
- Two separate calculation types chosen first, **Урьдчилгаа цалин** and **Сүүл цалин**, each with its own template of columns and formulas.
- Advance options: fixed amount typed by hand, **percent of base salary** (Dayansoft default 40%), or **by time worked**.
- The advance run carries **no tax or НДШ**; tax and НДШ are calculated once, on the whole month, in the final run.
- The final run **pulls the advance automatically**, only if the advance run was calculated first; otherwise it warns.
- A "pull from time records" action plus manual entry; manual inputs can be imported from an Excel template.
- A **formula-explanation window** («Багана дүн») showing, per column, the formula, the inputs and whether the value is automatic or manual.
- Deductions from the worker (wage penalties, amounts owed by the worker) as a manual column taken after tax.
- A mid-month base-salary change is split by working days before and after the change date.
- A payment list / bank transfer export per run.
- Advance larger than earned pay: Dayansoft records the excess as an employee receivable (offered here as an option, §16).

**Not adopted (Phase 2 or never):** the last-3-month-average overtime basis (overtime uses the base-salary formula of the accountant's Excel, confirmed), salary templates and F-code indicator columns, user-written formulas, journal templates, наряд/KPI, sick-leave and maternity calculators, wage-savings accounts, payslip e-mails.

---

## 3. Roles

| Role | Can do |
|---|---|
| **HR** | Create/edit workers and their *payroll profile* (§4.1). Cannot touch runs. |
| **Accountant** | Create runs, sync workers, edit row values, approve/reject rows, Approve all, export, mark paid, close the month. |
| **Admin** | Company payroll settings, statutory rule sets, holiday calendar, account mapping, unlock a closed run or month. |

Map onto the existing role system; do not invent new auth.

---

## 4. Data structures

### 4.1 Worker payroll profile (owned by HR, stored on the **shared worker record**)
The HR module, platform People/Users admin and payroll all read the *same* worker. Add:

- Base salary (Үндсэн цалин), monthly, with **valid-from date** (a short history list; the current value is the latest one on or before the payroll month; a mid-month change is handled by §6.1).
- Salary type: **PRORATION** (pay by worked hours) or **FIXED** (full amount regardless of hours).
- Meal (Хоол) amount, Commute (Унаа) amount.
- **Payment frequency: MONTHLY / BIWEEKLY / WEEKLY** and **pay days** (see §4.1.1).
- **Advance basis** (see §4.1.2): FIXED amount / PERCENT of base / WORKED-TO-DATE.
- Daily norm hours (default from company setting, 8), for part-time workers.
- Insurance type code (default 01001), "apply tax relief here" flag (default yes).
- Start date, end date; department, position, register number (РД), active status (already exist).
- Bank and account number (optional; only used in payment-list exports).

**Profile completeness rule:** a worker missing base salary, salary type, frequency or pay days is *not silently skipped*; runs show a "Profile incomplete" strip with a link to HR.

#### 4.1.1 Frequency and pay days (HR types the days; tax and НДШ stay monthly)
| Frequency | Pay days HR types (day of month) | Meaning |
|---|---|---|
| **MONTHLY** | 1 day (e.g. 25) | One payout = сүүл цалин. No advance run applies. |
| **BIWEEKLY** | 2 days (e.g. 10 and 25, or 5 and 20) | Day 1 = урьдчилгаа, day 2 = сүүл цалин. |
| **WEEKLY** | 4 days (e.g. 7, 14, 21, 28) | Days 1–3 = урьдчилгаа instalments, day 4 = сүүл цалин. |

A day number beyond the month length becomes the last day of the month. The frequency only decides **how many pay days HR must fill and which run each pay day belongs to**; it never changes the tax math.

#### 4.1.2 Advance basis (for every advance pay day of the worker)
- **FIXED:** HR types the advance amount for that pay day (₮).
- **PERCENT:** HR types a percent of base salary for that pay day (company default 40%, as in Dayansoft).
- **WORKED-TO-DATE:** no value typed; the advance is the pay earned up to the run's cut-off date, minus advances already paid this month (§6.2).

### 4.2 Company payroll settings (Admin, singleton)
Legal company name (export title), default daily norm hours (8), ҮОМШӨ employer rate (0.5–2.5%), the three overtime multipliers (§6.1, validated ≥ legal minimums 1.5 / 1.5 / 2.0), default advance basis and percent (default FIXED; 40% when PERCENT), the list of **deduction types** for Бусад суутгал (defaults: Торгууль / сахилгын шийтгэл, Хохирол / ажилтнаас авах авлага, Бусад), rounding (whole ₮, half-up), the accounts (§10).

### 4.3 Statutory rule set (Admin, effective-dated, seeded from suray.mn)
Per valid-from date: minimum wage; НДШ cap multiplier (10); worker rates by insurance type (pension 8.5, benefit 0.8, unemployment 0.2, health 2.0 = 11.5%); employer rates by type (pension 8.5, benefit 1.0, unemployment 0.5, ҮОМШӨ per company, health 2.0); ХХОАТ brackets; relief table. A month stores the version it used.

### 4.4 Work calendar (Admin)
One row per date with day type **Working / Weekly rest / Public holiday**. Default weekends = weekly rest. Admin marks public holidays and **transferred working days** (a transferred Saturday is a normal working day). Planned days/hours derive from this calendar.

### 4.5 Payroll month (container)
Year-month; rule-set version; calendar snapshot; list of its runs; status derived: **Open → Final approved → Closed**.

### 4.6 Run
- Month; **type** (ADVANCE / FINAL); **pay date** (advance runs: the pay date the run pays); **cut-off date** (advance runs, default = day before pay date); department filter (optional scope); status **Draft → Approved → Paid → Closed**; created/approved/paid/closed by and at; note.
- Uniqueness: one FINAL run per month; one ADVANCE run per (month, pay date).
- Scope is only a *filter*: a worker may appear in any run they are due in, and the final run pulls advances **by worker**, not by department (unlike Dayansoft, where a scope mismatch breaks the pull).

### 4.7 Run row (one per worker per run)
- **Common:** worker link, identity snapshot (last name, name, РД, position, department), profile snapshot (salary segments, type, meal, commute, frequency, pay days, advance basis/values, relief flag), override markers per field, status, note.
- **ADVANCE row:** basis, typed value, cut-off date, planned/worked time to cut-off (WORKED-TO-DATE only), **advance amount**, estimated monthly net (reference), advance as % of estimated net.
- **FINAL row:** time inputs (planned days/hours, worked normal hours, overtime hours in three buckets), accountant inputs (Ээлжийн амралт, Урамшуулал, **Бусад суутгал lines**: type, amount, note), every computed money field of §6.3, НДШ split (worker/employer), taxable income, **links to the advance rows it pulled**, final pay day.

### 4.8 Day lines (feed info boxes)
Per FINAL row (and per ADVANCE row for WORKED-TO-DATE): date, day type, hours, in/out if available, bucket (normal / weekday OT / rest-day / holiday), multiplier, amount. Source = the ERP's existing time/attendance data through **one adapter function**; the bucket is always decided by the calendar. If no time source exists yet, the same columns are filled by hand or by **Excel import** (template keyed by worker and column).

### 4.9 Row audit log
Who, when, field, old → new, reason. Nothing else.

### 4.10 Derived, not stored
For open runs: dashboard totals, department subtotals, formula explanations. At run close they are frozen into the archive (§11).

---

## 5. Runs and workflow

### 5.1 Month board («Цалин → Сарын цалин»)
Top: month selector. Below: a **strip of run cards** in order — each advance run (by pay date), then the final run — showing type, pay date, worker count, total ₮, approval progress "n / N", status chip and a Paid toggle. Button **+ Шинэ бодолт**.

### 5.2 New run dialog (type first)
1. **Төрөл (required, first):** `Урьдчилгаа цалин` or `Сүүл цалин`.
2. **If Урьдчилгаа:** choose the **pay date** from the dates present in workers' HR pay days (e.g. "10-ны өдөр — 23 ажилтан", "5-ны өдөр — 4 ажилтан"; the last pay day of each worker is excluded because it belongs to the final run). Optional department filter. If the basis of some due worker is WORKED-TO-DATE, the cut-off date field appears.
3. **If Сүүл цалин:** optional department filter only.
4. **Үүсгэх** creates the run and opens its table already calculated.

The advance run lists only workers **due on that pay date**. **Ажилтан нэмэх** adds a one-off advance for a worker who is not scheduled.

### 5.3 Run life cycle
```
Draft (system-calculated) ─ accountant reviews: ✓ approve / ✗ flag / ✎ edit
   ▼  [Бүгдийг батлах] approves every row without a blocking error
Approved ─ export enabled
   ▼  [Төлсөн] marks the run paid (advance runs lock here)
Paid
   ▼  final run only: [Сар хаах] → closing stats → lock → archive
Closed (month closed)
```
Advance run: Draft → Approved → Paid (locked). Final run: Draft → Approved → Closed (Paid can be toggled before closing). Unlocking a Paid/Closed run is Admin only, with a reason.

### 5.4 Sequencing rules (advance → final)
- The final run **pulls the sum of a worker's advances from Approved advance runs of the same month**, by worker.
- A worker with an advance pay day whose advance run does not exist or is not approved gets the warning chip **«Урьдчилгаа бодоогүй»** and advance = 0 (editable, marked manual). The accountant can proceed knowingly.
- If an advance run changes after the final run was calculated, the final rows show **«Урьдчилгаа өөрчлөгдсөн»** and the action **Урьдчилгаа дахин татах** appears.
- A short read-only **checklist** sits on top of the final run: advance runs approved · time data loaded · extra work recorded · manual columns filled. It informs; it never blocks.
- Worker import rules: workers come from the single shared worker record (HR is the main source; platform admin and the **Ажилчид шинэчлэх** button add/refresh them). Inactive workers are excluded. Rows are **snapshots**; if HR changes a profile later the row shows **«HR changed»** with an Accept action. Sync never overwrites edited or approved rows.

---

## 6. Calculation spec (single engine; plain-language formulas)

All money rounded to whole ₮ **per cell**; totals are sums of rounded cells so exports reconcile.

### 6.1 Common building blocks
- **Planned days** = working days in the month per calendar (holidays and rest days excluded), limited to start/end dates. **Planned hours** = planned days × worker daily norm.
- **Salary segments:** if the base salary changes mid-month, split planned days/hours at the valid-from date and use each segment's salary (example: 1,000,000 ÷ 21 × 10 + 1,500,000 ÷ 21 × 11). The info box shows both segments.
- **Hourly rate** r = base ÷ planned hours (per segment).
- **Day buckets** (from the calendar): public holiday → bucket 3 (all hours); weekly rest day → bucket 2 (all hours); working day → hours up to the norm are normal, hours above the norm → bucket 1. Overtime is never double counted in normal hours.
- **Multipliers** (Labour Law art. 109: overtime ≥ 1.5×, weekly rest day ≥ 1.5×, public holiday ≥ 2×): defaults 1.5 / 1.5 / 2.0, the **total** pay factor (hours × rate × multiplier).
- **Estimated monthly net (reference, advance run):** the engine run on the profile alone for a full month (base + meal + commute, no extras, no advance).

### 6.2 ADVANCE run (Урьдчилгаа цалин)
No НДШ, no ХХОАТ, no overtime, no meal/commute. Tax and НДШ are calculated once, on the whole month, in the final run.
- **FIXED:** advance = the amount HR typed for this pay day.
- **PERCENT:** advance = base salary × percent for this pay day.
- **WORKED-TO-DATE:** earned to cut-off = PRORATION → r × normal hours worked from the 1st through the cut-off date; FIXED-type → base × (planned working days elapsed ÷ planned working days of the month). **Advance = earned to cut-off − advances already approved in earlier advance runs this month** (never below 0).
- Manual override allowed on the advance amount.
- **Reference columns:** estimated monthly net and advance as % of it.

### 6.3 FINAL run (Сүүл цалин)
- **Тооцсон цалин:** PRORATION → r × worked normal hours; FIXED → full base (hours informational).
- **Илүү цагийн хөлс** = r × (bucket1 × m1 + bucket2 × m2 + bucket3 × m3), with r = base ÷ planned hours (per salary segment), exactly as in the accountant's Excel. Base-salary basis only (confirmed); no last-3-month average.
- **Хоол унаа** = meal + commute. Default: full for FIXED, prorated by worked ÷ planned hours for PRORATION (A4).
- **Олговол зохих цалин (gross Q)** = Тооцсон + Илүү цагийн хөлс + Ээлжийн амралт + Хоол унаа + Урамшуулал. (Ээлжийн амралт and Урамшуулал are typed by the accountant; like Dayansoft, leave pay is entered by hand.)
- **НДШ base** = Q, capped at 10 × minimum wage. Rule-set switches allow excluding components from the НДШ/ХХОАТ base; defaults = everything counts (as the Excel does).
- **Worker НДШ** = base × 11.5% (8.5 / 0.8 / 0.2 / 2.0 stored). **Employer НДШ (БНДШ)** = base × employer rate (split stored).
- **Taxable income** = Q − worker НДШ. **ХХОАТ before relief** = bracket formula (§2.2). **ХХОАТ ХӨН** = relief-table value if the worker's flag is on, never more than the tax before relief. **ХХОАТ (T)** = tax before relief − relief applied.
- **Урьдчилгаа** = sum of the worker's advance lines from Approved advance runs of the month (§5.4).
- **Бусад суутгал** = sum of the worker's manual deduction lines (wage penalty, amount owed by the worker, other). Entered by the accountant in the final run only. Taken **after** tax: it never changes the НДШ or ХХОАТ base.
- **Суутгалын дүн** = урьдчилгаа + ХХОАТ (T) + worker НДШ + Бусад суутгал.
- **Сүүл цалин / Гарт олгох цалин** = Q − Суутгалын дүн. Must be ≥ 0 (§15).
- **Built-in check:** Суутгалын дүн + Сүүл цалин = Q for every row.

### 6.4 Manual edits
Any computed cell is editable in either run type. An edited cell shows a "manual" dot and can be reverted to automatic; downstream cells recalculate unless also overridden. Editing an *Approved* row returns it to *Edited*. **Цагийн бүртгэлээс татах** refreshes time inputs; **Дахин бодох** recalculates formulas; both skip manual cells and approved rows.

---

## 7. Screens

**Glossary:** Урьдчилгаа · Сүүл цалин (Гарт олгох цалин) · Тооцсон цалин · Илүү цаг · Олговол зохих цалин · Суутгалын дүн · БНДШ · ХХОАТ ХӨН · Төлсөн · Батлах · Сар хаах · Архив.

### 7.1 Advance run table
Columns: № · Овог, Нэр · РД · Албан тушаал · Үндсэн цалин · Төрөл (Proration/Fixed) · Урьдчилгааны суурь · Хувь/дүн · *(WORKED-TO-DATE only:)* Ажилласан цаг · **Урьдчилгаа** · Сарын цэвэр (тооцоолсон) · Урьдчилгаа % · Төлбөрийн өдөр · Төлөв · ✓ · ✗ · ⓘ. Sticky totals footer.

### 7.2 Final run table (Excel order)

| # | Label | Filled by | Notes |
|---|---|---|---|
| 1 | № | system | |
| 2 | Овог, Нэр | system | shown together; separate in export |
| 3 | РД | system | |
| 4 | Албан тушаал | system | |
| 5 | Үндсэн цалин | HR snapshot | editable |
| 6 | Ажиллах өдөр | calendar | editable |
| 7 | Ажиллах цаг | calendar × norm | |
| 8 | Ажилласан цаг | time source | editable, normal hours only |
| 9 | Тооцсон цалин | system | by salary type |
| 10 | Илүү цаг | time source | total with 3-bucket breakdown; highlighted (§8) |
| 11 | Илүү цагийн хөлс | system | highlighted (§8) |
| 12 | Ээлжийн амралтын мөнгө | accountant | manual |
| 13 | Хоол унаа | HR snapshot | |
| 14 | Урамшуулал | accountant | manual |
| 15 | Олговол зохих цалин | system | gross |
| 16 | НДШ | system | worker share |
| 17 | ХХОАТ ХӨН | system | relief applied |
| 18 | ХХОАТ | system | after relief |
| 19 | Урьдчилгаа | advance runs | pulled by worker; badge shows source |
| 20 | Бусад суутгал | accountant | manual; lines in the ⓘ drawer |
| 21 | Суутгалын дүн | system | |
| 22 | Сүүл цалин (Гарт олгох цалин) | system | negative = error |
| 23 | БНДШ | system | employer share |
| — | Төлөв · ✓ · ✗ · ⓘ | UI only | not exported |

Grouped header like the Excel: **Суутгалууд** spans НДШ, ХХОАТ ХӨН, ХХОАТ, Урьдчилгаа, Бусад суутгал; **Ажиллах** spans Өдөр, Цаг.

### 7.3 Behaviour common to both tables
- Rows grouped by department with collapsible groups and **department subtotals**; sticky grand-total footer; frozen columns № and Овог/Нэр; sticky header; horizontal scroll (desktop target).
- Inline editing with spreadsheet-like Enter/Tab. Computed cells are read-only until "edit" is chosen.
- Column presets: *Бүрэн* and *Товч*.
- **ⓘ row drawer:** tabs — *Тооцооны задаргаа* (for each column: formula in words, inputs with values, automatic or manual; tax steps taxable income → bracket → relief; НДШ split), *Өдрөөр* (day-by-day lines), *Урьдчилгаа* (advance lines pulled, final run), *Суутгал* (Бусад суутгал lines: type, amount, note; add/edit/remove), *Түүх* (audit log, "HR changed" diff).

### 7.4 Header bar (per run)
`◀ 2026-08 ▶` · run title («Урьдчилгаа — 10-ны өдөр» / «Сүүл цалин») · **Ажилчид шинэчлэх** · **Цагийн бүртгэлээс татах** · **Дахин бодох** · **Бүгдийг батлах** · **Батлалт цуцлах** · **Excel татах** (disabled until all rows approved; tooltip "N мөр батлагдаагүй") · **Төлсөн** · **Сар хаах** (final run only) · **Архив**.
Below: search, department filter, status chips (Бүгд / Ноорог / Батлагдсан / Анхаарах / Илүү цагтай), progress "42 / 48 батлагдсан". The final run also shows the §5.4 checklist.

### 7.5 Row actions
✓ approve · ✗ flag with required note (row stays out of Approve all) · ✎ edit. A row with a blocking error cannot be approved. Status chips: Ноорог · Засварласан · Анхаарах · Батлагдсан · Алдаатай.

---

## 8. Overtime, weekend and holiday highlighting + info box (final run)

- Cells **Ажилласан цаг**, **Илүү цаг** and **Илүү цагийн хөлс** get a coloured background when the row has extra work. One colour per type: weekday overtime (amber), weekly rest day (blue), public holiday (red). Several types in one cell → striped fill or one dot per type. Colour is never the only signal (icon + text in the box).
- Hover (desktop) or tap (mobile) opens an **info box**:
  - a table of every extra-work day: **date · weekday · day type (holiday name if any) · in–out · hours · multiplier · hourly rate used · amount**;
  - a subtotal per type and a grand total that **equals the cell value**;
  - the hourly rate used (base salary ÷ planned hours) and the legal reference (Хөдөлмөрийн тухай хууль 109.1 / 109.2 / 109.4).
- The box reads the same day lines the engine used; it never recalculates. If the accountant overrides the cell, the box shows both "calculated" and "manual".

---

## 9. Dashboard («Цалин → Хянах самбар»)

Month selector plus:
1. **Run pipeline:** each advance run and the final run with status, totals and Paid/Closed markers.
2. **KPI cards:** Урьдчилгаа (total, paid/planned) · Олговол зохих цалин (gross) · ХХОАТ (net of relief) · Ажилтны НДШ · БНДШ · Бусад суутгал · Сүүл цалин · **Нийт зардал** (gross + БНДШ). Final-run KPIs show once a final run exists.
3. **Approval progress** per run, linking to unapproved rows.
4. **Overtime card:** hours and ₮ by bucket.
5. **By department** table: headcount, gross, НДШ, ХХОАТ, total cost.
6. **Trend chart:** total cost and gross for the last 6–12 months.
7. **Upcoming payments:** next pay dates (advance or final, worker count, amount) from the runs and HR pay days.
8. **Alerts:** blocking errors, warnings, incomplete profiles, HR-changed rows, «Урьдчилгаа өөрчлөгдсөн».

Plus a link to the archive; closed months show the closing stats card (§11). No configurable widgets.

---

## 10. Accounting mapping

- **Account A — Salary expense (final run):** Суутгалын дүн + Сүүл цалин, summed over approved rows; by construction equal to total gross Q.
- **Account B — Employer НДШ:** sum of БНДШ.
- Admin picks both from the existing chart of accounts. The **Accounting summary** (dashboard card + export sheet) shows A and B with sub-lines for A: урьдчилгаа, ХХОАТ, ажилтны НДШ, бусад суутгал (by type), сүүл цалин; per-department split.
- **Advance run:** the summary shows total advance paid or planned. **Reconciliation line:** Σ advances pulled into the final run must equal Σ approved advance runs of the month.
- **Ledger posting (assumption A8):** display and export only at first. When posting is switched on, an optional third account **C — Урьдчилгаа цалин (clearing)** receives the advance at payment and is closed by the final run (the pattern the Dayansoft guide uses); confirm the account structure with the company accountant first.
- **Бусад суутгал** stays inside A (A = Суутгалын дүн + Сүүл цалин). When ledger posting is switched on, the admin maps each deduction type to its counter-account (for example receivable from the worker, or penalty income).
- If a run's numbers change after posting, the summary shows "posted amounts differ" — nothing is silently re-posted.

---

## 11. Month closing, closing stats and archive

### Сар хаах (final run)
1. **Preconditions:** the final run is approved; every advance run of the month is Approved (a run may be waived with a reason); no blocking errors; invariants pass (Суутгалын дүн + Сүүл цалин = Q per row; column sums equal dashboard totals; advance reconciliation).
2. The **closing stats screen** («Сарын хаалтын тайлан») opens first.
3. **Confirm** → all runs of the month become *Closed*; the archive snapshot is written; the accounting summary is produced; the final Excel export is generated once and stored.
4. **Unlock:** Admin only, reason required; the next close creates a **new archive version**; earlier versions stay readable.

### Closing stats (general)
- **Headcount:** on the table, paid, new, left, workers with extra work, workers with manual edits.
- **Money totals:** gross; ХХОАТ before relief, total relief, net ХХОАТ; worker НДШ; БНДШ; урьдчилгаа (total and by run); бусад суутгал (total and by type); сүүл цалин; **total company cost** (gross + БНДШ).
- **Averages and range:** average and median gross, average take-home, highest and lowest gross.
- **Extra work:** hours and ₮ by bucket, workers, top 5.
- **By department:** headcount, gross, НДШ, ХХОАТ, total cost, share.
- **Change vs the previous closed month:** ₮ and % for gross, cost, headcount, extra work.
- **Quality:** manual overrides, flagged-then-resolved rows, НДШ cap hits, workers without an advance run, warnings at closing.
- **Accounting:** A and B totals (and C if used). **Meta:** rule-set version, calendar snapshot, approvers, closed by/at, archive version.

### Runs and payments
Every run (advance or final) is stored with its lines and status **Planned / Paid**: pay date, total, who marked it paid and when, note. There is **no bank integration**; the payment-list export (§12) is what goes to the bank. Final-run workers may have different final pay days; the payment list is grouped by pay day.

### Archive («Цалин → Архив»)
- **Immutable snapshot** per closed month and version: month header (rule set, calendar), all runs with every row and manual-override markers, НДШ split and tax steps, day lines, closing stats, accounting summary, row audit log, approval trail, and each export exactly as generated.
- **Screen:** list by month (headcount, total cost, version, runs paid/planned). Opening a month gives a read-only view of runs, dashboard and closing stats, worker search, re-download of stored files.
- **Worker history:** one worker across all archived months, exportable to Excel.
- Archived numbers are never recalculated, so later rule or profile changes cannot alter them. No delete in the UI; kept indefinitely by default (admin decides retention).

---

## 12. Export and reports

### 12.1 Advance run export (enabled when all rows approved)
- **Sheet 1 «Урьдчилгаа»:** title `"<Company>" ХХК-ийн MM сарын урьдчилгаа цалин (DD өдөр)`, columns as §7.1 without the reference columns, department subtotals, grand total.
- **Sheet 2 «Төлбөрийн жагсаалт»:** worker, РД, bank, account number, amount (rows with missing bank data are flagged).

### 12.2 Final run export (enabled when all rows approved)
- **Sheet 1 «Цалингийн хүснэгт»:** title `"<Company>" ХХК-ийн MM сарын цалингийн хүснэгт`; two-row grouped header like the sample (the Суутгалууд group has one extra column, Бусад суутгал); department group rows with subtotals; grand total; footnote «БНДШ – Байгууллагын төлөх нийгмийн даатгалын шимтгэл». Values as approved (including manual edits); totals as SUM formulas; number format `#,##0`; landscape, fit to width.
- **Sheet 2 «Дүн»:** closing stats plus Account A / B (and C) summary.
- **Sheet 3 «Илүү цаг»:** every extra-work day line with bucket, multiplier, hourly rate used, amount.
- **Sheet 4 «НДШ задаргаа»:** worker and employer share by insurance type per worker.
- **Sheet 5 «Төлбөрийн жагсаалт»:** сүүл цалин by pay day with bank and account.
- **Sheet 6 «Бусад суутгал»:** every deduction line (worker, type, amount, note).

### 12.3 Reports page (presets, with month-range and department filters, each exportable)
1. Payroll table (any month, re-export a closed month).
2. Tax and НДШ summary by month with year-to-date.
3. Overtime report by worker and bucket.
4. Company cost by department by month.
5. Advance vs final by month.
6. Other deductions by worker and type.

Reports read archived data for closed months and live data for open months.

---

## 13. Settings screens (Admin)
1. **Company payroll settings** (§4.2).
2. **Statutory rules** (§4.3): versions by valid-from date, "copy to new version", seeded with 2026 values from suray.mn.
3. **Work calendar** (§4.4).
4. **Accounts** (§10).

---

## 14. HR worker form additions

Add a **«Цалингийн тохиргоо»** section with the fields of §4.1. The pay-day inputs change with the selector: MONTHLY shows 1 day; BIWEEKLY shows 2 days (advance day, final day) and the advance basis/value; WEEKLY shows 4 days and an advance basis/value for each of the first three. A **live preview** on the right calls the same engine: estimated gross → НДШ → taxable income → ХХОАТ ХӨН → ХХОАТ → net for a full month, and the advance amount(s) with the pay-day schedule. HR list gets the same activate/inactivate/edit/delete menu as platform settings.

---

## 15. Validation

**Advance run — blocking:** missing basis or value; advance not a positive number; worker not due on the run's pay date (unless added by "Ажилтан нэмэх"); duplicate row for the same worker.
**Advance run — warnings:** advance above the estimated monthly net; WORKED-TO-DATE with no time data; bank data missing (export only).

**Final run — blocking:** Сүүл цалин < 0 (advance and deductions larger than earned pay; resolve by editing values, or see the receivable option in §16); a Бусад суутгал line with an amount ≤ 0; missing base salary, salary type, frequency or pay days.
**Final run — warnings:** worked hours = 0 for a PRORATION worker; worked hours above planned; any overtime/rest-day/holiday work; base salary below minimum wage for a full-time worker; profile changed in HR after import; «Урьдчилгаа бодоогүй»; «Урьдчилгаа өөрчлөгдсөн»; НДШ cap hit; Бусад суутгал line without a type or note.

**Month:** final run cannot close while an advance run is unapproved (waiver with reason allowed).

---

## 16. Decisions and assumptions

**Confirmed by the user**
- **C1.** HR types the pay days of the month per worker (e.g. 10th & 25th, 5th & 20th).
- **C2.** «Листний мөнгө» is dropped.
- **C3.** Step 4 is **Сар хаах** with general closing stats; all runs are stored and archived with a detailed breakdown.
- **C4.** The frequency selector **Monthly / Weekly / Biweekly** stays for flexibility.
- **C5.** The accountant first chooses **Урьдчилгаа** or **Сүүл цалин**, and the calculation, table and export change with that choice.
- **C6.** WEEKLY = fixed days of the month typed by HR (four days: three advances, one final).
- **C7.** Overtime uses the base-salary formula of the accountant's Excel with the three Labour Law multipliers (1.5 / 1.5 / 2.0). The last-3-month average is not used.
- **C8.** **Бусад суутгал** is a column for deductions from the worker (wage penalties etc.).

**Assumptions (defaults used; change any that are wrong)**
- **A1. BIWEEKLY** means two typed pay days (advance, final); MONTHLY means one payout with no advance. (The WEEKLY part of the old A1 and the old A5 on overtime basis are now C6 and C7.)
- **A2. Advance run** carries no tax or НДШ and excludes overtime and meal/commute; it is based on base salary only.
- **A3. Source of hours:** the ERP's existing time/attendance data (or Excel import/manual); hours beyond the daily norm on working days count automatically as overtime, and the accountant can zero them out.
- **A4. Meal/commute:** counted in the НДШ/ХХОАТ base (as in the Excel); full for FIXED, prorated for PRORATION workers. Confirm with the company's accountant.
- **A6. Employer rate:** 12.5% default, adjustable to 12.5–14.5% via the ҮОМШӨ setting.
- **A7. Tax relief:** applied automatically unless the worker's flag is off.
- **A8. Ledger posting:** display and export first; posting once the ERP's ledger interface and account structure are confirmed.
- **A9. Pay days** are days of the same payroll month (a day beyond month end becomes the last day).
- **A10. Other absences** (sick-leave benefits, annual-leave accrual) are out of scope: those days reduce worked hours; leave pay is typed in *Ээлжийн амралтын мөнгө*.
- **A11. Paid status** is a manual Planned / Paid toggle per run; no bank integration.
- **A12. Archive versions:** unlocking and closing again creates a new version; old versions are kept.
- **A13. Over-advanced worker** (advance > earned pay): blocks approval in v1. Option for later: carry the excess as an employee receivable deducted from next month's сүүл цалин.
- **A14. Бусад суутгал** is taken after tax (it does not change the НДШ/ХХОАТ base) and exists in the final run only; amounts over the available pay block approval through the Сүүл цалин ≥ 0 rule (A13).

---

## 17. Build order

1. **Foundation:** shared-worker payroll profile (frequency, pay days, advance basis, salary history, bank), company settings, statutory rule set (seeded), work calendar, calculation engine for both run types + unit-style test cases (§18).
2. **HR form:** payroll section with the frequency selector and live preview.
3. **Runs:** month board, **+ Шинэ бодолт** dialog (type first), worker import/sync, run states.
4. **Advance run:** table, three advance bases, validation, approval, payment-list export, Paid.
5. **Final run:** table, advance pulling and sequencing rules, Бусад суутгал lines, editing, validation, Approve all.
6. **Extra-work highlighting, info boxes, ⓘ drawer** with formula explanation; day-line adapter to the time source; Excel import of manual columns.x`
7. **Final Excel export** (sheet 1 first, then 2–5).
8. **Dashboard, reports page, accounting summary.**
9. **Сар хаах:** closing stats, lock, archive (versions, read-only month view, stored files, worker history export).

**Phase 2 candidates (do not build now):** payslip PDF, direct bank integration, НД-7/НД-8 and ХХОАТ filing exports (with profession code), other additions (KPI, bonuses beyond Урамшуулал), employee-receivable balances pulled from the ledger, leave-pay helper, sick-leave/maternity calculators, two-step approval.

---

## 18. Acceptance test cases (numbers verified against suray.mn and the Excel)

**Final run, monthly 2026 rules, no other pay components, relief on:**

| Gross | Worker НДШ | Taxable | ХХОАТ before relief | Relief | ХХОАТ | Take-home before advance |
|---|---|---|---|---|---|---|
| 792,000 | 91,080 | 700,920 | 70,092 | 18,000 | 52,092 | 648,828 |
| 1,500,000 | 172,500 | 1,327,500 | 132,750 | 16,000 | 116,750 | 1,210,750 |
| 2,500,000 | 287,500 | 2,212,500 | 221,250 | 12,000 | 209,250 | 2,003,250 |
| 12,000,000 | 910,800 (cap) | 11,089,200 | 1,163,380 | 0 | 1,163,380 | 9,925,820 |

**Excel row (Оюун-Эрдэнэ style), full flow:** base 1,500,000, BIWEEKLY pay days 10 and 25, advance basis PERCENT 40% → **advance run** on the 10th gives 600,000. **Final run:** 168/168 hours, Ээлжийн амралт 168,000, Хоол унаа 120,000 → Q 1,788,000; НДШ 205,620; taxable 1,582,380; ХХОАТ before relief 158,238; relief 14,000; ХХОАТ 144,238; урьдчилгаа 600,000 (pulled) → Суутгалын дүн 949,858; сүүл цалин 838,142; БНДШ at 12.5% = 223,500. Payments: 600,000 on the 10th, 838,142 on the 25th.

**Excel sample row 151:** base 2,000,000, 21 days (168 planned hours), 147 worked, PRORATION → Тооцсон 1,750,000 = Q; НДШ 201,250; taxable 1,548,750. The Excel shows ХХОАТ 154,875 only because ХХОАТ ХӨН was left blank; the system applies relief 14,000 → ХХОАТ 140,875; with урьдчилгаа 750,000 → Суутгалын дүн 1,092,125; сүүл цалин 657,875; БНДШ 218,750.

**Advance WORKED-TO-DATE:** base 1,500,000, 168 planned hours, PRORATION, 80 normal hours through the cut-off → advance 714,286. A second advance run with 120 cumulative hours: earned 1,071,429 − 714,286 already paid = 357,143.

**Extra work (base-salary basis, as in the Excel):** base 1,500,000, 168 planned hours → r ≈ 8,928.57. 4 h weekday overtime × 1.5 = 53,571; 8 h weekly-rest-day × 1.5 = 107,143; 8 h public holiday × 2.0 = 142,857; total Илүү цагийн хөлс 303,571; the info box lines add up to the cell.

**Бусад суутгал:** the Excel row above plus a 50,000 wage penalty → НДШ and ХХОАТ unchanged (205,620 and 144,238); Суутгалын дүн 949,858 + 50,000 = 999,858; сүүл цалин 1,788,000 − 999,858 = 788,142; Account A still equals Q = 1,788,000.

**Mid-month salary change:** 1,000,000 until the 15th, 1,500,000 after; 21 planned days (10 before, 11 after) → 476,190 + 785,714 = 1,261,904 base earned (FIXED type).

**Sequencing:** final run calculated before the advance run is approved → «Урьдчилгаа бодоогүй», advance 0; approving the advance run afterwards → «Урьдчилгаа өөрчлөгдсөн» until **Урьдчилгаа дахин татах**.

**Invariants:** an archived month is identical after a statutory rule set is edited; Суутгалын дүн + Сүүл цалин = Q for every row; Σ advances in the final run = Σ approved advance runs; column sums in the export equal the dashboard KPIs; Account A = total Q; Account B = total БНДШ.
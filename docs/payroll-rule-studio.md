# Configurable Mongolia payroll rule studio

The unified payroll v2 path now resolves an effective statutory profile and
work policy before calculation, freezes the selected rules in `PayrollRun`, and
retains fund-level statutory lines beside each `Payslip`. Workbook layouts are
not imported and no workbook rate is seeded.

Administrators edit profile tiers through the Setup Hub or the additive profile
payload. Supported modes are `flat_percent`, `marginal_tiers`, `band_rate`, and
the allowlisted AST `formula` mode. Salary components use `fixed`, `percentage`,
or `formula` amount modes; all formulas are compiled without Python/JavaScript
evaluation.

НДШ tiers also expose a `profile` cap or explicit `none` cap policy, plus
floors, fixed/base amounts, exemptions, and fund/payer/hazard selectors.

The formula DSL exposes arithmetic, comparisons, boolean/conditional branches,
and only `min`, `max`, `abs`, `round_money`, and `if_else`. Runtime names are
resolved from the frozen context (salary, scheduled/payable units, categorized
overtime, YTD values, statutory parameters, approved leave/benefit inputs,
manual variables, and earlier component codes). Unknown names, cycles, unsafe
AST nodes, division by zero, non-finite results, and negative statutory amounts
are rejected.

Every production profile and report template must cite and be approved against
the current authoritative source, for example:

- [Social Insurance General Law](https://legalinfo.mn/mn/detail?lawId=16760148379551)
- [2026 Health Insurance rate resolution](https://legalinfo.mn/mn/detail?lawId=17434916300742)
- [Personal Income Tax law](https://legalinfo.mn/mn/detail?lawId=14410)
- [Labor Law](https://legalinfo.mn/mn/edtl/16532053891911)

Use `/v1/erp/payroll/statutory-profiles/{id}/simulate` for a non-persisting
calculation ladder. Filing outputs are generated only from frozen run/payslip
snapshots: `nd7a`, `nd7b`, `nd8`, and `tt11`, with CSV, XLSX, and print/PDF
formats. Direct portal submission is intentionally outside Phase 1.

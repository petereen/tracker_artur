from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    EmployeeBenefitApplication,
    EmployeeBenefitClaim,
    EmployeeTaxExemptionDeclaration,
    EmployeeTaxExemptionProof,
    PayrollRun,
    PayrollTaxExemptionCategory,
    SalaryComponent,
)


ZERO = Decimal("0")


def money(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


async def approved_tax_adjustments(
    db: AsyncSession,
    *,
    organization_id: int,
    employee_id: int,
    tax_year: int,
) -> dict[str, Any]:
    declarations = list((await db.execute(
        select(EmployeeTaxExemptionDeclaration, PayrollTaxExemptionCategory)
        .join(PayrollTaxExemptionCategory, PayrollTaxExemptionCategory.id == EmployeeTaxExemptionDeclaration.category_id)
        .where(
            EmployeeTaxExemptionDeclaration.organization_id == organization_id,
            EmployeeTaxExemptionDeclaration.employee_id == employee_id,
            EmployeeTaxExemptionDeclaration.tax_year == tax_year,
            EmployeeTaxExemptionDeclaration.status == "approved",
            PayrollTaxExemptionCategory.is_active.is_(True),
        )
    )).all())
    if not declarations:
        return {"deduction": ZERO, "credit": ZERO, "items": []}

    proof_totals = dict((await db.execute(
        select(EmployeeTaxExemptionProof.declaration_id, func.sum(EmployeeTaxExemptionProof.amount))
        .where(
            EmployeeTaxExemptionProof.declaration_id.in_([row.id for row, _ in declarations]),
            EmployeeTaxExemptionProof.status == "approved",
        )
        .group_by(EmployeeTaxExemptionProof.declaration_id)
    )).all())
    totals = {"tax_deduction": ZERO, "tax_credit": ZERO}
    items: list[dict[str, Any]] = []
    for declaration, category in declarations:
        eligible = money(proof_totals.get(declaration.id, 0)) if category.requires_proof else money(declaration.declared_amount)
        eligible = min(eligible, money(declaration.declared_amount))
        if money(category.annual_limit) > 0:
            eligible = min(eligible, money(category.annual_limit))
        totals[category.treatment] += eligible
        items.append({"declaration_id": declaration.id, "category_id": category.id, "code": category.code, "treatment": category.treatment, "eligible_amount": str(eligible)})
    return {"deduction": money(totals["tax_deduction"]), "credit": money(totals["tax_credit"]), "items": items}


async def reserve_benefit_claims(
    db: AsyncSession,
    *,
    run: PayrollRun,
    employee_id: int,
) -> list[dict[str, Any]]:
    rows = list((await db.execute(
        select(EmployeeBenefitClaim, EmployeeBenefitApplication, SalaryComponent)
        .join(EmployeeBenefitApplication, EmployeeBenefitApplication.id == EmployeeBenefitClaim.application_id)
        .join(SalaryComponent, SalaryComponent.id == EmployeeBenefitApplication.salary_component_id)
        .where(
            EmployeeBenefitClaim.organization_id == run.organization_id,
            EmployeeBenefitApplication.employee_id == employee_id,
            EmployeeBenefitApplication.status == "approved",
            EmployeeBenefitClaim.claim_date >= run.period_start,
            EmployeeBenefitClaim.claim_date <= run.period_end,
            EmployeeBenefitClaim.status.in_(("approved", "queued")),
            (EmployeeBenefitClaim.payroll_run_id.is_(None) | (EmployeeBenefitClaim.payroll_run_id == run.id)),
        )
        .order_by(EmployeeBenefitClaim.id)
        .with_for_update()
    )).all())
    result: list[dict[str, Any]] = []
    for claim, application, component in rows:
        claim.status = "queued"
        claim.payroll_run_id = run.id
        result.append({
            "claim_id": claim.id,
            "application_id": application.id,
            "component_id": component.id,
            "component_code": component.code,
            "component_name": component.name,
            "amount": str(money(claim.amount)),
            "taxable": component.is_taxable,
            "shi_subject": component.is_shi_subject,
            "non_taxable_allowance": component.is_non_taxable_allowance,
            "only_tax_impact": component.only_tax_impact,
            "account_id": component.account_id,
            "cost_center_id": component.cost_center_id,
        })
    return result


async def mark_run_benefits_paid(db: AsyncSession, run_id: int) -> None:
    claims = list((await db.execute(select(EmployeeBenefitClaim).where(
        EmployeeBenefitClaim.payroll_run_id == run_id,
        EmployeeBenefitClaim.status == "queued",
    ).with_for_update())).scalars().all())
    for claim in claims:
        claim.status = "paid"


async def validate_claim_balance(db: AsyncSession, application: EmployeeBenefitApplication, amount: Decimal) -> None:
    used = money(await db.scalar(select(func.coalesce(func.sum(EmployeeBenefitClaim.amount), 0)).where(
        EmployeeBenefitClaim.application_id == application.id,
        EmployeeBenefitClaim.status.in_(("approved", "queued", "paid")),
    )))
    if used + money(amount) > money(application.approved_amount):
        raise HTTPException(status_code=422, detail={
            "code": "payroll_benefit_claim_exceeds_balance",
            "available": str(max(ZERO, money(application.approved_amount) - used)),
        })


def grouped_benefit_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[int, dict[str, Any]] = {}
    for claim in claims:
        key = int(claim["component_id"])
        if key not in grouped:
            grouped[key] = {**claim, "amount": ZERO, "claim_ids": []}
        grouped[key]["amount"] += money(claim["amount"])
        grouped[key]["claim_ids"].append(claim["claim_id"])
    return [{**item, "amount": money(item["amount"])} for item in grouped.values()]

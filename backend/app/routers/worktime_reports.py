from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, require_roles
from app.core.roles import WORKTIME_REPORT_ROLES
from app.services.worktime_report_service import (
    REPORT_PAGE_SIZE,
    ReportFilters,
    csv_report,
    preview_report,
    report_options,
    report_summary,
    resolve_scope,
    xlsx_report,
)


router = APIRouter()
REPORT_ACCESS = require_roles(*WORKTIME_REPORT_ROLES)


def _filters(
    date_from: date,
    date_to: date,
    department: str | None,
    worker_id: int | None,
) -> ReportFilters:
    return ReportFilters(date_from=date_from, date_to=date_to, department=department, worker_id=worker_id)


@router.get("/options")
async def worktime_report_options(
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(REPORT_ACCESS),
):
    return await report_options(db, actor)


@router.get("/preview")
async def worktime_report_preview(
    date_from: date = Query(alias="from"),
    date_to: date = Query(alias="to"),
    department: str | None = Query(default=None, max_length=200),
    worker_id: int | None = Query(default=None, ge=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=REPORT_PAGE_SIZE, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(REPORT_ACCESS),
):
    filters = _filters(date_from, date_to, department, worker_id)
    scope = await resolve_scope(db, actor, filters)
    return await preview_report(db, filters, scope, page, page_size)


@router.get("/export")
async def worktime_report_export(
    date_from: date = Query(alias="from"),
    date_to: date = Query(alias="to"),
    department: str | None = Query(default=None, max_length=200),
    worker_id: int | None = Query(default=None, ge=1),
    format: Literal["csv", "xlsx"] = "csv",
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(REPORT_ACCESS),
):
    filters = _filters(date_from, date_to, department, worker_id)
    scope = await resolve_scope(db, actor, filters)
    summary = await report_summary(db, filters, scope)
    stem = f"worktime-report_{date_from.isoformat()}_{date_to.isoformat()}"
    if format == "csv":
        return StreamingResponse(
            csv_report(db, filters, scope, summary),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{stem}.csv"', "X-Content-Type-Options": "nosniff"},
        )
    buffer = await xlsx_report(db, filters, scope, summary)

    def chunks():
        try:
            while chunk := buffer.read(1024 * 1024):
                yield chunk
        finally:
            buffer.close()

    return StreamingResponse(
        chunks(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{stem}.xlsx"', "X-Content-Type-Options": "nosniff"},
    )

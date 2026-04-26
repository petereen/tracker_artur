import csv
import io
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import Answer, Employee, Question, SurveySession

router = APIRouter()


@router.get("")
async def list_answers(
    emp_id: Optional[int] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    q = select(SurveySession).order_by(SurveySession.date.desc())
    if emp_id:
        q = q.where(SurveySession.employee_id == emp_id)
    if date_from:
        q = q.where(SurveySession.date >= date_from)
    if date_to:
        q = q.where(SurveySession.date <= date_to)
    result = await db.execute(q)
    sessions = result.scalars().all()

    out = []
    for s in sessions:
        emp_r = await db.execute(select(Employee).where(Employee.id == s.employee_id))
        emp = emp_r.scalar_one_or_none()
        ans_r = await db.execute(
            select(Answer, Question)
            .join(Question, Answer.question_id == Question.id)
            .where(Answer.session_id == s.id)
            .order_by(Question.sort_order)
        )
        answers = ans_r.all()
        row = {
            "session_id": s.id,
            "employee_id": s.employee_id,
            "employee_name": emp.name if emp else "",
            "date": str(s.date),
            "status": s.status,
            "answers": [
                {
                    "question": a.Question.text,
                    "value": a.Answer.value_text or (str(int(a.Answer.value_numeric)) if a.Answer.value_numeric is not None else None),
                }
                for a in answers
            ],
        }
        out.append(row)
    return out


@router.get("/export")
async def export_answers(
    format: str = Query("csv"),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    result = await db.execute(
        select(SurveySession, Employee)
        .join(Employee, SurveySession.employee_id == Employee.id)
        .order_by(SurveySession.date.desc())
    )
    rows = result.all()

    questions_r = await db.execute(select(Question).order_by(Question.sort_order))
    questions = questions_r.scalars().all()

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        headers = ["Сотрудник", "Дата", "Статус"] + [q.text for q in questions]
        writer.writerow(headers)
        for session, emp in rows:
            ans_r = await db.execute(
                select(Answer).where(Answer.session_id == session.id)
            )
            answers = {a.question_id: a for a in ans_r.scalars().all()}
            row_data = [emp.name, str(session.date), session.status]
            for q in questions:
                a = answers.get(q.id)
                if a:
                    row_data.append(a.value_text or (str(int(a.value_numeric)) if a.value_numeric is not None else ""))
                else:
                    row_data.append("")
            writer.writerow(row_data)
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=answers.csv"},
        )

    # xlsx
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ответы"
    headers = ["Сотрудник", "Дата", "Статус"] + [q.text for q in questions]
    ws.append(headers)
    for session, emp in rows:
        ans_r = await db.execute(select(Answer).where(Answer.session_id == session.id))
        answers = {a.question_id: a for a in ans_r.scalars().all()}
        row_data = [emp.name, str(session.date), session.status]
        for q in questions:
            a = answers.get(q.id)
            if a:
                row_data.append(a.value_text or (int(a.value_numeric) if a.value_numeric is not None else ""))
            else:
                row_data.append("")
        ws.append(row_data)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=answers.xlsx"},
    )

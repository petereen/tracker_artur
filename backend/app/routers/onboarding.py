from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import ManagerSettings

router = APIRouter()

DEFAULT_TEMPLATE = """Привет, {имя}! 👋

Я — бот трекера активности отдела продаж.

Каждый день в {время} я буду присылать тебе короткий опрос из 5 вопросов — он займёт буквально 2–3 минуты.

Нажми /start, чтобы начать!"""


class OnboardingTemplate(BaseModel):
    message: str


@router.get("/template", response_model=OnboardingTemplate)
async def get_template(db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(ManagerSettings))
    s = result.scalar_one_or_none()
    message = s.onboarding_template if s and s.onboarding_template else DEFAULT_TEMPLATE
    return OnboardingTemplate(message=message)


@router.put("/template", status_code=200)
async def update_template(data: OnboardingTemplate, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(ManagerSettings))
    s = result.scalar_one_or_none()
    if s:
        s.onboarding_template = data.message
    else:
        db.add(ManagerSettings(onboarding_template=data.message))
    await db.commit()
    return {"ok": True}

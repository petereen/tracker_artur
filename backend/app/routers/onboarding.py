from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.tenancy import current_tenant_id, tenant_directory
from app.models.models import ManagerSettings
from app.services.manager_recipients import manager_settings_for

router = APIRouter()

DEFAULT_TEMPLATE = """Сайн байна уу, {нэр}! 👋

Би OYUNS Agent байна.

Өдөр бүр {цаг}-т танд 5 асуулттай богино асуулга илгээнэ. Бөглөхөд ердөө 2–3 минут зарцуулна.

Мөн та надаас даалгавар, өдрийн төлөвлөгөө, компаний мэдээлэл болон ажлын бичвэрийн талаар энгийнээр асууж болно.

/start командыг дарж эхлээрэй!"""


class OnboardingTemplate(BaseModel):
    message: str


async def _organization_id() -> int | None:
    return current_tenant_id() or await tenant_directory.primary_id()


@router.get("/template", response_model=OnboardingTemplate)
async def get_template(db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    s = await manager_settings_for(db, await _organization_id())
    message = s.onboarding_template if s and s.onboarding_template else DEFAULT_TEMPLATE
    return OnboardingTemplate(message=message)


@router.put("/template", status_code=200)
async def update_template(data: OnboardingTemplate, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    organization_id = await _organization_id()
    s = await manager_settings_for(db, organization_id)
    if s:
        s.onboarding_template = data.message
    else:
        db.add(ManagerSettings(organization_id=organization_id, onboarding_template=data.message))
    await db.commit()
    return {"ok": True}

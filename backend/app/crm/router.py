from fastapi import APIRouter

from app.crm.activities import router as activities_router
from app.crm.parties import router as parties_router
from app.crm.settings import router as settings_router

router = APIRouter()
router.include_router(settings_router)
router.include_router(parties_router)
router.include_router(activities_router)

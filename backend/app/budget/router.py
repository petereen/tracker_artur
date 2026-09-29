from fastapi import APIRouter

from app.budget.analysis import router as analysis_router
from app.budget.budgets import router as budgets_router
from app.budget.settings import router as settings_router

router = APIRouter()
router.include_router(settings_router)
router.include_router(budgets_router)
router.include_router(analysis_router)

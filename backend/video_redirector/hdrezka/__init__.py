from fastapi import APIRouter
from .hdrezka_routes import router as core_router
from .hdrezka_subtitle_proxy import router as subs_router

router = APIRouter()
router.include_router(core_router)
router.include_router(subs_router)
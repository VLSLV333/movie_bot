from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.video_redirector.services.mirror_selector import select_working_mirrors
from backend.video_redirector.services.mirror_search_service import search_for_movie_on_mirror
from backend.video_redirector.db.session import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

import logging
logger = logging.getLogger(__name__)

router = APIRouter()

class MirrorSearchRequest(BaseModel):
    query: str
    lang: str  # not used for now, but can be helpful later

@router.post("/mirror/search")
async def mirror_search(req: MirrorSearchRequest, db: AsyncSession = Depends(get_db)):
    try:
        mirrors = await select_working_mirrors(db=db, preferred_lang=req.lang, limit=10)
        if not mirrors:
            raise HTTPException(status_code=404, detail="No working mirrors found")

        first_mirror = mirrors[0]

        logger.info(f"[MirrorSearch] Selected: {first_mirror.name} (geo={first_mirror.geo}) for query: '{req.query}'")
        results = await search_for_movie_on_mirror(first_mirror.name, req.query)

        return [{
            "mirror": first_mirror.name,
            "geo_priority": first_mirror.geo,
            "results": results
        }]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")
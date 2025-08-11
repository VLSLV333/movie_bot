import hashlib
import traceback
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.video_redirector.services.mirror_selector import select_working_mirrors
from backend.video_redirector.services.mirror_search_service import search_for_movie_on_mirror
from backend.video_redirector.db.session import get_db_dep
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends
from backend.video_redirector.db.models import DownloadedFile
from sqlalchemy.future import select

import logging
logger = logging.getLogger(__name__)

router = APIRouter()

class MirrorSearchRequest(BaseModel):
    query: str
    fallback_query: str
    lang: str

@router.post("/mirror/search")
async def mirror_search(req: MirrorSearchRequest, db: AsyncSession = Depends(get_db_dep)):
    try:
        mirrors = await select_working_mirrors(db=db, preferred_lang=req.lang, limit=10)
        if not mirrors:
            raise HTTPException(status_code=404, detail="No working mirrors found")

        first_mirror = mirrors[0]

        logger.info(f"[MirrorSearch] Selected: {first_mirror.name} (geo={first_mirror.geo}) for query: '{req.query}', and fallback_query: '{req.fallback_query}'")
        results = await search_for_movie_on_mirror(first_mirror.name, req.query, req.fallback_query)

        for result in results:
            result["id"] = hashlib.sha256(result["url"].encode()).hexdigest()[:16]

        return [{
            "mirror": first_mirror.name,
            "geo_priority": first_mirror.geo,
            "results": results
        }]
    except Exception as e:
        traceback.print_exc()  # <-- ADD THIS LINE
        logger.exception(f"[MirrorSearch] Failed with exception: {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

@router.get("/downloaded_files/by_tmdb_id")
async def get_downloaded_file_by_tmdb_id(tmdb_id: int, db: AsyncSession = Depends(get_db_dep)):
    result = await db.execute(select(DownloadedFile).where(DownloadedFile.tmdb_id == tmdb_id))
    file = result.scalars().first()
    if not file:
        raise HTTPException(status_code=404, detail="Downloaded file not found")
    return {
        "tmdb_id": file.tmdb_id,
        "lang": file.lang,
        "dub": file.dub,
        "quality": file.quality,
        "tg_bot_token_file_owner": file.tg_bot_token_file_owner,
        "created_at": file.created_at.isoformat() if file.created_at else None,
        "movie_title": file.movie_title,
        "movie_poster": file.movie_poster,
        "movie_url": file.movie_url,
        "checked_by_admin": file.checked_by_admin,
        "session_name": file.session_name
    }
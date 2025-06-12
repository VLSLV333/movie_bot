import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from backend.video_redirector.db.session import get_db
from backend.video_redirector.db.crud_downloads import get_file_id, get_parts_for_downloaded_file, get_files_by_tmdb_and_lang
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter()

class FileIDCreateRequest(BaseModel):
    tmdb_id: int
    lang: str
    dub: str
    telegram_file_id: str
    quality: Optional[str] = "unknown"


@router.get("/all_movie_parts")
async def get_all_movie_parts(
    tmdb_id: int = Query(...),
    lang: str = Query(...),
    dub: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        file_entry = await get_file_id(db, tmdb_id, lang, dub)
        if not file_entry:
            logger.warning(f"File not found: tmdb_id={tmdb_id}, lang={lang}, dub={dub}")
            raise HTTPException(status_code=404, detail="File not found")

        parts = await get_parts_for_downloaded_file(db, file_entry.id)

        return {
            "tg_bot_token_file_owner": file_entry.tg_bot_token_file_owner,
            "parts": [
                {
                    "part_number": part.part_number,
                    "telegram_file_id": part.telegram_file_id
                }
                for part in parts
            ]
        }


    except Exception as e:
        logger.exception(f"Failed to get file_id: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/all_movie_parts_by_id")
async def get_all_movie_parts_by_id(
    db_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        parts = await get_parts_for_downloaded_file(db, db_id)
        return {
            "parts": [
                {
                    "part_number": part.part_number,
                    "telegram_file_id": part.telegram_file_id
                }
                for part in parts
            ]
        }


    except Exception as e:
        logger.exception(f"Failed to get file_id: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/all_db_dubs")
async def get_all_dubs_in_db_for_selected_movie_route(
    tmdb_id: int = Query(...),
    lang: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        entries = await get_files_by_tmdb_and_lang(db, tmdb_id, lang)
        logger.info(f"Found {len(entries)} entries for tmdb_id={tmdb_id}, lang={lang}")
        return [
            {
                "tmdb_id": entry.tmdb_id,
                "lang": entry.lang,
                "dub": entry.dub,
                "quality": entry.quality,
                "tg_bot_token_file_owner": entry.tg_bot_token_file_owner
            }
            for entry in entries
        ]
    except Exception as e:
        logger.exception(f"Failed to get files_id: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# @router.post("/file_id")
# async def save_file_id_route(
#     payload: FileIDCreateRequest,
#     db: AsyncSession = Depends(get_db),
# ):
#     try:
#         await save_file_id(
#             session=db,
#             tmdb_id=payload.tmdb_id,
#             lang=payload.lang,
#             dub=payload.dub,
#             telegram_file_id=payload.telegram_file_id,
#             quality=payload.quality,
#             tg_bot_token_file_owner=payload.tg_bot_token_file_owner
#         )
#         logger.info(f"Saved file_id for tmdb_id={payload.tmdb_id}, dub={payload.dub}, quality={payload.quality}")
#         return {"status": "saved"}
#     except Exception as e:
#         logger.exception(f"Failed to save file_id: {e}")
#         raise HTTPException(status_code=500, detail="Internal server error")
#
# @router.delete("/file_id")
# async def delete_file_id_route(
#     tmdb_id: int = Query(...),
#     lang: str = Query(...),
#     dub: str = Query(...),
#     db: AsyncSession = Depends(get_db),
# ):
#     try:
#         await delete_file_id(db, tmdb_id, lang, dub)
#         logger.info(f"Deleted file_id for tmdb_id={tmdb_id}, lang={lang}, dub={dub}")
#         return {"status": "deleted"}
#     except Exception as e:
#         logger.exception(f"Failed to delete file_id: {e}")
#         raise HTTPException(status_code=500, detail="Internal server error")
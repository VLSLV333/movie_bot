import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from backend.video_redirector.db.session import get_db
from backend.video_redirector.db.crud_downloads import get_file_id, get_parts_for_downloaded_file, get_files_by_tmdb_and_lang, cleanup_expired_file
from backend.video_redirector.utils.validate_tg_file_ids import validate_all_file_ids, validate_file_by_id
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

class CleanupExpiredFileRequest(BaseModel):
    telegram_file_id: str

class ValidationRequest(BaseModel):
    downloaded_file_id: Optional[int] = None  # If None, validate all files

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

    except HTTPException:
        # Re-raise HTTPExceptions (like 404) without modification
        raise
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

    except HTTPException:
        # Re-raise HTTPExceptions without modification
        raise
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
    except HTTPException:
        # Re-raise HTTPExceptions without modification
        raise
    except Exception as e:
        logger.exception(f"Failed to get files_id: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/cleanup-expired-file")
async def cleanup_expired_file_route(
    payload: CleanupExpiredFileRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Clean up expired Telegram file ID and all related database records.
    This endpoint is called by the delivery bot when it encounters
    'wrong file identifier' errors from Telegram.
    """
    try:
        logger.info(f"Attempting to cleanup expired file ID: {payload.telegram_file_id}")
        
        result = await cleanup_expired_file(db, payload.telegram_file_id)
        
        if result["success"]:
            logger.info(f"Successfully cleaned up expired file: {result}")
        else:
            logger.warning(f"Cleanup failed: {result}")
            
        return result
        
    except HTTPException:
        # Re-raise HTTPExceptions without modification
        raise
    except Exception as e:
        logger.exception(f"Failed to cleanup expired file ID {payload.telegram_file_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during cleanup")

@router.post("/validate-file-ids")
async def validate_file_ids_route(
    payload: ValidationRequest,
):
    """
    Manually trigger file ID validation for all files or a specific file
    """
    try:
        if payload.downloaded_file_id:
            logger.info(f"Manual file ID validation requested for file ID: {payload.downloaded_file_id}")
            stats = await validate_file_by_id(payload.downloaded_file_id)
            return {
                "message": f"File ID validation completed for file {payload.downloaded_file_id}",
                "stats": stats
            }
        else:
            logger.info("Manual file ID validation requested for all files")
            stats = await validate_all_file_ids()
            return {
                "message": "File ID validation completed for all files",
                "stats": stats
            }
        
    except HTTPException:
        # Re-raise HTTPExceptions without modification
        raise
    except Exception as e:
        logger.exception(f"Failed to validate file IDs: {e}")
        raise HTTPException(status_code=500, detail=f"File ID validation failed: {str(e)}")

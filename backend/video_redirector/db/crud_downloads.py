from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from backend.video_redirector.db.models import DownloadedFile, DownloadedFilePart
from datetime import datetime

QUALITY_PRIORITY = {
    "1080p": 4,
    "1080": 4,
    "720p": 3,
    "720": 3,
    "480p": 2,
    "480": 2,
    "360p": 1,
    "360": 1,
    "unknown": 0
}

async def get_file_id(session: AsyncSession, tmdb_id: int, lang: str, dub: str):
    stmt = select(DownloadedFile).where(
        DownloadedFile.tmdb_id == tmdb_id,
        DownloadedFile.lang == lang,
        DownloadedFile.dub == dub
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()

async def get_youtube_file_id(session: AsyncSession, tmdb_id: int, video_url: str):
    """Get existing YouTube file by tmdb_id and video_url"""
    stmt = select(DownloadedFile).where(
        DownloadedFile.tmdb_id == tmdb_id,
        DownloadedFile.movie_url == video_url
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()

async def get_files_by_tmdb_and_lang(session: AsyncSession, tmdb_id: int, lang: str):
    stmt = select(DownloadedFile).where(
        DownloadedFile.tmdb_id == tmdb_id,
        DownloadedFile.lang == lang
    )
    result = await session.execute(stmt)
    all_entries = result.scalars().all()

    best_per_dub = {}
    for entry in all_entries:
        current_best = best_per_dub.get(entry.dub)
        if not current_best or QUALITY_PRIORITY.get(entry.quality, 0) > QUALITY_PRIORITY.get(current_best.quality, 0):
            best_per_dub[entry.dub] = entry

    return list(best_per_dub.values())

async def get_parts_for_downloaded_file(session: AsyncSession, file_id: int):
    stmt = select(DownloadedFilePart).where(
        DownloadedFilePart.downloaded_file_id == file_id
    ).order_by(DownloadedFilePart.part_number)
    result = await session.execute(stmt)
    return result.scalars().all()

async def cleanup_expired_file(session: AsyncSession, telegram_file_id: str):
    """
    Clean up expired Telegram file ID and all related records.
    
    Args:
        session: Database session
        telegram_file_id: The expired Telegram file ID
        
    Returns:
        dict: Cleanup result with details about what was deleted
    """
    try:
        # First, find the DownloadedFilePart with the expired telegram_file_id
        stmt = select(DownloadedFilePart).where(
            DownloadedFilePart.telegram_file_id == telegram_file_id
        )
        result = await session.execute(stmt)
        file_part = result.scalar_one_or_none()
        
        if not file_part:
            return {
                "success": False,
                "message": f"No file part found with telegram_file_id: {telegram_file_id}",
                "deleted_parts": 0,
                "deleted_file": False
            }
        
        downloaded_file_id = file_part.downloaded_file_id
        
        # Delete all parts for this downloaded file
        delete_parts_stmt = delete(DownloadedFilePart).where(
            DownloadedFilePart.downloaded_file_id == downloaded_file_id
        )
        result = await session.execute(delete_parts_stmt)
        deleted_parts_count = result.rowcount
        
        # Delete the corresponding DownloadedFile record
        delete_file_stmt = delete(DownloadedFile).where(
            DownloadedFile.id == downloaded_file_id
        )
        result = await session.execute(delete_file_stmt)
        deleted_file_count = result.rowcount
        
        # Commit the transaction
        await session.commit()
        
        return {
            "success": True,
            "message": f"Successfully cleaned up expired file ID: {telegram_file_id}",
            "deleted_parts": deleted_parts_count,
            "deleted_file": deleted_file_count > 0,
            "downloaded_file_id": downloaded_file_id
        }
        
    except Exception as e:
        await session.rollback()
        raise e

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

# async def save_file_id(session: AsyncSession, tmdb_id: int, lang: str, dub: str, telegram_file_id: str, quality: str,tg_bot_token_file_owner:str):
#     file_entry = DownloadedFile(
#         tmdb_id=tmdb_id,
#         lang=lang,
#         dub=dub,
#         quality=quality,
#         created_at=datetime.utcnow(),
#         tg_bot_token_file_owner=tg_bot_token_file_owner
#     )
#     session.add(file_entry)
#     await session.commit()
#
#
# async def delete_file_id(session: AsyncSession, tmdb_id: int, lang: str, dub: str):
#     stmt = delete(DownloadedFile).where(
#         DownloadedFile.tmdb_id == tmdb_id,
#         DownloadedFile.lang == lang,
#         DownloadedFile.dub == dub
#     )
#     await session.execute(stmt)
#     await session.commit()


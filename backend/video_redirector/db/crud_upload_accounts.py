from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from backend.video_redirector.db.models import UploadAccountStats
from datetime import date, datetime
from typing import Optional, List

async def get_account_stats_by_session_name(db: AsyncSession, session_name: str) -> Optional[UploadAccountStats]:
    result = await db.execute(
        select(UploadAccountStats).where(UploadAccountStats.session_name == session_name)
    )
    return result.scalars().first()

async def create_or_get_account_stats(db: AsyncSession, session_name: str) -> UploadAccountStats:
    stats = await get_account_stats_by_session_name(db, session_name)
    if not stats:
        stats = UploadAccountStats(
            session_name=session_name,
            last_upload_date=date.today()
        )
        db.add(stats)
        await db.commit()
        await db.refresh(stats)
    return stats

async def increment_uploads(db: AsyncSession, session_name: str, error: Optional[str] = None) -> Optional[UploadAccountStats]:
    stats = await create_or_get_account_stats(db, session_name)
    today = date.today()
    if stats.last_upload_date != today:
        stats.today_uploads = 0
        stats.last_upload_date = today
    stats.total_uploads = (stats.total_uploads or 0) + 1
    stats.today_uploads = (stats.today_uploads or 0) + 1
    stats.last_upload_time = datetime.now()
    if error is not None:
        stats.last_error = error
    await db.commit()
    await db.refresh(stats)
    return stats

async def get_least_used_accounts_today(db: AsyncSession) -> List[UploadAccountStats]:
    result = await db.execute(
        select(UploadAccountStats).order_by(UploadAccountStats.today_uploads.asc())
    )
    return result.scalars().all()

async def update_last_error(db: AsyncSession, session_name: str, error: str) -> Optional[UploadAccountStats]:
    stats = await get_account_stats_by_session_name(db, session_name)
    if stats is not None:
        stats.last_error = error
        await db.commit()
        await db.refresh(stats)
    return stats

async def get_all_stats(db: AsyncSession) -> List[UploadAccountStats]:
    result = await db.execute(select(UploadAccountStats))
    return result.scalars().all()
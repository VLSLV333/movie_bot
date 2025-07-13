from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from backend.video_redirector.db.models import UploadAccountStats
from datetime import date, datetime
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)

async def get_account_stats_by_session_name(db: AsyncSession, session_name: str) -> Optional[UploadAccountStats]:
    try:
        result = await db.execute(
            select(UploadAccountStats).where(UploadAccountStats.session_name == session_name)
        )
        return result.scalars().first()
    except Exception as e:
        logger.error(f"Database error in get_account_stats_by_session_name: {e}")
        return None

async def create_or_get_account_stats(db: AsyncSession, session_name: str) -> UploadAccountStats:
    try:
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
    except Exception as e:
        logger.error(f"Database error in create_or_get_account_stats: {e}")
        # Try to rollback and return None
        try:
            await db.rollback()
        except:
            pass
        raise

async def increment_uploads(db: AsyncSession, session_name: str, error: Optional[str] = None) -> Optional[UploadAccountStats]:
    try:
        stats = await create_or_get_account_stats(db, session_name)
        today = date.today()
        
        # Use proper SQLAlchemy attribute access
        # Compare dates properly by getting the actual value
        current_last_upload_date = getattr(stats, 'last_upload_date', None)
        if current_last_upload_date != today:
            setattr(stats, 'today_uploads', 0)
            setattr(stats, 'last_upload_date', today)
        
        current_total = getattr(stats, 'total_uploads', 0) or 0
        current_today = getattr(stats, 'today_uploads', 0) or 0
        
        setattr(stats, 'total_uploads', current_total + 1)
        setattr(stats, 'today_uploads', current_today + 1)
        setattr(stats, 'last_upload_time', datetime.now())
        
        if error is not None:
            setattr(stats, 'last_error', error)
            
        await db.commit()
        await db.refresh(stats)
        return stats
    except Exception as e:
        logger.error(f"Database error in increment_uploads: {e}")
        # Try to rollback
        try:
            await db.rollback()
        except:
            pass
        return None

async def get_least_used_accounts_today(db: AsyncSession) -> List[UploadAccountStats]:
    try:
        result = await db.execute(
            select(UploadAccountStats).order_by(UploadAccountStats.today_uploads.asc())
        )
        return list(result.scalars().all())
    except Exception as e:
        logger.error(f"Database error in get_least_used_accounts_today: {e}")
        # Return empty list as fallback
        return []

async def update_last_error(db: AsyncSession, session_name: str, error: str) -> Optional[UploadAccountStats]:
    try:
        stats = await get_account_stats_by_session_name(db, session_name)
        if stats is not None:
            setattr(stats, 'last_error', error)
            await db.commit()
            await db.refresh(stats)
        return stats
    except Exception as e:
        logger.error(f"Database error in update_last_error: {e}")
        # Try to rollback
        try:
            await db.rollback()
        except:
            pass
        return None

async def get_all_stats(db: AsyncSession) -> List[UploadAccountStats]:
    try:
        result = await db.execute(select(UploadAccountStats))
        return list(result.scalars().all())
    except Exception as e:
        logger.error(f"Database error in get_all_stats: {e}")
        return []
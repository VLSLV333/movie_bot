from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, any_
from typing import Optional, List
from backend.video_redirector.db.models import Mirror
from typing import cast

async def select_working_mirrors(
    db: AsyncSession,
    preferred_lang: Optional[str] = None,
    limit: int = 10
) -> List[Mirror]:
    """
    Select best working mirrors from DB, prioritizing:
    - is_working = True
    - lang == preferred_lang
    - most recently checked (last_checked DESC)
    """
    stmt = select(Mirror).where(Mirror.is_working.is_(True))

    if preferred_lang:
        stmt = stmt.where(preferred_lang == any_(Mirror.lang))

    stmt = stmt.order_by(Mirror.last_checked.desc())

    result = await db.execute(stmt.limit(limit))
    mirrors = list(result.scalars().all())

    return mirrors


# Optional fallback: broaden search if none found with preferred_lang
async def select_fallback_mirrors(
    db: AsyncSession,
    limit: int = 10
) -> List[Mirror]:
    stmt = select(Mirror).where(Mirror.is_working.is_(True)).order_by(Mirror.last_checked.desc())
    result = await db.execute(stmt.limit(limit))
    return list(result.scalars().all())

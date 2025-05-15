from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from backend.video_redirector.db.models import Mirror
from typing import cast

# async def select_best_mirror(session: AsyncSession, geo: str) -> Optional[list[Mirror]]:
async def select_best_mirror(session: AsyncSession) -> Optional[list[Mirror]]:
    """
    Select the best working mirror for a given geo region.

    Prioritization logic:
    1. is_working == True
    2. geo match
    3. most recently checked
    """
    try:
        result = await session.execute(
            select(Mirror)
            # .where(Mirror.geo == geo, Mirror.is_working == True)
            .where(Mirror.is_working == True)
            .order_by(Mirror.last_checked.desc())
        )
        mirrors = cast(list[Mirror], result.scalars().all())
        return mirrors
    except Exception as e:
        print(f"[ERROR] Failed to select mirror: {e}")
        return None
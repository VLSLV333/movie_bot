import asyncio
from datetime import datetime, timezone
import httpx
import os
import time

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.future import select

from backend.video_redirector.db.models import Mirror
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("MOVIE_MIRRORS_DB_URL").replace("postgresql://", "postgresql+asyncpg://")
engine = create_async_engine(DATABASE_URL, echo=False)

SessionLocal: sessionmaker[AsyncSession] = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def check_url_is_alive(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(url)
            return response.status_code == 200
    except Exception as e:
        print(f'Error while checking if url is active, error:{e}')
        return False

async def check_with_retry(mirror: Mirror) -> tuple[Mirror, bool]:
    is_alive = await check_url_is_alive(mirror.url)
    if not is_alive:
        is_alive = await check_url_is_alive(mirror.url)  # Retry once
    return mirror, is_alive


async def run_health_check():
    start = time.time()

    async with SessionLocal() as session:
        result = await session.execute(select(Mirror))
        mirrors = result.scalars().all()

        print(f"🔍 Checking {len(mirrors)} mirrors...")

        tasks = [check_with_retry(m) for m in mirrors]
        results = await asyncio.gather(*tasks)

        passed, failed = 0, 0

        for mirror, is_alive in results:
            mirror.is_working = is_alive
            mirror.last_checked = datetime.now(timezone.utc)
            print(f"{'✅' if is_alive else '❌'} {mirror.url}")
            passed += is_alive
            failed += not is_alive

        await session.commit()
        duration = round(time.time() - start, 2)
        print(f"\n📊 Health Check Summary:")
        print(f"   ✅ Passed: {passed}")
        print(f"   ❌ Failed: {failed}")
        print(f"   ⏱ Duration: {duration}s")


if __name__ == "__main__":
    asyncio.run(run_health_check())

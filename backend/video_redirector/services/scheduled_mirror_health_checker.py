from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio
from datetime import datetime

from backend.video_redirector.services.mirror_health_checker import run_health_check

async def scheduled_job():
    print(f"🕒 [Job Start] Running health check at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    await run_health_check()

async def main():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(scheduled_job, "interval",hours=1)
    scheduler.start()
    print("✅ Scheduler started. Press Ctrl+C to stop.")

    # Keep the script running
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        print("👋 Scheduler stopped.")

if __name__ == "__main__":
    asyncio.run(main())
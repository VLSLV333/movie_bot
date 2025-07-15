import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from backend.video_redirector.utils.download_queue_manager import DownloadQueueManager
from backend.video_redirector.utils.pyrogram_acc_manager import (
    idle_client_cleanup, 
    initialize_proxy_on_startup,
    initialize_all_accounts_in_db,
    diagnose_account_distribution
)
from backend.video_redirector.utils.rate_limit_monitor import setup_pyrogram_rate_limit_monitoring
from backend.video_redirector.utils.validate_tg_file_ids import validate_all_file_ids
from backend.video_redirector.db.session import get_db

logger = logging.getLogger(__name__)

async def initialize_accounts_in_database():
    """Initialize all upload accounts in the database during startup"""
    logger.info("🔧 Initializing upload accounts in database...")
    
    try:
        async for db in get_db():
            # First diagnose current state
            diagnosis = await diagnose_account_distribution(db)
            
            if diagnosis.get("needs_initialization"):
                logger.info(f"🔧 Found {len(diagnosis.get('missing_accounts', []))} accounts missing from database")
                initialized_count = await initialize_all_accounts_in_db(db)
                logger.info(f"✅ Successfully initialized {initialized_count} accounts in database")
            else:
                logger.info("✅ All accounts already properly initialized in database")
            break  # Only need one database session
    except Exception as e:
        logger.error(f"❌ Error initializing accounts in database: {e}")
        # Don't fail startup, just log the error

async def scheduled_file_id_validation():
    """
    Scheduled task to validate file IDs at 4 AM Kyiv time every day
    """
    # Set up Kyiv timezone
    kyiv_tz = ZoneInfo('Europe/Kiev')
    
    while True:
        try:
            # Calculate next run time (4 AM Kyiv time)
            now_kyiv = datetime.now(kyiv_tz)
            next_run = now_kyiv.replace(hour=14, minute=47, second=0, microsecond=0)
            
            # If it's already past 4 AM today, schedule for tomorrow
            if next_run <= now_kyiv:
                next_run += timedelta(days=1)
            
            # Calculate seconds until next run
            seconds_until_next = (next_run - now_kyiv).total_seconds()
            
            logger.info(f"🕒 Next file ID validation scheduled for: {next_run.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            logger.info(f"⏰ Waiting {seconds_until_next:.0f} seconds until next validation...")
            
            # Wait until next run time
            await asyncio.sleep(seconds_until_next)
            
            logger.info("🕒 Starting scheduled file ID validation...")
            stats = await validate_all_file_ids()
            logger.info(f"✅ Scheduled file ID validation completed: {stats}")
            
        except Exception as e:
            logger.error(f"❌ Error in scheduled file ID validation: {e}")
            # If there's an error, wait 1 hour before retrying
            await asyncio.sleep(3600)  # 1 hour

async def start_background_workers():
    await initialize_proxy_on_startup()
    await initialize_accounts_in_database()  # Initialize accounts in database
    asyncio.create_task(DownloadQueueManager.queue_worker())
    asyncio.create_task(idle_client_cleanup())
    asyncio.create_task(scheduled_file_id_validation())  # Add file ID validation task
    setup_pyrogram_rate_limit_monitoring()

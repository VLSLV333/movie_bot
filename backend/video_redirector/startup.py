import asyncio
import logging
from backend.video_redirector.utils.download_queue_manager import DownloadQueueManager
from backend.video_redirector.utils.pyrogram_acc_manager import (
    idle_client_cleanup, 
    initialize_proxy_on_startup,
    initialize_all_accounts_in_db,
    diagnose_account_distribution
)
from backend.video_redirector.utils.rate_limit_monitor import setup_pyrogram_rate_limit_monitoring
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

async def start_background_workers():
    await initialize_proxy_on_startup()
    await initialize_accounts_in_database()  # Initialize accounts in database
    asyncio.create_task(DownloadQueueManager.queue_worker())
    asyncio.create_task(idle_client_cleanup())
    setup_pyrogram_rate_limit_monitoring()

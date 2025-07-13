#!/usr/bin/env python3
"""
Script to initialize all upload accounts in the database
This ensures proper load balancing by creating database records for all configured accounts
"""

import asyncio
import sys
import os
from pathlib import Path

# Add the backend directory to the Python path
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))

from backend.video_redirector.db.session import get_db
from backend.video_redirector.utils.pyrogram_acc_manager import (
    initialize_all_accounts_in_db,
    diagnose_account_distribution,
    UPLOAD_ACCOUNT_POOL
)
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    """Main function to initialize accounts and provide diagnostics"""
    logger.info("🚀 Starting upload account initialization...")
    
    # First, diagnose current state
    async for db in get_db():
        try:
            logger.info("=" * 60)
            logger.info("🔍 DIAGNOSING CURRENT ACCOUNT DISTRIBUTION")
            logger.info("=" * 60)
            
            diagnosis = await diagnose_account_distribution(db)
            
            if diagnosis.get("needs_initialization"):
                logger.info("=" * 60)
                logger.info("🔧 INITIALIZING MISSING ACCOUNTS")
                logger.info("=" * 60)
                
                initialized_count = await initialize_all_accounts_in_db(db)
                
                logger.info("=" * 60)
                logger.info("✅ POST-INITIALIZATION DIAGNOSIS")
                logger.info("=" * 60)
                
                # Run diagnosis again to confirm
                final_diagnosis = await diagnose_account_distribution(db)
                
                if final_diagnosis.get("needs_initialization"):
                    logger.error("❌ Some accounts still need initialization!")
                    return 1
                else:
                    logger.info("✅ All accounts successfully initialized!")
                    return 0
            else:
                logger.info("✅ All accounts are already properly initialized!")
                return 0
                
        except Exception as e:
            logger.error(f"❌ Error during account initialization: {e}")
            return 1

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("⏹️ Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        sys.exit(1) 
"""
!!! IMPORTANT: FOR THIS TO WORK, ADMIN MUST START CONVERSATION WITH BOT FIRST !!!

Telegram File ID Validation System

1. Uses aiogram Bot like delivery bot
2. Sends to admin chat for validation
3. Only treats "wrong file identifier" as expired
4. Uses same cleanup API as delivery bot
5. Proper timing: 1-2 sec between parts, 5-7 sec between files

"""
import logging
import random
import asyncio
import aiohttp
from typing import Dict, List
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone
import os

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from backend.video_redirector.db.models import DownloadedFile, DownloadedFilePart
from backend.video_redirector.db.session import get_db
from backend.video_redirector.utils.notify_admin import notify_admin

# Get delivery bot token from environment (same as delivery bot uses)
DELIVERY_BOT_TOKEN = os.getenv("DELIVERY_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

logger = logging.getLogger(__name__)

# Configuration
BATCH_SIZE = 20  # Number of files to process in each batch
BATCH_DELAY = 2  # Seconds to wait between batches
PART_DELAY_MIN = 1.0  # Minimum seconds between parts (per user requirement)
PART_DELAY_MAX = 2.0  # Maximum seconds between parts (per user requirement)
FILE_DELAY_MIN = 5.0  # Minimum seconds between files (per user requirement) 
FILE_DELAY_MAX = 7.0  # Maximum seconds between files (per user requirement)
VALIDATION_TIMEOUT = 10  # Seconds timeout for each file validation

async def clean_up_expired_file_id(telegram_file_id: str):
    """
    Call the backend API to clean up expired Telegram file ID (same as delivery bot)
    """
    session = None
    try:
        session = aiohttp.ClientSession()
        async with session.post(
            "https://moviebot.click/cleanup-expired-file",
            json={"telegram_file_id": telegram_file_id}
        ) as resp:
            if resp.status == 200:
                cleanup_result = await resp.json()
                logger.debug(f"Successfully cleaned up expired file ID {telegram_file_id}: {cleanup_result}")
                return cleanup_result
            else:
                logger.error(f"Failed to cleanup expired file ID {telegram_file_id}, status: {resp.status}")
                return None
    except Exception as e:
        logger.error(f"Exception while cleaning up expired file ID {telegram_file_id}: {e}")
        return None
    finally:
        if session:
            await session.close()

class FileIDValidator:
    """
    Validates Telegram file IDs by attempting to send them to admin chat using aiogram Bot
    (exactly like the delivery bot) and removes expired files from the database.
    """
    
    def __init__(self):
        self.stats = {
            "total_files_processed": 0,
            "valid_files": 0,
            "expired_files": 0,
            "errors": 0
        }
        self.bot = None
    
    async def _ensure_bot_ready(self) -> bool:
        """
        Initialize aiogram Bot (same as delivery bot uses)
        """
        if self.bot is None:
            if not DELIVERY_BOT_TOKEN:
                logger.error("❌ DELIVERY_BOT_TOKEN not set - cannot perform file ID validation")
                return False
            
            try:
                self.bot = Bot(
                    token=DELIVERY_BOT_TOKEN,
                    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
                )
                logger.debug("✅ Delivery bot initialized for validation")
                return True
            except Exception as e:
                logger.error(f"❌ Failed to initialize delivery bot: {e}")
                return False
        return True
    
    async def validate_all_files(self) -> Dict[str, int]:
        """
        Validate file IDs for all DownloadedFiles in the database
        """
        logger.debug("🔍 Starting file ID validation for all files")
        
        # Check if we have required tokens for validation
        if not DELIVERY_BOT_TOKEN:
            error_msg = "❌ DELIVERY_BOT_TOKEN not set - cannot perform file ID validation"
            logger.error(error_msg)
            await notify_admin(error_msg)
            return {"total_files_processed": 0, "valid_files": 0, "expired_files": 0, "errors": 1}
            
        if not ADMIN_CHAT_ID:
            error_msg = "❌ ADMIN_CHAT_ID not set - cannot perform file ID validation without test user"
            logger.error(error_msg)
            await notify_admin(error_msg)
            return {"total_files_processed": 0, "valid_files": 0, "expired_files": 0, "errors": 1}
        
        # Initialize bot
        if not await self._ensure_bot_ready():
            error_msg = "❌ Failed to initialize delivery bot for validation"
            await notify_admin(error_msg)
            return {"total_files_processed": 0, "valid_files": 0, "expired_files": 0, "errors": 1}
        
        logger.debug(f"📋 Using delivery bot for validation to admin chat: {ADMIN_CHAT_ID}")
        
        async for db in get_db():
            # Get total count first
            count_stmt = select(func.count(DownloadedFile.id))
            result = await db.execute(count_stmt)
            total_files = result.scalar() or 0
            
            if total_files == 0:
                logger.debug("📭 No files found in database to validate")
                await notify_admin("📭 File ID validation: No files found in database")
                return self.stats
            
            logger.debug(f"📊 Found {total_files} files to validate")
            
            # Process in batches
            offset = 0
            
            while offset < total_files:
                # Get batch of files (sorted by ID for consistent processing)
                stmt = select(DownloadedFile).order_by(DownloadedFile.id).offset(offset).limit(BATCH_SIZE)
                
                result = await db.execute(stmt)
                batch_files = list(result.scalars().all())
                
                batch_num = offset // BATCH_SIZE + 1
                total_batches = (total_files + BATCH_SIZE - 1) // BATCH_SIZE
                
                logger.debug(f"📦 Processing batch {batch_num}/{total_batches}: files {offset+1}-{min(offset+BATCH_SIZE, total_files)}")
                
                # Process this batch
                batch_stats = await self.process_file_batch(files=batch_files, db=db)
                
                # Update global stats
                self.stats["total_files_processed"] += len(batch_files)
                self.stats["valid_files"] += batch_stats["validated_files"]
                self.stats["expired_files"] += batch_stats["expired_files"]
                self.stats["errors"] += batch_stats["errors"]
                
                # Log progress
                progress = min((offset + len(batch_files)) / total_files * 100, 100.0)
                logger.debug(f"📈 Progress: {progress:.1f}% - Batch: {batch_stats}")
                
                # Move to next batch
                offset += BATCH_SIZE
                
                # Add delay between batches to be nice to Telegram
                if offset < total_files:
                    logger.debug(f"⏳ Waiting {BATCH_DELAY} seconds before next batch...")
                    await asyncio.sleep(BATCH_DELAY)
            
            break  # Only need one database session
        
        # Send final summary
        await self.send_validation_summary()
        return self.stats
    
    async def validate_file_by_id(self, downloaded_file_id: int) -> Dict[str, int]:
        """
        Validate file IDs for a specific DownloadedFile by ID
        """
        logger.debug(f"🔍 Starting validation for file ID: {downloaded_file_id}")
        
        # Initialize bot
        if not await self._ensure_bot_ready():
            error_msg = "❌ Failed to initialize delivery bot for validation"
            await notify_admin(error_msg)
            return {"validated_files": 0, "expired_files": 0, "errors": 1}
        
        async for db in get_db():
            # Get the specific file
            stmt = select(DownloadedFile).where(DownloadedFile.id == downloaded_file_id)
            result = await db.execute(stmt)
            downloaded_file = result.scalar_one_or_none()
            
            if not downloaded_file:
                logger.error(f"❌ File with ID {downloaded_file_id} not found in database")
                return {"validated_files": 0, "expired_files": 0, "errors": 1}
            
            # Process single file
            stats = await self.process_file_batch(files=[downloaded_file], db=db)
            
            # Update global stats
            self.stats["total_files_processed"] += 1
            self.stats["valid_files"] += stats["validated_files"]
            self.stats["expired_files"] += stats["expired_files"]
            self.stats["errors"] += stats["errors"]
            
            break
        
        await self.send_validation_summary()
        return stats
    
    async def process_file_batch(self, files: List[DownloadedFile], db: AsyncSession) -> Dict[str, int]:
        """
        Process a single batch of files using aiogram Bot (exactly like delivery bot)
        """
        validated_count = 0
        expired_count = 0
        error_count = 0
        
        # Ensure bot is ready and we have admin chat ID
        if not self.bot:
            logger.error("❌ Bot not initialized")
            return {"validated_files": 0, "expired_files": 0, "errors": len(files)}
        
        if not ADMIN_CHAT_ID:
            logger.error("❌ ADMIN_CHAT_ID not set")
            return {"validated_files": 0, "expired_files": 0, "errors": len(files)}
        
        admin_chat_id = int(ADMIN_CHAT_ID)  # Convert to int for aiogram
        
        for downloaded_file in files:
            # Get parts for this file
            parts_stmt = select(DownloadedFilePart).where(
                DownloadedFilePart.downloaded_file_id == downloaded_file.id
            ).order_by(DownloadedFilePart.part_number)
            
            parts_result = await db.execute(parts_stmt)
            parts = list(parts_result.scalars().all())
            
            # --- NEW LOGIC: Clean up YouTube Video files immediately ---
            if downloaded_file.movie_title == "YouTube Video":
                if parts:
                    cleanup_result = await clean_up_expired_file_id(str(parts[0].telegram_file_id))
                    if cleanup_result and cleanup_result.get('success') == True:
                        logger.debug(f"Deleted {cleanup_result['deleted_parts']} parts and file record: {cleanup_result['deleted_file']}")
                        expired_count += 1
                    else:
                        logger.error(f"❌ Failed to cleanup YouTube Video file ID through API")
                        error_count += 1
                else:
                    logger.debug(f"🗑️ No parts found for YouTube Video file ID {downloaded_file.id}, skipping.")
                    expired_count += 1
                continue
            # --- END NEW LOGIC ---

            file_expired = False
            
            # Check each part (same logic as delivery bot)
            for part in parts:
                try:
                    # Get the actual string value from the database column
                    file_id = str(part.telegram_file_id)
                    
                    # Use timeout to prevent hanging and send to admin chat like delivery bot
                    async with asyncio.timeout(VALIDATION_TIMEOUT):
                        await self.bot.send_video(
                            chat_id=admin_chat_id,  # Send to admin chat for validation
                            video=file_id,  # Use the string value
                            disable_notification=True  # Don't spam admin
                        )
                    
                    logger.debug(f"✅ File ID valid: {file_id[:20]}...")
                    
                    # Wait between parts (per user requirement: 1-2 seconds)
                    delay = random.uniform(PART_DELAY_MIN, PART_DELAY_MAX)
                    await asyncio.sleep(delay)
                    
                except asyncio.TimeoutError:
                    file_id = str(part.telegram_file_id)
                    logger.warning(f"⏰ Timeout checking file ID: {file_id[:20]}...")
                    error_count += 1
                    continue
                except TelegramBadRequest as e:
                    # Same error handling as delivery bot - only "wrong file identifier" means expired
                    file_id = str(part.telegram_file_id)
                    error_str = str(e).lower()
                    if "wrong file identifier" in error_str:
                        logger.warning(f"❌ File ID expired: {file_id[:20]}... (Error: {error_str})")
                        file_expired = True
                        break
                    else:
                        logger.warning(f"⚠️ Non-fatal error checking file ID {file_id[:20]}...: {e}")
                        error_count += 1
                        continue
                except Exception as e:
                    file_id = str(part.telegram_file_id)
                    logger.warning(f"⚠️ Unexpected error checking file ID {file_id[:20]}...: {e}")
                    error_count += 1
                    continue
            
            # Handle expired file (same cleanup as delivery bot)
            if file_expired and parts:
                # Use the same cleanup function as delivery bot
                cleanup_result = await clean_up_expired_file_id(str(parts[0].telegram_file_id))
                if cleanup_result and cleanup_result.get('success') == True:
                    logger.debug(f"🗑️ Successfully cleaned up file: {cleanup_result['message']}")
                    logger.debug(f"Deleted {cleanup_result['deleted_parts']} parts and file record: {cleanup_result['deleted_file']}")
                    expired_count += 1
                    await notify_admin(f"Expired file cleaned up during validation. "
                                     f"Deleted {cleanup_result['deleted_parts']} parts, file_id: {cleanup_result['downloaded_file_id']}")
                else:
                    logger.error(f"❌ Failed to cleanup expired file ID through API")
                    error_count += 1
            else:
                validated_count += 1
            
            # Wait between files (per user requirement: 5-7 seconds)
            delay = random.uniform(FILE_DELAY_MIN, FILE_DELAY_MAX)
            logger.debug(f"⏳ Waiting {delay:.1f}s before next file...")
            await asyncio.sleep(delay)
        
        return {
            "validated_files": validated_count,
            "expired_files": expired_count,
            "errors": error_count
        }
    
    async def send_validation_summary(self):
        """
        Send validation summary to admin
        """
        stats = self.stats
        
        if stats["total_files_processed"] == 0:
            return
        
        success_rate = (stats["valid_files"] / stats["total_files_processed"]) * 100 if stats["total_files_processed"] > 0 else 0
        
        summary = f"""
📊 **File ID Validation Summary**

📁 **Total Files:** {stats['total_files_processed']}
✅ **Valid Files:** {stats['valid_files']} ({success_rate:.1f}%)
❌ **Expired Files:** {stats['expired_files']}
⚠️ **Errors:** {stats['errors']}

🤖 **Method:** aiogram Bot (same as delivery bot)
📍 **Validation Target:** Admin chat {ADMIN_CHAT_ID}

🕒 **Completed at:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}
        """
        
        await notify_admin(summary.strip())
        logger.debug(f"📊 Validation summary sent: {stats}")
        
        # Close bot session to prevent resource leaks
        if self.bot:
            try:
                await self.bot.session.close()
                logger.debug("✅ Bot session closed successfully")
            except Exception as e:
                logger.warning(f"⚠️ Error closing bot session: {e}")

# Convenience functions for easy usage
async def validate_all_file_ids() -> Dict[str, int]:
    """
    Validate file IDs for all DownloadedFiles in the database
    """
    validator = FileIDValidator()
    return await validator.validate_all_files()

async def validate_file_by_id(downloaded_file_id: int) -> Dict[str, int]:
    """
    Validate file IDs for a specific DownloadedFile by ID
    """
    validator = FileIDValidator()
    return await validator.validate_file_by_id(downloaded_file_id)

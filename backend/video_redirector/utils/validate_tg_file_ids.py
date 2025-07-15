import logging
import random
import asyncio
from typing import Dict, List
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from backend.video_redirector.db.models import DownloadedFile, DownloadedFilePart
from backend.video_redirector.db.session import get_db
from backend.video_redirector.utils.pyrogram_acc_manager import UPLOAD_ACCOUNT_POOL
from backend.video_redirector.utils.notify_admin import notify_admin

logger = logging.getLogger(__name__)

# Configuration
BATCH_SIZE = 20  # Number of files to process in each batch
BATCH_DELAY = 2  # Seconds to wait between batches
FILE_CHECK_DELAY_MIN = 0.4  # Minimum seconds to wait between individual file checks
FILE_CHECK_DELAY_MAX = 3.0  # Maximum seconds to wait between individual file checks
MAX_RETRIES = 3  # Maximum retries for client connection issues
VALIDATION_TIMEOUT = 5  # Seconds timeout for each file validation (reduced from 30)

class FileIDValidator:
    """
    Validates Telegram file IDs by attempting to send them to saved messages
    and removes expired files from the database
    """
    
    def __init__(self):
        self.stats = {
            "total_files_processed": 0,
            "valid_files": 0,
            "expired_files": 0,
            "errors": 0,
            "sessions_processed": 0
        }
    
    async def validate_all_sessions(self) -> Dict[str, int]:
        """
        Validate file IDs for all session_names in the database
        """
        logger.info("🔍 Starting file ID validation for all sessions")
        
        async for db in get_db():
            # Get unique session_names from database
            stmt = select(DownloadedFile.session_name).distinct()
            result = await db.execute(stmt)
            session_names = [row[0] for row in result.fetchall() if row[0]]
            
            if not session_names:
                logger.info("📭 No files found in database to validate")
                await notify_admin("📭 File ID validation: No files found in database")
                return self.stats
            
            logger.info(f"🎯 Found {len(session_names)} sessions to validate: {session_names}")
            
            for session_name in session_names:
                try:
                    await self.validate_session_files(session_name, db)
                    self.stats["sessions_processed"] += 1
                except Exception as e:
                    logger.error(f"❌ Error validating session {session_name}: {e}")
                    self.stats["errors"] += 1
                    await notify_admin(f"❌ File ID validation failed for session {session_name}: {e}")
            
            break  # Only need one database session
        
        # Send final summary
        await self.send_validation_summary()
        return self.stats
    
    async def validate_session_files(self, session_name: str, db: AsyncSession) -> Dict[str, int]:
        """
        Validate file IDs for a specific session_name with batch processing
        """
        logger.info(f"🔍 Starting validation for session: {session_name}")
        
        # Get total count first
        count_stmt = select(func.count(DownloadedFile.id)).where(
            DownloadedFile.session_name == session_name
        )
        result = await db.execute(count_stmt)
        total_files = result.scalar() or 0  # Handle None case
        
        if total_files == 0:
            logger.info(f"📭 No files found for session_name: {session_name}")
            return {"validated_files": 0, "expired_files": 0, "errors": 0}
        
        logger.info(f"📊 Found {total_files} files to validate for {session_name}")
        
        # Find the account in the pool
        account = None
        
        # Check if UPLOAD_ACCOUNT_POOL is available
        if not hasattr(UPLOAD_ACCOUNT_POOL, '__iter__') or len(UPLOAD_ACCOUNT_POOL) == 0:
            logger.error(f"❌ UPLOAD_ACCOUNT_POOL is not available or empty")
            await notify_admin(f"❌ File ID validation: UPLOAD_ACCOUNT_POOL is not available for session {session_name}")
            return {"validated_files": 0, "expired_files": 0, "errors": 1}
        
        for acc in UPLOAD_ACCOUNT_POOL:
            if acc.session_name == session_name:
                account = acc
                break
        
        if not account:
            logger.error(f"❌ Account not found in pool for session_name: {session_name}")
            await notify_admin(f"❌ File ID validation: Account not found in pool for session {session_name}")
            return {"validated_files": 0, "expired_files": 0, "errors": 1}
        
        # Process in batches
        offset = 0
        session_stats = {"validated_files": 0, "expired_files": 0, "errors": 0}
        
        while offset < total_files:
            # Get batch of files
            stmt = select(DownloadedFile).where(
                DownloadedFile.session_name == session_name
            ).offset(offset).limit(BATCH_SIZE)
            
            result = await db.execute(stmt)
            batch_files = list(result.scalars().all())  # Convert to list
            
            batch_num = offset // BATCH_SIZE + 1
            total_batches = (total_files + BATCH_SIZE - 1) // BATCH_SIZE
            
            logger.info(f"📦 Processing batch {batch_num}/{total_batches}: files {offset+1}-{min(offset+BATCH_SIZE, total_files)}")
            
            # Process this batch
            batch_stats = await self.process_file_batch(files=batch_files, db=db, account=account)
            
            session_stats["validated_files"] += batch_stats["validated_files"]
            session_stats["expired_files"] += batch_stats["expired_files"]
            session_stats["errors"] += batch_stats["errors"]
            
            # Update global stats
            self.stats["total_files_processed"] += len(batch_files)
            self.stats["valid_files"] += batch_stats["validated_files"]
            self.stats["expired_files"] += batch_stats["expired_files"]
            self.stats["errors"] += batch_stats["errors"]
            
            # Log progress - Fix the calculation
            progress = min((offset + len(batch_files)) / total_files * 100, 100.0)
            logger.info(f"📈 Progress: {progress:.1f}% - Batch: {batch_stats}")
            
            # Move to next batch
            offset += BATCH_SIZE
            
            # Add delay between batches to be nice to Telegram
            if offset < total_files:
                logger.info(f"⏳ Waiting {BATCH_DELAY} seconds before next batch...")
                await asyncio.sleep(BATCH_DELAY)
        
        logger.info(f"✅ Completed validation for {session_name}: {session_stats}")
        return session_stats
    
    async def process_file_batch(self, files: List[DownloadedFile], db: AsyncSession, account) -> Dict[str, int]:
        """
        Process a single batch of files
        """
        validated_count = 0
        expired_count = 0
        error_count = 0
        
        # Start client for this batch
        client = None
        retry_count = 0
        
        while retry_count < MAX_RETRIES:
            try:
                client = await account.ensure_client_ready()
                if client:
                    break
                retry_count += 1
                logger.warning(f"⚠️ Failed to start client for {account.session_name}, retry {retry_count}/{MAX_RETRIES}")
                await asyncio.sleep(5)  # Wait before retry
            except Exception as e:
                retry_count += 1
                logger.error(f"❌ Error starting client for {account.session_name}: {e}")
                await asyncio.sleep(5)
        
        if not client:
            logger.error(f"❌ Failed to start client for {account.session_name} after {MAX_RETRIES} retries")
            return {"validated_files": 0, "expired_files": 0, "errors": len(files)}
        
        try:
            for downloaded_file in files:
                # Get parts for this file
                parts_stmt = select(DownloadedFilePart).where(
                    DownloadedFilePart.downloaded_file_id == downloaded_file.id
                ).order_by(DownloadedFilePart.part_number)
                
                parts_result = await db.execute(parts_stmt)
                parts = parts_result.scalars().all()
                
                file_expired = False
                
                # Check each part
                for part in parts:
                    try:
                        # Use timeout to prevent hanging
                        async with asyncio.timeout(VALIDATION_TIMEOUT):
                            await client.send_video(
                                chat_id="me",  # Saved messages
                                video=part.telegram_file_id,
                                disable_notification=True
                            )
                        
                        logger.debug(f"✅ File ID valid: {part.telegram_file_id[:20]}...")
                        
                        # Random delay between file checks to be nice to Telegram (more human-like)
                        delay = random.uniform(FILE_CHECK_DELAY_MIN, FILE_CHECK_DELAY_MAX)
                        await asyncio.sleep(delay)
                        
                    except asyncio.TimeoutError:
                        logger.warning(f"⏰ Timeout checking file ID: {part.telegram_file_id[:20]}...")
                        error_count += 1
                        continue
                    except Exception as e:
                        error_str = str(e).lower()
                        # Updated error detection based on actual Telegram error messages
                        if any(keyword in error_str for keyword in ["wrong file identifier", "file identifier", "invalid", "expired", "bad request"]):
                            logger.warning(f"❌ File ID expired: {part.telegram_file_id[:20]}... (Error: {error_str})")
                            file_expired = True
                            break
                        else:
                            logger.error(f"⚠️ Error checking file ID {part.telegram_file_id[:20]}...: {e}")
                            error_count += 1
                            continue
                
                # Handle expired file
                if file_expired:
                    # Delete parts and file
                    delete_parts_stmt = delete(DownloadedFilePart).where(
                        DownloadedFilePart.downloaded_file_id == downloaded_file.id
                    )
                    await db.execute(delete_parts_stmt)
                    
                    delete_file_stmt = delete(DownloadedFile).where(
                        DownloadedFile.id == downloaded_file.id
                    )
                    await db.execute(delete_file_stmt)
                    
                    expired_count += 1
                    logger.info(f"🗑️ Removed expired file from DB: {downloaded_file.movie_title} (ID: {downloaded_file.id})")
                else:
                    validated_count += 1
            
            # Commit batch changes
            await db.commit()
            
        except Exception as e:
            logger.error(f"❌ Error processing batch: {e}")
            await db.rollback()
            error_count += len(files)
        
        finally:
            # Stop the client
            try:
                await account.stop_client()
            except Exception as e:
                logger.warning(f"⚠️ Error stopping client: {e}")
        
        return {
            "validated_files": validated_count,
            "expired_files": expired_count,
            "errors": error_count
        }
    
    async def validate_specific_session(self, session_name: str) -> Dict[str, int]:
        """
        Validate file IDs for a specific session_name
        """
        logger.info(f"🔍 Starting validation for specific session: {session_name}")
        
        async for db in get_db():
            stats = await self.validate_session_files(session_name, db)
            break
        
        await self.send_validation_summary()
        return stats
    
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

🎯 **Sessions Processed:** {stats['sessions_processed']}
📁 **Total Files:** {stats['total_files_processed']}
✅ **Valid Files:** {stats['valid_files']} ({success_rate:.1f}%)
❌ **Expired Files:** {stats['expired_files']}
⚠️ **Errors:** {stats['errors']}

🕒 **Completed at:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}
        """
        
        await notify_admin(summary.strip())
        logger.info(f"📊 Validation summary sent: {stats}")

# Convenience functions for easy usage
async def validate_all_file_ids() -> Dict[str, int]:
    """
    Validate file IDs for all session_names in the database
    """
    validator = FileIDValidator()
    return await validator.validate_all_sessions()

async def validate_session_file_ids(session_name: str) -> Dict[str, int]:
    """
    Validate file IDs for a specific session_name
    """
    validator = FileIDValidator()
    return await validator.validate_specific_session(session_name)

# For testing and manual execution
if __name__ == "__main__":
    import asyncio
    
    async def main():
        # Example usage
        print("Starting file ID validation...")
        stats = await validate_all_file_ids()
        print(f"Validation complete: {stats}")
    
    asyncio.run(main())

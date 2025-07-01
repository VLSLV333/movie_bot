import os
import logging
import random
import time
from dotenv import load_dotenv
import math
import subprocess
import asyncio
from pyrogram.client import Client
from typing import Optional, Dict, Any
import shutil
import datetime

from backend.video_redirector.utils.notify_admin import notify_admin
from backend.video_redirector.utils.pyrogram_acc_manager import select_upload_account,increment_daily_stat,increment_total_stat

logger = logging.getLogger(__name__)
load_dotenv()

# Get environment variables
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
SESSION_NAME = os.getenv("SESSION_NAME")
TG_DELIVERY_BOT_USERNAME = os.getenv("TG_DELIVERY_BOT_USERNAME")

if not all([API_ID, API_HASH, SESSION_NAME, TG_DELIVERY_BOT_USERNAME]):
    raise ValueError("Missing required environment variables: API_ID, API_HASH, SESSION_NAME, or TG_DELIVERY_BOT_USERNAME")

# Type assertion after validation - we know these are not None due to the check above
API_ID = int(API_ID)  # type: ignore
API_HASH = str(API_HASH)  # type: ignore
SESSION_NAME = str(SESSION_NAME)  # type: ignore
TG_DELIVERY_BOT_USERNAME = str(TG_DELIVERY_BOT_USERNAME)  # type: ignore

bot_tokens = os.getenv("DELIVERY_BOT_TOKEN", "").split(",")
bot_tokens = [t.strip() for t in bot_tokens if t.strip()]

MAX_MB = 1400
PARTS_DIR = "downloads/parts"
# Use absolute path to match where your working test created the session file
SESSION_DIR = "/app/backend/session_files"
TG_USER_ID_TO_UPLOAD = 7841848291

# Upload configuration
UPLOAD_TIMEOUT = 420  # 7 minutes per part
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
MIN_DISK_SPACE_MB = 1000  # 1GB minimum free space

# Upload monitoring
_upload_stats = {
    "total_uploads": 0,
    "successful_uploads": 0,
    "failed_uploads": 0,
    "retry_count": 0,
    "total_bytes_uploaded": 0
}

# Create necessary directories
os.makedirs(PARTS_DIR, exist_ok=True)
os.makedirs(SESSION_DIR, exist_ok=True)

logger.info(f"📁 Current working directory: {os.getcwd()}")
logger.info(f"📁 Session directory: {SESSION_DIR}")
logger.info(f"📁 Parts directory: {PARTS_DIR}")

# Global client instance to avoid multiple connections
_client_instance = None
_client_lock = asyncio.Lock()
_client_last_used = 0
_client_ref_count = 0  # Track how many users are using the client
CLIENT_TIMEOUT = 300  # 5 minutes timeout

async def check_system_resources() -> Dict[str, Any]:
    """Check system resources before upload"""
    try:
        # Check disk space
        total, used, free = shutil.disk_usage(PARTS_DIR)
        free_mb = free / (1024 * 1024)
        
        # Check memory (simplified)
        with open('/proc/meminfo', 'r') as f:
            meminfo = f.read()
            available_mb = int([line for line in meminfo.split('\n') if 'MemAvailable:' in line][0].split()[1]) / 1024
        
        return {
            "disk_free_mb": free_mb,
            "memory_available_mb": available_mb,
            "disk_ok": free_mb > MIN_DISK_SPACE_MB,
            "memory_ok": available_mb > 500  # 500MB minimum
        }
    except Exception as e:
        logger.warning(f"⚠️ Could not check system resources: {e}")
        return {"disk_ok": True, "memory_ok": True}  # Assume OK if can't check

async def get_client():
    """Get or create a Pyrogram client instance with proper session handling"""
    global _client_instance, _client_last_used, _client_ref_count
    
    async with _client_lock:
        current_time = time.time()
        
        # Check if client exists and is healthy
        if _client_instance is not None:
            # Check if client is too old and should be refreshed
            if current_time - _client_last_used > CLIENT_TIMEOUT:
                logger.info("🔄 Client timeout reached, refreshing connection...")
                try:
                    await _client_instance.stop()
                except Exception as e:
                    logger.warning(f"⚠️ Error stopping old client: {e}")
                _client_instance = None
                _client_ref_count = 0  # Reset ref count when client is refreshed
        
        if _client_instance is None:
            session_path = os.path.join(SESSION_DIR, SESSION_NAME)
            logger.info(f"🔧 Creating Pyrogram client with session path: {session_path}")
            
            # Check if session file exists
            session_file = f"{session_path}.session"
            if os.path.exists(session_file):
                logger.info(f"✅ Session file exists: {session_file}")
            else:
                logger.warning(f"⚠️ Session file does not exist: {session_file}")
            
            try:
                _client_instance = Client(
                    session_path, 
                    api_id=API_ID, 
                    api_hash=API_HASH
                )
                await _client_instance.start()
                logger.info(f"✅ Pyrogram client started successfully")
            except Exception as e:
                logger.error(f"❌ Failed to create Pyrogram client: {e}")
                raise e
        
        _client_last_used = current_time
        _client_ref_count += 1
        logger.debug(f"📊 Client reference count: {_client_ref_count}")
        return _client_instance

async def release_client():
    """Release a reference to the client (called when upload completes)"""
    global _client_ref_count
    
    async with _client_lock:
        if _client_ref_count > 0:
            _client_ref_count -= 1
            logger.debug(f"📊 Client reference count: {_client_ref_count}")

async def cleanup_client():
    """Clean up the global Pyrogram client instance only if no one is using it"""
    global _client_instance, _client_last_used, _client_ref_count
    
    async with _client_lock:
        if _client_instance is not None and _client_ref_count == 0:
            try:
                await _client_instance.stop()
                logger.info("🔌 Pyrogram client stopped successfully")
            except Exception as e:
                logger.warning(f"⚠️ Error stopping Pyrogram client: {e}")
            finally:
                _client_instance = None
                _client_last_used = 0
                _client_ref_count = 0
        elif _client_ref_count > 0:
            logger.info(f"⚠️ Client cleanup skipped - {_client_ref_count} users still using it")

async def upload_part_to_tg_with_retry(file_path: str, task_id: str, part_num: int) -> Optional[str]:
    """Upload a part with retry logic and comprehensive error handling"""
    
    # Pre-upload checks
    resources = await check_system_resources()
    if not resources["disk_ok"]:
        error_msg = f"Insufficient disk space: {resources['disk_free_mb']:.1f}MB free"
        logger.error(f"[{task_id}] {error_msg}")
        await notify_admin(f"❌ [{task_id}] {error_msg}")
        await log_upload_metrics(task_id, 0, False, 0)
        return None
    
    if not resources["memory_ok"]:
        error_msg = f"Low memory: {resources['memory_available_mb']:.1f}MB available"
        logger.warning(f"[{task_id}] {error_msg}")
    
    file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
    retry_count = 0
    
    for attempt in range(MAX_RETRIES):
        try:
            logger.info(f"[{task_id}] Upload attempt {attempt + 1}/{MAX_RETRIES} for part {part_num}")
            
            # Check if file still exists
            if not os.path.exists(file_path):
                logger.error(f"[{task_id}] Part {part_num} file not found: {file_path}")
                await log_upload_metrics(task_id, file_size, False, retry_count)
                return None
            
            # Check file size
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                logger.error(f"[{task_id}] Part {part_num} file is empty: {file_path}")
                await log_upload_metrics(task_id, file_size, False, retry_count)
                return None
            
            idx, account = await select_upload_account()
            async with account.lock:
                account.busy = True
                try:
                    client = await account.get_client()
                    # Upload with timeout
                    start_time = datetime.datetime.now()
                    logger.info(f"[{task_id}] [Part {part_num}] Starting upload at {start_time:%Y-%m-%d %H:%M:%S}")
                    async with asyncio.timeout(UPLOAD_TIMEOUT):
                        msg = await client.send_video(
                            chat_id=str(TG_DELIVERY_BOT_USERNAME),
                            video=file_path,
                            caption=f"🎬 Part {part_num}",
                            disable_notification=True,
                            supports_streaming=True
                        )
                    end_time = datetime.datetime.now()
                    elapsed = (end_time - start_time).total_seconds()
                    logger.info(f"[{task_id}] [Part {part_num}] Finished upload at {end_time:%Y-%m-%d %H:%M:%S}, elapsed: {elapsed:.2f} seconds")
                    
                    if msg and msg.video:
                        file_id = msg.video.file_id
                        logger.info(f"✅ [{task_id}] Uploaded part {part_num} successfully. file_id: {file_id}")
                        await log_upload_metrics(task_id, file_size, True, retry_count)
                        increment_daily_stat(idx)
                        increment_total_stat(idx)
                        return file_id
                    else:
                        logger.error(f"[{task_id}] Upload succeeded but no video data returned")
                        await log_upload_metrics(task_id, file_size, False, retry_count)
                        return None
                
                except asyncio.TimeoutError:
                    retry_count += 1
                    logger.error(f"[{task_id}] Upload timeout for part {part_num} (attempt {attempt + 1})")
                    if attempt == MAX_RETRIES - 1:
                        await notify_admin(f"⏰ [{task_id}] Upload timeout for part {part_num} after {MAX_RETRIES} attempts")
                        await log_upload_metrics(task_id, file_size, False, retry_count)
                        return None
                
                except Exception as err:
                    retry_count += 1
                    error_type = type(err).__name__
                    logger.error(f"❌ [{task_id}] Upload failed for part {part_num} (attempt {attempt + 1}): {error_type}: {err}")
                    
                    # Handle specific error types
                    if "network" in str(err).lower() or "connection" in str(err).lower():
                        logger.info(f"[{task_id}] Network error detected, will retry...")
                    elif "rate" in str(err).lower() or "flood" in str(err).lower():
                        logger.warning(f"[{task_id}] Rate limit detected, waiting longer...")
                        await asyncio.sleep(RETRY_DELAY * (attempt + 1) * 2)  # Exponential backoff
                    elif "session" in str(err).lower() or "auth" in str(err).lower():
                        logger.error(f"[{task_id}] Session/auth error, cannot retry: {err}")
                        await notify_admin(f"🔐 [{task_id}] Session error for part {part_num}: {err}")
                        await log_upload_metrics(task_id, file_size, False, retry_count)
                        return None
                    else:
                        logger.warning(f"[{task_id}] Unknown error type: {error_type}")
                    
                    if attempt == MAX_RETRIES - 1:
                        await notify_admin(f"❌ [{task_id}] Upload failed for part {part_num} after {MAX_RETRIES} attempts: {err}")
                        await log_upload_metrics(task_id, file_size, False, retry_count)
                        return None
                
                    # Wait before retry
                    await asyncio.sleep(RETRY_DELAY * (attempt + 1))
        finally:
            account.busy = False
    
    await log_upload_metrics(task_id, file_size, False, retry_count)
    return None

async def upload_part_to_tg(file_path: str, task_id: str, part_num: int):
    """Wrapper for upload_part_to_tg_with_retry with cleanup"""
    try:
        return await upload_part_to_tg_with_retry(file_path, task_id, part_num)
    finally:
        # Always release the client reference when done
        await release_client()
        
        try:
            os.remove(file_path)
        except Exception as e:
            logger.warning(f"[{task_id}] Fail in finally block, file path - {file_path}, error: {e}")

def split_video_by_duration(file_path: str, task_id: str, num_parts: int, part_duration: float) -> list[str] | None:
    part_paths = []

    for i in range(num_parts):
        start_time = i * part_duration
        part_output = os.path.join(PARTS_DIR, f"{task_id}_part{i+1}.mp4")

        cmd = [
            "ffmpeg",
            "-ss", str(int(start_time)),
            "-i", file_path,
            "-t", str(int(part_duration)),
            "-c", "copy",
            part_output,
            "-y"
        ]

        logger.info(f"[{task_id}] Generating part {i+1}: {cmd}")
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        logger.debug(f"[{task_id}] ffprobe output: {result.stdout}")
        logger.debug(f"[{task_id}] ffprobe errors: {result.stderr}")
        logger.info(f"✅ [{task_id}] Part {i + 1} generated: {part_output}")

        if result.returncode != 0:
            logger.error(f"[{task_id}] FFmpeg failed on part {i+1}: {result.stderr}")
            return None


        part_paths.append(part_output)

    logger.info(f"✅ [{task_id}] All {num_parts} parts generated successfully.")
    return part_paths

async def check_size_upload_large_file(file_path: str, task_id: str):
    if not file_path:
        logger.error(f"[{task_id}] File path is None or empty")
        await notify_admin(f"[{task_id}] File path is None or empty. Check space on VPS or other error logs!")
        return None

    if not os.path.exists(file_path):
        logger.error(f"[{task_id}] File does not exist: {file_path}")
        await notify_admin(f"[{task_id}] File does not exist: {file_path}. Check space on VPS or other error logs!")
        return None

    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    logger.info(f"[{task_id}] Checking file: {file_path} ({file_size_mb:.2f} MB)")
    global bot_tokens
    tokens = bot_tokens[:]  # Copy to preserve original
    random.shuffle(tokens)

    for token in tokens:
        await asyncio.sleep(1.5)
        parts_result = []

        try:
            if file_size_mb <= MAX_MB:
                logger.info(f"[{task_id}] File is {round(file_size_mb)} MB — uploading as one part")
                file_id = await upload_part_to_tg(file_path, task_id, 1)
                if file_id:
                    logger.info(f"✅ [{task_id}] Single-part upload complete. file_id: {file_id}")
                    return {
                        "bot_token": token,
                        "parts": [{"part": 1, "file_id": file_id}]
                    }
                else:
                    logger.error(f"[{task_id}] Upload of single-part file failed.")
                    await notify_admin(f"[{task_id}] Upload of single-part file failed.")
                    continue

            logger.info(f"[{task_id}] File is {round(file_size_mb)} MB — splitting...")

            # Step 1: Get duration
            try:
                result = subprocess.run([
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    file_path
                ], capture_output=True, text=True, check=True)
                logger.debug(f"[{task_id}] ffprobe output: {result.stdout}")
                logger.debug(f"[{task_id}] ffprobe errors: {result.stderr}")
                if not result.stdout.strip():
                    raise ValueError("FFprobe returned empty duration.")
                duration = float(result.stdout.strip())
            except Exception as ero:
                logger.exception(f"[{task_id}] FFprobe failed")
                await notify_admin(f"❌ [Task {task_id}] Failed to get video duration: {ero}")
                continue

            num_parts = math.ceil(file_size_mb / MAX_MB)
            part_duration = duration / num_parts

            part_paths = split_video_by_duration(file_path, task_id, num_parts, part_duration)
            if not part_paths:
                await notify_admin(f"❌ [Task {task_id}] Failed to split movie during ffmpeg slicing.")
                continue

            for idx, part_path in enumerate(part_paths):
                try:
                    file_id = await upload_part_to_tg(part_path, task_id, idx + 1)
                    if not file_id:
                        raise RuntimeError(f"Upload failed for part {idx + 1}")
                    parts_result.append({"part": idx + 1, "file_id": file_id})
                except Exception as e:
                    logger.exception(f"[{task_id}] Error uploading part {idx + 1}")
                    await notify_admin(f"❌ [Task {task_id}] Part {idx + 1} upload failed: {e}")
                    break

            if len(parts_result) == num_parts:
                try:
                    os.remove(file_path)
                except Exception as errr:
                    logger.warning(f"[{task_id}] Couldn't clean up original movie file: {errr}")
                logger.info(f"[{task_id}] Upload successful with bot: {token[:10]}...")
                logger.info(f"✅ [{task_id}] Multipart upload complete. {len(parts_result)} parts uploaded.")
                return {
                    "bot_token": token,
                    "parts": parts_result
                }
            else:
                logger.warning(f"[{task_id}] Upload incomplete with bot {token[:10]}... Trying another...")
                await notify_admin(f"⚠️ [Task {task_id}] Upload incomplete with bot `{token[:10]}...`. Uploaded {len(parts_result)} of {num_parts}. Trying next...")

        except Exception as e:
            logger.exception(f"[{task_id}] Critical error with token {token[:10]}")
            await notify_admin(f"🧨 Critical failure while handling {task_id} with bot {token[:10]}:\n{e}")

    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            logger.info(f"[{task_id}] Cleaned up leftover movie file after failed upload.")
        except Exception as e:
            logger.warning(f"[{task_id}] Couldn't delete leftover .mp4: {e}")

    logger.critical(f"🆘 [{task_id}] All delivery bots failed. No movie uploaded.")
    await notify_admin(f"🆘 [{task_id}] All delivery bots failed. User can't get content.")
    return None

async def get_upload_stats() -> Dict[str, Any]:
    """Get upload statistics for monitoring"""
    return _upload_stats.copy()

async def log_upload_metrics(task_id: str, file_size: int, success: bool, retries: int = 0):
    """Log upload metrics for monitoring"""
    global _upload_stats
    
    _upload_stats["total_uploads"] += 1
    if success:
        _upload_stats["successful_uploads"] += 1
        _upload_stats["total_bytes_uploaded"] += file_size
    else:
        _upload_stats["failed_uploads"] += 1
    
    _upload_stats["retry_count"] += retries
    
    # Log metrics every 10 uploads
    if _upload_stats["total_uploads"] % 10 == 0:
        success_rate = (_upload_stats["successful_uploads"] / _upload_stats["total_uploads"]) * 100
        logger.info(f"📊 Upload Stats: {_upload_stats['total_uploads']} total, "
                   f"{success_rate:.1f}% success rate, "
                   f"{_upload_stats['retry_count']} total retries")

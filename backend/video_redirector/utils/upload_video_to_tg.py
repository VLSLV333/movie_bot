import os
import logging
import random
from dotenv import load_dotenv
import math
import subprocess
import asyncio
import time
import json
from typing import Dict, Any, Optional
import shutil
import datetime
from pyrogram.errors import FloodWait

from backend.video_redirector.utils.notify_admin import notify_admin
from backend.video_redirector.utils.pyrogram_acc_manager import (
    select_upload_account, 
    increment_daily_stat, 
    should_rotate_ip, 
    rotate_proxy_ip,
    acquire_upload_permission,
    release_upload_permission,
    register_upload_start,
    register_upload_end,
    increment_upload_counter,
    track_rate_limit_event
)
from backend.video_redirector.db.crud_upload_accounts import update_last_error

logger = logging.getLogger(__name__)
load_dotenv()

# Get environment variables
TG_DELIVERY_BOT_USERNAME = os.getenv("TG_DELIVERY_BOT_USERNAME")

if not all([TG_DELIVERY_BOT_USERNAME]):
    raise ValueError("Missing required environment variables: API_ID, API_HASH, SESSION_NAME, or TG_DELIVERY_BOT_USERNAME")

# Type assertion after validation - we know these are not None due to the check above
TG_DELIVERY_BOT_USERNAME = str(TG_DELIVERY_BOT_USERNAME)  # type: ignore

bot_tokens = os.getenv("DELIVERY_BOT_TOKEN", "").split(",")
bot_tokens = [t.strip() for t in bot_tokens if t.strip()]

MAX_MB = 1400
PARTS_DIR = "downloads/parts"
TG_USER_ID_TO_UPLOAD = 7841848291

# Upload configuration
UPLOAD_TIMEOUT = 600  # 10 minutes per part
MAX_RETRIES = 5  # Increased from 3
RETRY_DELAY = 5  # Increased from 2 seconds
MIN_DISK_SPACE_MB = 1000  # 1GB minimum free space
UPLOAD_DELAY = 3  
FLOOD_WAIT_BUFFER = 5  # Additional buffer time after FloodWait
MAX_FLOOD_WAIT_RETRIES = 10  # Maximum FloodWait retries per part

# Upload monitoring
_upload_stats = {
    "total_uploads": 0,
    "successful_uploads": 0,
    "failed_uploads": 0,
    "retry_count": 0,
    "total_bytes_uploaded": 0,
    "speed_stats": {
        "total_duration": 0,
        "total_mb_uploaded": 0,
        "average_speed_mbps": 0,
        "flood_wait_count": 0,
        "upload_times": []  # List of recent upload durations
    }
}

# Rate limiting detection
_rate_limit_detection_enabled = True

# Create necessary directories
os.makedirs(PARTS_DIR, exist_ok=True)

def report_rate_limit_event(wait_seconds: int, task_id: str = "unknown"):
    """Report a rate limiting event detected from logs or monitoring"""
    if not _rate_limit_detection_enabled:
        return
    
    # Track the rate limit event
    should_rotate = track_rate_limit_event(wait_seconds)
    
    if should_rotate:
        logger.warning(f"🚨 [{task_id}] Smart IP rotation should be triggered")
        # Note: The actual rotation will happen on the next upload check

async def log_upload_performance(task_id: str, file_size_mb: float, duration_seconds: float, 
                                flood_wait_count: int, account_name: str, success: bool):
    """
    Log upload performance statistics for real movie uploads
    """
    global _upload_stats
    
    if success:
        # Update speed statistics
        _upload_stats["speed_stats"]["total_duration"] += duration_seconds
        _upload_stats["speed_stats"]["total_mb_uploaded"] += file_size_mb
        _upload_stats["speed_stats"]["flood_wait_count"] += flood_wait_count
        
        # Calculate current speed
        current_speed_mbps = (file_size_mb * 8) / duration_seconds if duration_seconds > 0 else 0
        
        # Keep track of recent upload times (last 10)
        _upload_stats["speed_stats"]["upload_times"].append(duration_seconds)
        if len(_upload_stats["speed_stats"]["upload_times"]) > 10:
            _upload_stats["speed_stats"]["upload_times"].pop(0)
        
        # Calculate average speed
        total_duration = _upload_stats["speed_stats"]["total_duration"]
        total_mb = _upload_stats["speed_stats"]["total_mb_uploaded"]
        _upload_stats["speed_stats"]["average_speed_mbps"] = (total_mb * 8) / total_duration if total_duration > 0 else 0
        
        # Log performance
        logger.info(f"📊 [{task_id}] Upload Performance:")
        logger.info(f"   File Size: {file_size_mb:.1f} MB")
        logger.info(f"   Duration: {duration_seconds:.1f} seconds")
        logger.info(f"   Current Speed: {current_speed_mbps:.2f} Mbps")
        logger.info(f"   Average Speed: {_upload_stats['speed_stats']['average_speed_mbps']:.2f} Mbps")
        logger.info(f"   FloodWaits: {flood_wait_count}")
        logger.info(f"   Account: {account_name}")
        
        # Log every 5th upload with summary
        if _upload_stats["successful_uploads"] % 5 == 0:
            total_flood_waits = _upload_stats["speed_stats"]["flood_wait_count"]
            avg_speed = _upload_stats["speed_stats"]["average_speed_mbps"]
            
            logger.info(f"📈 Upload Performance Summary (Last {len(_upload_stats['speed_stats']['upload_times'])} uploads):")
            logger.info(f"   Total Uploads: {_upload_stats['successful_uploads']}")
            logger.info(f"   Average Speed: {avg_speed:.2f} Mbps")
            logger.info(f"   Total FloodWaits: {total_flood_waits}")
            logger.info(f"   FloodWait Rate: {total_flood_waits / _upload_stats['successful_uploads']:.2f} per upload")
            
            # Performance recommendations
            if total_flood_waits / _upload_stats['successful_uploads'] > 0.5:
                logger.warning(f"⚠️ High FloodWait rate detected - consider using proxies")
            elif avg_speed < 200:
                logger.warning(f"⚠️ Low upload speed detected - check network or consider proxies")
            else:
                logger.info(f"✅ Good performance - current setup is working well")
    else:
        # Log failed uploads with rate limiting info
        if flood_wait_count > 0:
            logger.warning(f"❌ [{task_id}] Upload failed with {flood_wait_count} FloodWaits (account: {account_name})")
            if flood_wait_count >= 5:
                logger.error(f"🚨 [{task_id}] Excessive FloodWaits detected - account {account_name} may be rate limited")
    
    # Update general stats
    _upload_stats["total_uploads"] += 1
    if success:
        _upload_stats["successful_uploads"] += 1
        _upload_stats["total_bytes_uploaded"] += int(file_size_mb * 1024 * 1024)
    else:
        _upload_stats["failed_uploads"] += 1

async def get_upload_performance_summary():
    """
    Get current upload performance summary
    """
    global _upload_stats
    
    total_uploads = _upload_stats["total_uploads"]
    successful_uploads = _upload_stats["successful_uploads"]
    failed_uploads = _upload_stats["failed_uploads"]
    
    speed_stats = _upload_stats["speed_stats"]
    total_flood_waits = speed_stats["flood_wait_count"]
    avg_speed = speed_stats["average_speed_mbps"]
    
    success_rate = (successful_uploads / total_uploads * 100) if total_uploads > 0 else 0
    flood_wait_rate = (total_flood_waits / successful_uploads) if successful_uploads > 0 else 0
    
    print({
        "total_uploads": total_uploads,
        "successful_uploads": successful_uploads,
        "failed_uploads": failed_uploads,
        "success_rate_percent": success_rate,
        "average_speed_mbps": avg_speed,
        "total_flood_waits": total_flood_waits,
        "flood_wait_rate": flood_wait_rate,
        "total_mb_uploaded": speed_stats["total_mb_uploaded"],
        "total_duration_hours": speed_stats["total_duration"] / 3600,
        "recent_upload_times": speed_stats["upload_times"][-5:] if speed_stats["upload_times"] else []
    })

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

async def rotate_account_on_failure(task_id: str, db, current_account):
    """Rotate to a different account when the current one is rate limited"""
    logger.info(f"[{task_id}] Rotating account from {current_account.session_name}")
    
    # Mark current account as recently used to avoid immediate reuse
    current_account.last_used = time.time()
    
    # Try to get a different account
    try:
        idx, new_account = await select_upload_account(db)
        if new_account.session_name != current_account.session_name:
            logger.info(f"[{task_id}] Rotated to account: {new_account.session_name}")
            return new_account
        else:
            logger.warning(f"[{task_id}] Could not rotate to different account, using same one")
            return current_account
    except Exception as e:
        logger.error(f"[{task_id}] Error rotating account: {e}")
        return current_account

async def get_video_metadata_for_upload(file_path: str, task_id: str) -> Optional[Dict[str, Any]]:
    """
    Extract video metadata (width, height, duration) for Telegram upload
    Returns metadata dict or None if extraction fails
    """
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-show_format",
            file_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
        
        if result.returncode != 0:
            logger.warning(f"⚠️ [{task_id}] ffprobe failed with return code {result.returncode}")
            return None
        
        metadata = json.loads(result.stdout)
        
        # Extract video stream information
        video_stream = None
        for stream in metadata.get("streams", []):
            if stream.get("codec_type") == "video":
                video_stream = stream
                break
        
        if not video_stream:
            logger.warning(f"⚠️ [{task_id}] No video stream found in file")
            return None
        
        # Extract dimensions
        width = video_stream.get("width")
        height = video_stream.get("height")
        
        # Extract duration (try from format first, then from stream)
        duration = None
        if "format" in metadata:
            duration_str = metadata["format"].get("duration")
            if duration_str:
                try:
                    duration = float(duration_str)
                except (ValueError, TypeError):
                    pass
        
        # If no duration from format, try from stream
        if duration is None:
            duration_str = video_stream.get("duration")
            if duration_str:
                try:
                    duration = float(duration_str)
                except (ValueError, TypeError):
                    pass
        
        # Validate extracted data
        if not width or not height:
            logger.warning(f"⚠️ [{task_id}] Could not extract valid dimensions: width={width}, height={height}")
            return None
        
        if width <= 0 or height <= 0:
            logger.warning(f"⚠️ [{task_id}] Invalid dimensions: {width}x{height}")
            return None
        
        # Calculate aspect ratio for validation
        aspect_ratio = width / height
        
        result_metadata = {
            "width": int(width),
            "height": int(height),
            "duration": int(duration) if duration else None,
            "aspect_ratio": round(aspect_ratio, 2)
        }

        return result_metadata
        
    except subprocess.TimeoutExpired:
        logger.error(f"❌ [{task_id}] ffprobe timeout (30s) while extracting metadata")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"❌ [{task_id}] Failed to parse ffprobe JSON output: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ [{task_id}] Error extracting video metadata: {e}")
        return None

async def upload_part_to_tg_with_retry(file_path: str, task_id: str, part_num: int, db, account):
    """Upload a part with retry logic and comprehensive error handling"""
    
    # Register this upload as active
    await register_upload_start(task_id)
    
    try:

        # Extract metadata for Telegram upload
        upload_metadata = await get_video_metadata_for_upload(file_path, task_id)
        if upload_metadata:
            logger.info(f"📤 [{task_id}] Will send to Telegram: {upload_metadata['width']}x{upload_metadata['height']}, duration: {upload_metadata['duration']}s")
        else:
            logger.warning(f"⚠️ [{task_id}] Could not extract metadata for upload - Telegram may receive incorrect dimensions")
        
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
        file_size_mb = file_size / (1024 * 1024)
        retry_count = 0
        flood_wait_count = 0
        upload_start_time = time.time()
        
        for attempt in range(MAX_RETRIES):
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
            
            async with account.lock:
                account.busy = True
                try:
                    client = await account.ensure_client_ready()
                    
                    # Add null check for client
                    if client is None:
                        logger.error(f"❌ [{task_id}] Client initialization failed for account {account.session_name}")
                        logger.error(f"   Account state - Busy: {account.busy}, Last used: {account.last_used}")
                        logger.error(f"   Client state - Client: {account.client}, Last creation: {account.last_client_creation}")
                        
                        await notify_admin(f"🔐 [{task_id}] Client initialization failed for account {account.session_name}")
                        await update_last_error(db, account.session_name, "Client initialization failed")
                        await log_upload_metrics(task_id, file_size, False, retry_count)
                        
                        # Log failed upload
                        total_duration = time.time() - upload_start_time
                        await log_upload_performance(task_id, file_size_mb, total_duration, flood_wait_count, account.session_name, False)
                        
                        return None
                    
                    logger.info(f"✅ [{task_id}] Client ready for {account.session_name}")
                    
                    # Upload with timeout
                    start_time = datetime.datetime.now()
                    logger.info(f"[{task_id}] [Part {part_num}] Starting upload at {start_time:%Y-%m-%d %H:%M:%S}")
                    
                    # Prepare send_video parameters
                    send_video_params = {
                        "chat_id": str(TG_DELIVERY_BOT_USERNAME),
                        "video": file_path,
                        "caption": "video",
                        "disable_notification": True,
                        "supports_streaming": True
                    }
                    
                    # Add metadata if available
                    if upload_metadata:
                        send_video_params["width"] = upload_metadata["width"]
                        send_video_params["height"] = upload_metadata["height"]
                        if upload_metadata["duration"]:
                            send_video_params["duration"] = upload_metadata["duration"]
                        logger.info(f"📐 [{task_id}] Sending with metadata: {upload_metadata['width']}x{upload_metadata['height']}, duration: {upload_metadata['duration']}s")
                    else:
                        logger.warning(f"⚠️ [{task_id}] Sending without metadata - Telegram will auto-detect dimensions")
                    
                    async with asyncio.timeout(UPLOAD_TIMEOUT):
                        msg = await client.send_video(**send_video_params)
                        
                    end_time = datetime.datetime.now()
                    elapsed = (end_time - start_time).total_seconds()
                    logger.info(f"[{task_id}] [Part {part_num}] Finished upload at {end_time:%Y-%m-%d %H:%M:%S}, elapsed: {elapsed:.2f} seconds")

                    if msg and msg.video:
                        file_id = msg.video.file_id
                        logger.info(f"✅ [{task_id}] Uploaded part {part_num} successfully. file_id: {file_id}")
                        
                        await log_upload_metrics(task_id, file_size, True, retry_count)
                        await increment_daily_stat(db, account.session_name)
                        
                        # Increment upload counter for IP rotation
                        increment_upload_counter()
                        
                        # Check if we should rotate proxy IP
                        if should_rotate_ip():
                            logger.info(f"🔄 [{task_id}] Rotating proxy IP after successful upload")
                            await rotate_proxy_ip()
                        
                        # Log performance statistics
                        total_duration = time.time() - upload_start_time
                        await log_upload_performance(task_id, file_size_mb, total_duration, flood_wait_count, account.session_name, True)
                        await get_upload_performance_summary()
                        return file_id
                    else:
                        logger.error(f"[{task_id}] Upload succeeded but no video data returned")
                        await log_upload_metrics(task_id, file_size, False, retry_count)
                        
                        # Log failed upload
                        total_duration = time.time() - upload_start_time
                        await log_upload_performance(task_id, file_size_mb, total_duration, flood_wait_count, account.session_name, False)
                        
                        return None

                except FloodWait as e:
                    flood_wait_count += 1
                    wait_time = int(str(e.value)) + FLOOD_WAIT_BUFFER
                    logger.warning(f"[{task_id}] FloodWait for part {part_num}: waiting {wait_time} seconds")
                    await notify_admin(f"⏰ [{task_id}] FloodWait for part {part_num} (account: {account.session_name}): waiting {wait_time} seconds")
                    
                    # Track the error in database
                    await update_last_error(db, account.session_name, f"FloodWait: {wait_time}s wait")
                    
                    # Stop the client to prevent further rate limiting
                    await account.stop_client()
                    
                    # If we've hit multiple FloodWaits, try rotating accounts
                    if flood_wait_count >= 5:
                        logger.info(f"[{task_id}] Multiple FloodWaits detected, attempting account rotation")
                        new_account = await rotate_account_on_failure(task_id, db, account)
                        if new_account.session_name != account.session_name:
                            account = new_account
                            logger.info(f"[{task_id}] Switched to account: {account.session_name}")
                            # Reset flood wait count for the new account
                            flood_wait_count = 0
                    
                    # Wait for the specified time plus buffer
                    await asyncio.sleep(wait_time)
                    
                    # If we've hit too many FloodWaits, stop retrying
                    if flood_wait_count >= MAX_FLOOD_WAIT_RETRIES:
                        logger.error(f"[{task_id}] Too many FloodWaits ({flood_wait_count}) for part {part_num}, stopping retries")
                        await notify_admin(f"🚫 [{task_id}] Too many FloodWaits for part {part_num} (account: {account.session_name})")
                        
                        # Track the error in database
                        await update_last_error(db, account.session_name, f"Too many FloodWaits: {flood_wait_count} retries exceeded")
                        
                        await log_upload_metrics(task_id, file_size, False, retry_count)
                        
                        # Log failed upload
                        total_duration = time.time() - upload_start_time
                        await log_upload_performance(task_id, file_size_mb, total_duration, flood_wait_count, account.session_name, False)
                        
                        return None
                    
                    # Continue with retry
                    continue

                except asyncio.TimeoutError:
                    retry_count += 1
                    logger.error(f"[{task_id}] Upload timeout for part {part_num} (attempt {attempt + 1})")
                    if attempt == MAX_RETRIES - 1:
                        await notify_admin(f"⏰ [{task_id}] Upload timeout for part {part_num} after {MAX_RETRIES} attempts")
                        
                        # Track the error in database
                        await update_last_error(db, account.session_name, f"Upload timeout after {MAX_RETRIES} attempts")
                        
                        await log_upload_metrics(task_id, file_size, False, retry_count)
                        
                        # Log failed upload
                        total_duration = time.time() - upload_start_time
                        await log_upload_performance(task_id, file_size_mb, total_duration, flood_wait_count, account.session_name, False)
                        
                        return None

                except Exception as err:
                    retry_count += 1
                    error_type = type(err).__name__
                    logger.error(f"❌ [{task_id}] Upload failed for part {part_num} (attempt {attempt + 1}): {error_type}: {err}")

                    # 🔍 ENHANCED DIAGNOSTICS: Detailed error classification
                    if "database is locked" in str(err).lower() or "OperationalError" in error_type:
                        logger.warning(f"🔒 [{task_id}] Database lock detected, waiting longer...")
                        logger.warning(f"   Error details: {error_type} - {err}")
                        logger.warning(f"   Account: {account.session_name}")
                        logger.warning(f"   Attempt: {attempt + 1}/{MAX_RETRIES}")
                        
                        # Log database pool status (removed due to type issues)
                        logger.warning(f"   Database lock detected, pool status unavailable")
                        
                        await asyncio.sleep(RETRY_DELAY * (attempt + 1) * 3)  # Longer delay for DB issues
                        continue
                    elif "network" in str(err).lower() or "connection" in str(err).lower():
                        logger.info(f"[{task_id}] Network error detected, will retry...")
                    elif "rate" in str(err).lower() or "flood" in str(err).lower():
                        logger.warning(f"[{task_id}] Rate limit detected, waiting longer...")
                        await asyncio.sleep(RETRY_DELAY * (attempt + 1) * 2)  # Exponential backoff
                        await account.stop_client()
                    elif "session" in str(err).lower() or "auth" in str(err).lower():
                        logger.error(f"[{task_id}] Session/auth error, cannot retry: {err}")
                        await notify_admin(f"🔐 [{task_id}] Session error for part {part_num}: {err}")
                        
                        # Track the error in database
                        await update_last_error(db, account.session_name, f"Session/Auth error: {error_type}: {err}")
                        
                        await log_upload_metrics(task_id, file_size, False, retry_count)
                        await account.stop_client()
                        
                        # Log failed upload
                        total_duration = time.time() - upload_start_time
                        await log_upload_performance(task_id, file_size_mb, total_duration, flood_wait_count, account.session_name, False)
                        
                        return None
                    else:
                        logger.warning(f"[{task_id}] Unknown error type: {error_type}")

                    if attempt == MAX_RETRIES - 1:
                        await notify_admin(f"❌ [{task_id}] Upload failed for part {part_num} after {MAX_RETRIES} attempts: {err}")
                        
                        # Track the error in database
                        await update_last_error(db, account.session_name, f"Upload failed after {MAX_RETRIES} attempts: {error_type}: {err}")
                        
                        await log_upload_metrics(task_id, file_size, False, retry_count)
                        
                        # Log failed upload
                        total_duration = time.time() - upload_start_time
                        await log_upload_performance(task_id, file_size_mb, total_duration, flood_wait_count, account.session_name, False)
                        
                        return None

                    # Wait before retry
                    await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                finally:
                    account.busy = False
        
        await log_upload_metrics(task_id, file_size, False, retry_count)
        
        # Log failed upload after all retries
        total_duration = time.time() - upload_start_time
        await log_upload_performance(task_id, file_size_mb, total_duration, flood_wait_count, account.session_name, False)
        
        return None
    finally:
        # Always register upload end, regardless of success/failure
        await register_upload_end(task_id)

async def upload_part_to_tg(file_path: str, task_id: str, part_num: int, db, account):
    """Wrapper for upload_part_to_tg_with_retry with cleanup"""
    try:
        return await upload_part_to_tg_with_retry(file_path, task_id, part_num, db, account)
    finally:
        try:
            os.remove(file_path)
        except Exception as e:
            logger.warning(f"[{task_id}] Fail in finally block, file path - {file_path}, error: {e}")

async def split_video_by_duration(file_path: str, task_id: str, num_parts: int, part_duration: float) -> list[str] | None:
    """
    Split video by duration with improved error handling and mobile compatibility
    """
    part_paths = []
    
    try:
        # Check if source file exists and is readable
        if not os.path.exists(file_path):
            logger.error(f"❌ [{task_id}] Source file doesn't exist: {file_path}")
            return None
        
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            logger.error(f"❌ [{task_id}] Source file is empty: {file_path}")
            return None
        
        logger.info(f"📂 [{task_id}] Splitting {file_size / (1024*1024):.1f}MB file into {num_parts} parts")
        
        for i in range(num_parts):
            start_time = i * part_duration
            part_output = os.path.join(PARTS_DIR, f"{task_id}_part{i+1}.mp4")
            
            # Remove existing part if it exists
            if os.path.exists(part_output):
                try:
                    os.remove(part_output)
                except Exception as e:
                    logger.warning(f"⚠️ [{task_id}] Couldn't remove existing part {i+1}: {e}")
            
            # Simple stream copy since mobile compatibility is already handled
            cmd = [
                "ffmpeg",
                "-ss", str(int(start_time)),
                "-i", file_path,
                "-t", str(int(part_duration)),
                "-c", "copy",  # Just copy, no re-processing
                "-avoid_negative_ts", "make_zero",
                "-movflags", "+faststart",
                "-y",
                part_output
            ]
            
            logger.info(f"🎬 [{task_id}] Generating part {i+1}/{num_parts} (start: {int(start_time)}s, duration: {int(part_duration)}s)")
            
            # Run FFmpeg with timeout
            try:
                start_time_actual = time.time()
                result = subprocess.run(
                    cmd, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE, 
                    text=True,
                    timeout=300  # 5 minute timeout per part
                )
                elapsed_time = time.time() - start_time_actual
                
                if result.returncode != 0:
                    logger.warning(f"⚠️ [{task_id}] FFmpeg failed on part {i+1} (return code: {result.returncode})")
                    logger.warning(f"FFmpeg stderr: {result.stderr}")
                    
                    # Since we're just doing stream copy, failure means the source file has issues
                    logger.error(f"❌ [{task_id}] Stream copy failed for part {i+1} - source file may be corrupted")
                    logger.error(f"FFmpeg stderr: {result.stderr}")
                    logger.error(f"FFmpeg command: {' '.join(cmd)}")
                    
                    # Clean up failed parts
                    for cleanup_path in part_paths:
                        try:
                            if os.path.exists(cleanup_path):
                                os.remove(cleanup_path)
                        except Exception as e:
                            logger.warning(f"⚠️ [{task_id}] Couldn't clean up {cleanup_path}: {e}")
                    
                    return None
                
                # Verify part was created successfully
                if not os.path.exists(part_output):
                    logger.error(f"❌ [{task_id}] Part {i+1} output file not created: {part_output}")
                    return None
                
                part_size = os.path.getsize(part_output)
                if part_size == 0:
                    logger.error(f"❌ [{task_id}] Part {i+1} is empty: {part_output}")
                    return None
                
                logger.info(f"✅ [{task_id}] Part {i+1} generated: {part_output} ({part_size / (1024*1024):.1f}MB) in {elapsed_time:.1f}s")
                
                part_paths.append(part_output)
                
            except subprocess.TimeoutExpired:
                logger.error(f"❌ [{task_id}] FFmpeg timeout on part {i+1} (5 minutes)")
                return None
            except Exception as e:
                logger.error(f"❌ [{task_id}] Unexpected error generating part {i+1}: {e}")
                return None
        
        logger.info(f"✅ [{task_id}] All {num_parts} parts generated successfully.")
        return part_paths
    
    except Exception as e:
        logger.error(f"❌ [{task_id}] Critical error in split_video_by_duration: {e}")
        
        # Clean up any partial parts
        for cleanup_path in part_paths:
            try:
                if os.path.exists(cleanup_path):
                    os.remove(cleanup_path)
            except Exception as cleanup_e:
                logger.warning(f"⚠️ [{task_id}] Couldn't clean up {cleanup_path}: {cleanup_e}")
        
        return None

async def check_size_upload_large_file(file_path: str, task_id: str, db):
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
            # Acquire upload permission (waits if rotation is in progress)
            await acquire_upload_permission()
            
            try:
                # Select a single Pyrogram account for this video
                idx, account = await select_upload_account(db)
                logger.info(f"[{task_id}] Selected account: {account.session_name}")
                
                if file_size_mb <= MAX_MB:
                    logger.info(f"[{task_id}] File is {round(file_size_mb)} MB — uploading as one part")
                    file_id = await upload_part_to_tg(file_path, task_id, 1, db, account)
                    if file_id:
                        logger.info(f"✅ [{task_id}] Single-part upload complete. file_id: {file_id}")
                        return {
                            "bot_token": token,
                            "parts": [{"part": 1, "file_id": file_id}]
                        }
                    else:
                        logger.error(f"[{task_id}] Upload of single-part file failed.")
                        await notify_admin(f"[{task_id}] Upload of single-part file failed with account {account.session_name}.")
                        # Try with a different account next time
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

                part_paths = await split_video_by_duration(file_path, task_id, num_parts, part_duration)
                if not part_paths:
                    await notify_admin(f"❌ [Task {task_id}] Failed to split movie during ffmpeg slicing.")
                    continue

                # Upload parts sequentially with delays to avoid rate limits
                for idx, part_path in enumerate(part_paths or []):
                    try:
                        # Add delay between uploads to avoid rate limits
                        if idx > 0:
                            logger.info(f"[{task_id}] Waiting {UPLOAD_DELAY} seconds before uploading part {idx + 1}")
                            await asyncio.sleep(UPLOAD_DELAY)
                        
                        file_id = await upload_part_to_tg(part_path, task_id, idx + 1, db, account)
                        if not file_id:
                            raise RuntimeError(f"Upload failed for part {idx + 1}")
                        parts_result.append({"part": idx + 1, "file_id": file_id})
                    except Exception as e:
                        logger.exception(f"[{task_id}] Error uploading part {idx + 1}")
                        await notify_admin(f"❌ [Task {task_id}] Part {idx + 1} upload failed: {e}")
                        # If we fail on a part, try with a different account
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

            finally:
                # Always release upload permission
                release_upload_permission()

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
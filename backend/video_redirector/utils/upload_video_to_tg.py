import os
import logging
from dotenv import load_dotenv
import math
import subprocess
import asyncio
import time
import json
from typing import Dict, Any, Optional
import datetime
from pyrogram.errors import FloodWait
import re

from backend.video_redirector.utils.notify_admin import notify_admin
from backend.video_redirector.db.session import get_db
from backend.video_redirector.utils.pyrogram_acc_manager import (
    select_upload_account, 
    increment_daily_stat, 
    release_account_reservation,
    register_upload_start,
    register_upload_end,
    AllProxiesExhaustedError
)
from backend.video_redirector.utils.rate_limit_monitor import (
    set_current_uploading_account,
    clear_current_uploading_account,
    reset_network_failures_for_account
)
from backend.video_redirector.db.crud_upload_accounts import update_last_error
from backend.video_redirector.utils.redis_client import RedisClient

# Store reference to the main event loop to schedule cross-thread coroutines
_MAIN_EVENT_LOOP: asyncio.AbstractEventLoop | None = None

def set_main_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _MAIN_EVENT_LOOP
    _MAIN_EVENT_LOOP = loop

logger = logging.getLogger(__name__)
load_dotenv()

MAX_MB = 1900
PARTS_DIR = "downloads/parts"
TG_USER_ID_TO_UPLOAD = 7841848291

# Upload configuration
UPLOAD_TIMEOUT = 600  # 10 minutes per part
MAX_RETRIES = 5  # Each retry uses 2 proxies. So we probably should set this num to = all proxies for acc / 2
RETRY_DELAY = 5  # Increased from 2 seconds
MIN_DISK_SPACE_MB = 1000  # 1GB minimum free space
FLOOD_WAIT_BUFFER = 5  # Additional buffer time after FloodWait
MAX_FLOOD_WAIT_RETRIES = 5  # Maximum FloodWait retries per part

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

# Progress logging throttle state
_progress_last_log_ts: dict[str, float] = {}

async def _persist_upload_progress(parent_task_id: str, file_task_id: str, part_num: int, percent: int, current: int, total: int) -> None:
    """Persist per-file/part upload progress to Redis without impacting the upload flow.

    Key: download:{parent_task_id}:upload_progress (hash)
    Field: {file_task_id}:part{part_num} -> percent (0..100)
    """
    try:
        redis = RedisClient.get_client()
        key = f"download:{parent_task_id}:upload_progress"
        field = f"{file_task_id}:part{part_num}"
        # Store percent as integer string
        await redis.hset(key, field, int(percent))
        # Ensure the key expires eventually
        await redis.expire(key, 3600)
        try:
            logger.debug(f"[{parent_task_id}] progress persisted: {field}={percent}% ({current}/{total})")
        except Exception:
            pass
    except Exception:
        # Never let progress persistence break upload
        pass

def _upload_progress_logger(current: int, total: int, task_id: str, part_num: int, file_size: int):
    """Synchronous progress callback for Pyrogram send_video.
    Throttled to log about once per second.
    """
    try:
        now = time.time()
        key = f"{task_id}:{part_num}"
        last = _progress_last_log_ts.get(key, 0.0)
        if now - last >= 1.0 or current == total:
            percent = int((current / total) * 100) if total else 0
            logger.debug(f"[{task_id}] [Part {part_num}] Upload progress: {percent}% ({current}/{total} bytes)")
            _progress_last_log_ts[key] = now

            # Also persist to Redis for frontend polling (best-effort, fire-and-forget)
            try:
                # Parent task id is the portion before optional _fileX suffix
                parent_task_id = task_id.split("_file")[0] if "_file" in task_id else task_id
                # Try current loop first (if in coroutine context)
                loop: asyncio.AbstractEventLoop | None = None
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    # Progress callback may run in a worker thread. Use main loop if available.
                    loop = _MAIN_EVENT_LOOP
                if loop is not None:
                    loop.create_task(_persist_upload_progress(parent_task_id, task_id, part_num, percent, current, total))
                else:
                    # As a last resort, write synchronously using redis asyncio client (will still be awaited via loop run)
                    # We cannot await here; skip to avoid blocking.
                    pass
            except Exception:
                # Ignore any issues with scheduling persistence
                pass
    except Exception:
        # Never let progress logging break upload
        pass

# Create necessary directories
os.makedirs(PARTS_DIR, exist_ok=True)

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
        
        # Update overall stats
        _upload_stats["total_uploads"] += 1
        _upload_stats["successful_uploads"] += 1
        _upload_stats["total_bytes_uploaded"] += int(file_size_mb * 1024 * 1024)
        
        # Log performance
        logger.debug(f"📊 [{task_id}] Upload performance: {file_size_mb:.1f}MB in {duration_seconds:.1f}s")
        logger.debug(f"   Speed: {current_speed_mbps:.2f} Mbps")
        logger.debug(f"   Account: {account_name}")
        logger.debug(f"   Flood waits: {flood_wait_count}")
        
        # Log average performance
        if len(_upload_stats["speed_stats"]["upload_times"]) >= 3:
            recent_avg = sum(_upload_stats["speed_stats"]["upload_times"][-3:]) / 3
            logger.debug(f"   Recent 3-upload average: {recent_avg:.1f}s")
        
        # Alert if performance is poor
        if duration_seconds > 180:  # 3 minutes
            await notify_admin(f"⚠️ [{task_id}] Slow upload: {file_size_mb:.1f}MB in {duration_seconds:.1f}s (account: {account_name})")
        
        # Alert if too many flood waits
        if flood_wait_count > 3:
            await notify_admin(f"⚠️ [{task_id}] High flood wait count: {flood_wait_count} (account: {account_name})")
    
    else:
        # Update failure stats
        _upload_stats["total_uploads"] += 1
        _upload_stats["failed_uploads"] += 1
        _upload_stats["retry_count"] += 1
        
        logger.error(f"❌ [{task_id}] Upload failed after {duration_seconds:.1f}s")
        logger.error(f"   Account: {account_name}")
        logger.error(f"   Flood waits: {flood_wait_count}")

async def get_upload_performance_summary():
    """Get a summary of upload performance"""
    global _upload_stats
    
    if _upload_stats["speed_stats"]["total_duration"] > 0:
        avg_speed = _upload_stats["speed_stats"]["average_speed_mbps"]
        total_uploads = _upload_stats["total_uploads"]
        success_rate = (_upload_stats["successful_uploads"] / total_uploads * 100) if total_uploads > 0 else 0
        
        logger.info(f"📊 Upload Performance Summary:")
        logger.info(f"   Total uploads: {total_uploads}")
        logger.info(f"   Success rate: {success_rate:.1f}%")
        logger.info(f"   Average speed: {avg_speed:.2f} Mbps")
        logger.info(f"   Total flood waits: {_upload_stats['speed_stats']['flood_wait_count']}")
        
        # Calculate recent performance (last 10 uploads)
        recent_times = _upload_stats["speed_stats"]["upload_times"][-10:]
        if recent_times:
            recent_avg = sum(recent_times) / len(recent_times)
            logger.info(f"   Recent average time for last 10 uploads: {recent_avg:.1f}s")
        
        return None
    
    return None

async def check_system_resources() -> Dict[str, Any]:
    """Check system resources before upload"""
    try:
        # Check disk space
        statvfs = os.statvfs('.')
        free_bytes = statvfs.f_frsize * statvfs.f_bavail
        free_mb = free_bytes / (1024 * 1024)
        disk_ok = free_mb >= MIN_DISK_SPACE_MB
        
        # Check memory (simplified)
        
        return {
            "disk_ok": disk_ok,
            "disk_free_mb": free_mb,
        }
    except Exception as e:
        logger.error(f"Error checking system resources: {e}")
        return {
            "disk_ok": False,
            "disk_free_mb": 0,
        }

async def rotate_account_on_failure(task_id: str, db, current_account):
    """Rotate to a different account on failure"""
    try:
        # Get a new account (already reserved by select_upload_account)
        new_account_idx, new_account = await select_upload_account(db)
        
        if new_account.session_name != current_account.session_name:
            # Release the current account's reservation since we're switching
            release_account_reservation(current_account.session_name)
            logger.info(f"🔄 [{task_id}] Rotating from {current_account.session_name} to {new_account.session_name}")
            return new_account
        else:
            logger.info(f"🔄 [{task_id}] Same account selected, no rotation needed")
            return current_account
            
    except Exception as e:
        logger.error(f"❌ [{task_id}] Error rotating account: {e}")
        return current_account

async def rotate_account_on_proxy_exhaustion(task_id: str, db, current_account):
    """When all proxies are exhausted for an account, try the next account"""
    try:
        logger.warning(f"🔄 [{task_id}] All proxies exhausted for {current_account.session_name}, attempting account rotation")
        
        # Get a new account (already reserved by select_upload_account)
        new_account_idx, new_account = await select_upload_account(db)
        
        if new_account.session_name != current_account.session_name:
            logger.info(f"🔄 [{task_id}] Switched from {current_account.session_name} to {new_account.session_name} due to proxy exhaustion")
            
            # Release the current account's reservation since we're switching
            release_account_reservation(current_account.session_name)
            
            # Reset rate limit events for the new account
            from .pyrogram_acc_manager import reset_rate_limit_events_for_account
            reset_rate_limit_events_for_account(new_account.session_name)
            
            return new_account
        else:
            logger.error(f"❌ [{task_id}] No alternative accounts available")
            return None
            
    except Exception as e:
        logger.error(f"❌ [{task_id}] Error rotating account on proxy exhaustion: {e}")
        return None

async def get_video_metadata_for_upload(file_path: str, task_id: str) -> Optional[Dict[str, Any]]:
    """Extract video metadata for Telegram upload"""
    try:
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            '-select_streams', 'v:0',  # Select first video stream
            file_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
        
        data = json.loads(result.stdout)
        
        # Try to get duration from format first, then stream
        format_info = data.get('format', {})
        streams = data.get('streams', [])
        
        if not streams:
            logger.warning(f"⚠️ [{task_id}] No video streams found")
            return None
        
        video_stream = streams[0]
        
        # Extract dimensions
        width = video_stream.get('width')
        height = video_stream.get('height')
        
        # Convert to integers for Pyrogram compatibility
        if width:
            width = int(width)
        if height:
            height = int(height)
        
        # Extract duration (prefer format, fallback to stream)
        duration = format_info.get('duration') or video_stream.get('duration')
        if duration:
            duration = int(float(duration))

        # Extract bitrate (prefer format, fallback to stream)
        bitrate = format_info.get('bit_rate') or video_stream.get('bit_rate')
        if bitrate:
            bitrate = int(bitrate)
        
        metadata = {
            'width': width,
            'height': height,
            'duration': duration,
            'bitrate': bitrate
        }
        
        logger.info(f"📐 [{task_id}] Video metadata: {width}x{height}, duration: {duration}s, bitrate: {bitrate}")
        return metadata
        
    except subprocess.CalledProcessError as e:
        logger.warning(f"⚠️ [{task_id}] ffprobe failed: {e.stderr}")
        return None
    except subprocess.TimeoutExpired:
        logger.error(f"❌ [{task_id}] ffprobe timeout")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"❌ [{task_id}] Failed to parse ffprobe JSON output: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ [{task_id}] Error extracting video metadata: {e}")
        return None

async def upload_part_to_tg_with_retry(file_path: str, task_id: str, part_num: int, db, account, bot_username: str):
    """Upload a part with retry logic and comprehensive error handling.

    Returns a tuple: (file_id or None, used_session_name)
    """
    
    # Register this upload as active
    await register_upload_start(task_id)
    
    # Set current uploading account for rate limit tracking
    set_current_uploading_account(task_id, account.session_name)
    
    try:
        # Extract metadata for Telegram upload
        upload_metadata = await get_video_metadata_for_upload(file_path, task_id)
        if not upload_metadata:
            logger.warning(f"⚠️ [{task_id}] Could not extract metadata for upload - Telegram may receive incorrect dimensions")
        
        # Pre-upload checks
        resources = await check_system_resources()
        if not resources["disk_ok"]:
            error_msg = f"Insufficient disk space: {resources['disk_free_mb']:.1f}MB free"
            logger.error(f"[{task_id}] {error_msg}")
            await notify_admin(f"❌ [{task_id}] {error_msg}")
            await log_upload_metrics(task_id, 0, False, 0)
            raise Exception(f"❌ [{task_id}] {error_msg}")
        
        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        file_size_mb = file_size / (1024 * 1024)
        retry_count = 0
        flood_wait_count = 0
        upload_start_time = time.time()
        
        for attempt in range(MAX_RETRIES):
            logger.info(f"[{task_id}] Upload attempt {attempt + 1}/{MAX_RETRIES} for part {part_num}")
            
            # Check if file still exists
            if not os.path.exists(file_path):
                error_msg = f"Part {part_num} file not found: {file_path}"
                logger.error(f"[{task_id}] {error_msg}")
                await log_upload_metrics(task_id, file_size, False, retry_count)
                raise Exception(f"❌{error_msg}")
            
            # Check file size
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                error_msg = f"Part {part_num} file is empty: {file_path}"
                logger.error(f"[{task_id}] {error_msg}")
                await log_upload_metrics(task_id, file_size, False, retry_count)
                raise Exception(f"❌{error_msg}")
            
            try:
                # Use new proxy-aware client creation
                client = await account.ensure_client_ready_with_retry()

                # Add null check for client
                if client is None:
                    error_msg = f"Client initialization failed for account {account.session_name}"
                    logger.error(f"❌ [{task_id}] {error_msg}")
                    logger.error(f"   Account state - Last used: {account.last_used}")
                    logger.error(f"   Client state - Client: {account.client}, Last creation: {account.last_client_creation}")

                    await notify_admin(f"🔐 [{task_id}] {error_msg}")
                    await update_last_error(db, account.session_name, "Client initialization failed")
                    await log_upload_metrics(task_id, file_size, False, retry_count)

                    # Log failed upload
                    total_duration = time.time() - upload_start_time
                    await log_upload_performance(task_id, file_size_mb, total_duration, flood_wait_count, account.session_name, False)

                    raise Exception(f"❌{error_msg}")

                logger.info(f"✅ [{task_id}] Client ready for {account.session_name}")

                # Upload with timeout
                start_time = datetime.datetime.now()
                logger.info(f"[{task_id}] [Part {part_num}] Starting upload at {start_time:%Y-%m-%d %H:%M:%S}")

                # Prepare send_video parameters
                send_video_params = {
                    "chat_id": str(bot_username),
                    "video": file_path,
                    "caption": "video",
                    "disable_notification": True,
                    "supports_streaming": True,
                    "progress": _upload_progress_logger,
                    "progress_args": (task_id, part_num, file_size)
                }

                # Add metadata if available
                if upload_metadata:
                    send_video_params["width"] = upload_metadata["width"]
                    send_video_params["height"] = upload_metadata["height"]
                    if upload_metadata["duration"]:
                        send_video_params["duration"] = upload_metadata["duration"]
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

                    # Mark proxy success for consecutive failure tracking
                    account.mark_proxy_success(account.current_proxy_index)

                    # If a rate-limit threshold was reached during this upload, apply the scheduled action now
                    try:
                        pending_idx = getattr(account, "pending_post_upload_cooldown_proxy_index", None)
                        if pending_idx is not None:
                            strikes = 0
                            try:
                                strikes = account.proxy_threshold_strikes.get(pending_idx, 0)
                            except Exception:
                                strikes = 0

                            # If the proxy has hit threshold across 3 uploads in a row, blacklist and notify
                            if strikes >= 3:
                                reason = "Repeated rate-limit thresholds across uploads"
                                logger.warning(
                                    f"🚫 [{account.session_name}] Blacklisting proxy index {pending_idx}: {reason} (strikes={strikes})"
                                )
                                account._blacklist_proxy(pending_idx, reason)
                                # Reset state after blacklisting
                                account.proxy_threshold_strikes[pending_idx] = 0
                                account.pending_post_upload_cooldown_proxy_index = None
                                # Stop client so future uploads cannot reuse the blacklisted proxy
                                try:
                                    await account.stop_client()
                                    logger.info(f"🛑 [{account.session_name}] Client stopped post-upload due to proxy blacklist (index {pending_idx})")
                                except Exception as stop_err:
                                    logger.debug(f"[{task_id}] Error stopping client after blacklist: {stop_err}")
                            else:
                                # Put the proxy into cooldown now; this will influence next selection
                                reason = "Post-upload cooldown due to rate-limit threshold"
                                account._put_proxy_in_cooldown(pending_idx, reason, "rate_limit_threshold")
                                logger.info(
                                    f"🧊 [{account.session_name}] Proxy index {pending_idx} cooled down post-upload (strikes={strikes})"
                                )
                                # Do NOT reset strikes here; allow escalation to 3 across consecutive uploads
                                account.pending_post_upload_cooldown_proxy_index = None
                                # Stop client so future uploads cannot reuse the cooled-down proxy
                                try:
                                    await account.stop_client()
                                    logger.info(f"🧊 [{account.session_name}] Client stopped post-upload due to proxy cooldown (index {pending_idx})")
                                except Exception as stop_err:
                                    logger.debug(f"[{task_id}] Error stopping client after cooldown: {stop_err}")
                        else:
                            # No threshold triggered during this upload; reset strikes for current proxy
                            try:
                                if account.current_proxy_index is not None:
                                    account.proxy_threshold_strikes[account.current_proxy_index] = 0
                            except Exception:
                                pass
                    except Exception as post_cooldown_err:
                        logger.debug(f"[{task_id}] Error handling post-upload cooldown/strikes: {post_cooldown_err}")

                    # Reset network failure counts after successful upload
                    reset_network_failures_for_account(account.session_name)

                    await log_upload_metrics(task_id, file_size, True, retry_count)
                    await increment_daily_stat(db, account.session_name)

                    # Log performance statistics
                    total_duration = time.time() - upload_start_time
                    await log_upload_performance(task_id, file_size_mb, total_duration, flood_wait_count, account.session_name, True)
                    await get_upload_performance_summary()
                    return file_id, account.session_name
                else:
                    logger.error(f"[{task_id}] Upload succeeded but no video data returned")
                    await log_upload_metrics(task_id, file_size, False, retry_count)

                    # Log failed upload
                    total_duration = time.time() - upload_start_time
                    await log_upload_performance(task_id, file_size_mb, total_duration, flood_wait_count, account.session_name, False)

                    return None, account.session_name

            except FloodWait as e:
                # Pyrogram already handled the rate limit internally, so this is a failure case
                flood_wait_count += 1
                wait_time = int(str(e.value))
                
                logger.warning(f"[{task_id}] FloodWait exception after Pyrogram's internal retries for part {part_num}: {wait_time}s")
                await notify_admin(f"🚫 [{task_id}] FloodWait exception (account: {account.session_name}): {wait_time}s after internal retries")
                
                # Mark proxy failure for consecutive failure tracking (this is a significant failure)
                account.mark_proxy_failure(account.current_proxy_index, f"FloodWait exception: {wait_time}s", is_significant_event=True)
                
                # Track the error in database
                await update_last_error(db, account.session_name, f"FloodWait exception: {wait_time}s after retries")
                
                # Stop the client to prevent further rate limiting
                await account.stop_client()

                # If we've hit too many FloodWait exceptions (not just events), stop retrying
                if flood_wait_count >= MAX_FLOOD_WAIT_RETRIES:
                    error_msg = f"Too many FloodWait exceptions ({flood_wait_count}) for part {part_num}, stopping retries"
                    logger.error(f"[{task_id}] {error_msg}")
                    await notify_admin(f"🚫 [{task_id}] {error_msg} (account: {account.session_name})")
                    
                    # Track the error in database
                    await update_last_error(db, account.session_name, f"Too many FloodWait exceptions: {flood_wait_count} retries exceeded")
                    
                    await log_upload_metrics(task_id, file_size, False, retry_count)
                    
                    # Log failed upload
                    total_duration = time.time() - upload_start_time
                    await log_upload_performance(task_id, file_size_mb, total_duration, flood_wait_count, account.session_name, False)
                    
                    raise Exception(f"❌{error_msg}")
                
                if flood_wait_count >= 3:  # Lower threshold since this is after Pyrogram's retries
                    logger.info(f"[{task_id}] Multiple FloodWait exceptions detected, attempting account rotation")
                    new_account = await rotate_account_on_failure(task_id, db, account)
                    if new_account.session_name != account.session_name:
                        account = new_account
                        logger.info(f"[{task_id}] Switched to account: {account.session_name}")
                        # Reset flood wait count for the new account
                        flood_wait_count = 0
                
                continue

            except asyncio.TimeoutError:
                retry_count += 1
                logger.error(f"[{task_id}] Upload timeout for part {part_num} (attempt {attempt + 1})")
                
                # Mark proxy failure for consecutive failure tracking (timeout is significant)
                account.mark_proxy_failure(account.current_proxy_index, "Upload timeout", is_significant_event=True)
                
                if attempt == MAX_RETRIES - 1:
                    error_msg = f"Upload timeout for part {part_num} after {MAX_RETRIES} attempts"
                    await notify_admin(f"⏰ [{task_id}] {error_msg}")
                    
                    # Track the error in database
                    await update_last_error(db, account.session_name, f"Upload timeout after {MAX_RETRIES} attempts")
                    
                    await log_upload_metrics(task_id, file_size, False, retry_count)
                    
                    # Log failed upload
                    total_duration = time.time() - upload_start_time
                    await log_upload_performance(task_id, file_size_mb, total_duration, flood_wait_count, account.session_name, False)
                    
                    raise Exception(f"❌{error_msg}")
                
                # Wait before retry
                await asyncio.sleep(RETRY_DELAY)
                continue

            except AllProxiesExhaustedError as e:
                error_msg = f"All proxies exhausted for account {account.session_name}: {e}"
                logger.error(f"❌ [{task_id}] {error_msg}")
                
                # Try to switch to next account instead of failing immediately
                new_account = await rotate_account_on_proxy_exhaustion(task_id, db, account)
                if new_account:
                    account = new_account
                    logger.info(f"🔄 [{task_id}] Switched to account: {account.session_name}")

                    # Update rate limit monitor context
                    set_current_uploading_account(task_id, account.session_name)

                    # Reset retry counters for new account
                    retry_count = 0
                    flood_wait_count = 0
                    continue  # Retry with new account
                else:
                    # No alternative accounts available
                    await notify_admin(f"🔴 [{task_id}] {error_msg}")
                    
                    # Track the error in database
                    await update_last_error(db, account.session_name, "All proxies exhausted")
                    
                    await log_upload_metrics(task_id, file_size, False, retry_count)
                    
                    # Log failed upload
                    total_duration = time.time() - upload_start_time
                    await log_upload_performance(task_id, file_size_mb, total_duration, flood_wait_count, account.session_name, False)
                    
                    raise Exception(f"❌{error_msg}")

            except Exception as e:
                retry_count += 1
                error_str = str(e).lower()
                logger.error(f"[{task_id}] Upload error for part {part_num} (attempt {attempt + 1}): {e}")
                
                # Mark proxy failure for consecutive failure tracking
                account.mark_proxy_failure(account.current_proxy_index, f"Upload error: {type(e).__name__}", is_significant_event=False)
                
                # If proxies are no longer available (exhausted or all in cooldown/blacklist), escalate to switch accounts
                try:
                    if not account.has_available_proxies():
                        raise AllProxiesExhaustedError(f"Account {account.session_name}: No available proxies after error")
                except AllProxiesExhaustedError as exhausted_err:
                    error_msg = f"All proxies exhausted for account {account.session_name}: {exhausted_err}"
                    logger.error(f"❌ [{task_id}] {error_msg}")
                    new_account = await rotate_account_on_proxy_exhaustion(task_id, db, account)
                    if new_account:
                        account = new_account
                        logger.info(f"🔄 [{task_id}] Switched to account: {account.session_name}")
                        set_current_uploading_account(task_id, account.session_name)
                        retry_count = 0
                        flood_wait_count = 0
                        continue
                    else:
                        await notify_admin(f"🔴 [{task_id}] {error_msg}")
                        await update_last_error(db, account.session_name, "All proxies exhausted")
                        await log_upload_metrics(task_id, file_size, False, retry_count)
                        total_duration = time.time() - upload_start_time
                        await log_upload_performance(task_id, file_size_mb, total_duration, flood_wait_count, account.session_name, False)
                        raise Exception(f"❌{error_msg}")

                # Track the error in database
                await update_last_error(db, account.session_name, f"Upload error: {type(e).__name__}")
                
                if attempt == MAX_RETRIES - 1:
                    error_msg = f"Upload failed for part {part_num} after {MAX_RETRIES} attempts: {e}"
                    await notify_admin(f"❌ [{task_id}] {error_msg}")
                    
                    await log_upload_metrics(task_id, file_size, False, retry_count)
                    
                    # Log failed upload
                    total_duration = time.time() - upload_start_time
                    await log_upload_performance(task_id, file_size_mb, total_duration, flood_wait_count, account.session_name, False)
                    
                    raise Exception(f"❌{error_msg}")
                
                # Wait before retry
                await asyncio.sleep(RETRY_DELAY)
                continue

    except Exception as e:
        logger.error(f"❌ [{task_id}] Fatal error in upload_part_to_tg_with_retry: {e}")
        await log_upload_metrics(task_id, 0, False, retry_count)
        raise
    finally:
        # Clear current uploading account
        clear_current_uploading_account(task_id)
        
        # Register upload end
        await register_upload_end(task_id)

async def upload_part_to_tg(file_path: str, task_id: str, part_num: int, db, account, bot_username: str):
    """
    Simple wrapper that guarantees a 2-tuple return shape: (file_id_or_None, used_session_name)
    """
    result = await upload_part_to_tg_with_retry(file_path, task_id, part_num, db, account, bot_username)
    if isinstance(result, tuple) and len(result) == 2:
        return result
    # Backward-compat: some paths might return only file_id; normalize using provided account
    return result, getattr(account, "session_name", "")

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
        
        logger.debug(f"📂 [{task_id}] Splitting {file_size / (1024*1024):.1f}MB file into {num_parts} parts")
        
        for i in range(num_parts):
            start_time = i * part_duration
            
            # For the last part, don't specify duration to avoid going beyond video length
            is_last_part = (i == num_parts - 1)
            
            part_output = os.path.join(PARTS_DIR, f"{task_id}_part{i+1}.mp4")
            
            # Remove existing part if it exists
            if os.path.exists(part_output):
                try:
                    os.remove(part_output)
                except Exception as e:
                    logger.warning(f"⚠️ [{task_id}] Couldn't remove existing part {i+1}: {e}")
            
            # Build FFmpeg command with better seeking
            cmd = [
                "ffmpeg",
                "-ss", str(int(start_time)),
                "-i", file_path
            ]
            
            # Only add duration for non-last parts
            if not is_last_part:
                cmd.extend(["-t", str(int(part_duration))])
            
            cmd.extend([
                "-c", "copy",  # Just copy, no re-processing
                "-avoid_negative_ts", "make_zero",
                "-movflags", "+faststart",
                "-y",
                part_output
            ])
            
            if is_last_part:
                logger.debug(f"🎬 [{task_id}] Generating part {i+1}/{num_parts} (start: {int(start_time)}s, duration: until end)")
            else:
                logger.debug(f"🎬 [{task_id}] Generating part {i+1}/{num_parts} (start: {int(start_time)}s, duration: {int(part_duration)}s)")
            
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
                
                logger.debug(f"✅ [{task_id}] Part {i+1} generated: {part_output} ({part_size / (1024*1024):.1f}MB) in {elapsed_time:.1f}s")
                
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

async def check_size_upload_large_file(file_path: str, task_id: str, db, bot_config: dict):
    """
    Upload a file to Telegram using the provided bot configuration.
    
    Args:
        file_path: Path to the file to upload
        task_id: Unique task identifier
        db: Database session
        bot_config: Dictionary containing 'username' and 'token' keys for the delivery bot
    """
    if not file_path:
        logger.error(f"[{task_id}] File path is None or empty")
        await notify_admin(f"[{task_id}] File path is None or empty. Check space on VPS or other error logs!")
        return None

    if not os.path.exists(file_path):
        logger.error(f"[{task_id}] File does not exist: {file_path}")
        await notify_admin(f"[{task_id}] File does not exist: {file_path}. Check space on VPS or other error logs!")
        return None

    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    logger.debug(f"[{task_id}] Checking file: {file_path} ({file_size_mb:.2f} MB)")
    
    # Extract bot info from config
    bot_username = bot_config.get("username")
    bot_token = bot_config.get("token")
    
    if not bot_username or not bot_token:
        raise Exception("Invalid bot configuration: missing username or token")
    
    parts_result = []
    selected_account = None  # Track the selected account for permission management (single-part path)
    created_part_paths: list[str] = []  # Track generated split parts for cleanup on failure

    try:
        part_num = re.search(r'_part(\d+)\.mp4$', file_path)
        if part_num:
            #part_num can be 0,1,2
            part_num = int(part_num.group(1)) + 1
        else:
            logger.error("No part number found.")
            raise Exception("No part number found.")
        
        try:
            # Single-part path: select and reserve one account and upload
            if file_size_mb <= MAX_MB:
                idx, account = await select_upload_account(db)
                selected_account = account  # Store for reservation management
                logger.info(f"[{task_id}] Selected account: {account.session_name}")

                logger.info(f"[{task_id}] File is {round(file_size_mb)} MB — uploading as one part")
                file_id, used_session = await upload_part_to_tg(file_path, task_id, 1, db, account, bot_username)
                logger.info(f"✅ [{task_id}] Single-part upload complete. file_id: {file_id}")

                # Success cleanup: remove the uploaded file and per-task folder if applicable
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        logger.debug(f"[{task_id}] Cleaned uploaded file: {file_path}")
                    parent_dir = os.path.dirname(file_path)
                    # If YouTube used a per-task folder downloads/<task_id>, try to remove when empty
                    if os.path.basename(parent_dir) == task_id and os.path.basename(os.path.dirname(parent_dir)) == 'downloads':
                        try:
                            if not os.listdir(parent_dir):
                                os.rmdir(parent_dir)
                                logger.debug(f"[{task_id}] Removed empty task directory: {parent_dir}")
                        except Exception as _e:
                            logger.debug(f"[{task_id}] Task folder cleanup skipped: {_e}")
                except Exception as _e:
                    logger.warning(f"[{task_id}] Single-part cleanup warning: {_e}")

                return {
                    "bot_token": bot_token,
                    "parts": {part_num:[{"part": 0, "file_id": file_id}]},
                    "session_name": used_session
                }

            logger.debug(f"[{task_id}] File is {round(file_size_mb)} MB — splitting...")

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
                logger.debug(f"[{task_id}] Video duration: {duration:.2f} seconds ({duration/60:.1f} minutes)")
                
                # Validate duration
                if duration <= 0:
                    logger.error(f"❌ [{task_id}] Invalid video duration: {duration}")
                    await notify_admin(f"❌ [Task {task_id}] Invalid video duration: {duration}")
                    raise Exception(f"❌ [Task {task_id}] Invalid video duration: {duration}")
                
                if duration < 60:  # Less than 1 minute
                    logger.warning(f"⚠️ [{task_id}] Very short video duration: {duration:.2f}s - this might be an error")
            except Exception as ero:
                logger.exception(f"[{task_id}] FFprobe failed")
                await notify_admin(f"❌ [Task {task_id}] Failed to get video duration: {ero}")
                raise Exception(f"❌ [Task {task_id}] Failed to get video duration: {ero}")

            num_parts = math.ceil(file_size_mb / MAX_MB)
            part_duration = duration / num_parts
            
            # Ensure each part has at least 10 seconds (to avoid very short parts)
            min_part_duration = 10
            if part_duration < min_part_duration:
                logger.warning(f"⚠️ [{task_id}] Calculated part duration ({part_duration:.1f}s) is too short, adjusting...")
                num_parts = max(1, int(duration / min_part_duration))
                part_duration = duration / num_parts
                logger.info(f"[{task_id}] Adjusted to {num_parts} parts, each ~{part_duration:.1f} seconds ({part_duration/60:.1f} minutes)")
            
            logger.info(f"[{task_id}] Splitting into {num_parts} parts, each ~{part_duration:.1f} seconds ({part_duration/60:.1f} minutes)")

            part_paths = await split_video_by_duration(file_path, task_id, num_parts, part_duration)
            if not part_paths:
                await notify_admin(f"❌ [Task {task_id}] Failed to split movie during ffmpeg slicing.")
                raise Exception(f"❌ [Task {task_id}] Failed to split movie during ffmpeg slicing.")
            created_part_paths = part_paths[:]

            #TODO: AS I understand if video is splited into 3 parts and parts are bigger then 1900MB we split each of 3 video parts
            # by 2 (so 6 parts total) (we can split more than by 2 if video parts are really big total video 21 GB, 3 parts 7 gb, each part splits into 4 pieces)
            # and we will get here and this logic upload each part sequntially, so probably 3 parallel uploads each will sequentially upload 2 parts
            # so all total 6 parts are uploaded (has not tested this scenario yet)

            # Upload parts in parallel — select a separate account per part
            used_sessions = set()

            async def upload_one(idx: int, part_path: str):
                reserved_account = None
                try:
                    # Create an isolated DB session for this task
                    async with get_db() as local_db:

                        # Reserve a separate account for this part
                        _, reserved_account = await select_upload_account(local_db)
                        used_sessions.add(reserved_account.session_name)

                        file_id, used_session = await upload_part_to_tg(
                            part_path, task_id, idx + 1, local_db, reserved_account, bot_username
                        )
                        return {"part": idx, "file_id": file_id, "used_session": used_session, "success": True}
                except Exception as e:
                    logger.exception(f"[{task_id}] Error uploading part {idx + 1}")
                    return {"part": idx, "error": str(e), "success": False}
                finally:
                    # Release reservation for this part's account
                    try:
                        if reserved_account is not None:
                            release_account_reservation(reserved_account.session_name)
                    except Exception as release_err:
                        logger.warning(f"[{task_id}] Error releasing reservation for part {idx + 1}: {release_err}")

            tasks = [asyncio.create_task(upload_one(idx, p)) for idx, p in enumerate(part_paths or [])]
            results = await asyncio.gather(*tasks)

            failures = [r for r in results if not r.get("success")]
            if failures:
                first_err = failures[0].get("error", "Unknown error")
                await notify_admin(f"❌ [Task {task_id}] Parallel upload failed for {len(failures)} part(s): {first_err}")
                raise Exception(f"❌ [{task_id}] Some parts failed: {first_err}")

            # Aggregate successful results in order
            parts_result = [
                {"part": r["part"], "file_id": r["file_id"]}
                for r in sorted(results, key=lambda x: x["part"])
            ]

            if len(parts_result) == num_parts:
                # Success cleanup: original big file and generated split parts
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                except Exception as errr:
                    logger.warning(f"[{task_id}] Couldn't clean up original movie file: {errr}")
                for p in part_paths:
                    try:
                        if os.path.exists(p):
                            os.remove(p)
                    except Exception as _e:
                        logger.warning(f"[{task_id}] Couldn't clean up split part {p}: {_e}")
                logger.info(f"[{task_id}] Upload successful with bot: {bot_username}")
                logger.debug(f"✅ [{task_id}] Multipart upload complete. {len(parts_result)} parts uploaded.")
                # Use the first used session for reporting; actual parts may span multiple sessions
                first_used_session = None
                try:
                    first_used_session = next(iter(used_sessions))
                except StopIteration:
                    first_used_session = None
                return {
                    "bot_token": bot_token,
                    "parts": {part_num: parts_result},
                    "session_name": first_used_session or ""
                }
            else:
                logger.error(f"[{task_id}] Upload incomplete. Uploaded {len(parts_result)} of {num_parts} parts.")
                await notify_admin(f"❌ [Task {task_id}] Upload incomplete. Uploaded {len(parts_result)} of {num_parts} parts.")
                raise Exception(f"❌ [Task {task_id}] Upload incomplete. Uploaded {len(parts_result)} of {num_parts} parts.")

        finally:
            # Release all reserved accounts used during this task
            try:
                # Always release the initially selected account
                if selected_account:
                    release_account_reservation(selected_account.session_name)
                # Also release any additional accounts used through rotation
                for used_session in locals().get('used_sessions', set()):
                    if not selected_account or used_session != selected_account.session_name:
                        release_account_reservation(used_session)
            except Exception as release_err:
                logger.warning(f"[{task_id}] Error releasing account reservations: {release_err}")

    except Exception as e:
        logger.exception(f"[{task_id}] Critical error during upload")
        await notify_admin(f"🧨 Critical failure while handling {task_id}:\n{e}")
        # Failure cleanup: remove original file, split parts, and per-task dir if applicable
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as _e:
            logger.debug(f"[{task_id}] Failure cleanup (file): {_e}")
        for p in created_part_paths:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception as _e:
                logger.debug(f"[{task_id}] Failure cleanup (part): {p} {_e}")
        try:
            parent_dir = os.path.dirname(file_path)
            if os.path.basename(parent_dir) == task_id and os.path.basename(os.path.dirname(parent_dir)) == 'downloads':
                # Best-effort remove leftover files then dir if empty
                try:
                    for fname in os.listdir(parent_dir):
                        fpath = os.path.join(parent_dir, fname)
                        if os.path.isfile(fpath):
                            try:
                                os.remove(fpath)
                            except Exception:
                                pass
                    if not os.listdir(parent_dir):
                        os.rmdir(parent_dir)
                except Exception:
                    pass
        except Exception:
            pass
        raise Exception(f"🧨 Critical failure while handling {task_id}:\n{e}")

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
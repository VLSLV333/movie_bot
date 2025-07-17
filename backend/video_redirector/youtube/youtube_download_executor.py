import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from typing import Optional
from backend.video_redirector.db.models import DownloadedFile, DownloadedFilePart
from backend.video_redirector.db.session import get_db
from backend.video_redirector.db.crud_downloads import get_file_id
from backend.video_redirector.utils.upload_video_to_tg import check_size_upload_large_file
from backend.video_redirector.utils.notify_admin import notify_admin
from backend.video_redirector.exceptions import RetryableDownloadError, RETRYABLE_EXCEPTIONS
from backend.video_redirector.utils.redis_client import RedisClient

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

async def get_best_format_id(video_url: str, target_quality: str, task_id: str) -> Optional[tuple]:
    """Get the best format selector and determine if we can use copy vs re-encode"""
    try:
        target_height = int(target_quality.replace('p', ''))
        
        # Format selector priority - prefer copy-friendly formats first
        format_selectors = [
            # Prefer MP4 with H.264+AAC (copy-friendly)
            f"best[height<={target_height}][ext=mp4][vcodec^=avc][acodec^=mp4a]",
            # Any MP4 at target quality (might need re-encode)
            f"best[height<={target_height}][ext=mp4]",
            # Any format at target quality (will need re-encode)
            f"best[height<={target_height}]", 
            # Fallback to best available (will need re-encode)
            "best"
        ]
        
        logger.info(f"[{task_id}] Testing format selectors for {target_quality}")
        
        # Test each format selector
        for format_selector in format_selectors:
            cmd = [
                "yt-dlp", 
                "--print", "%(format_id)s %(ext)s %(width)sx%(height)s %(acodec)s %(vcodec)s",
                "-f", format_selector,
                "--no-playlist",
                video_url
            ]
            
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0 and result.stdout.strip():
                    format_info = result.stdout.strip()
                    parts = format_info.split()
                    
                    if len(parts) >= 6:
                        format_id, ext, resolution, acodec, vcodec = parts[0], parts[1], parts[2], parts[3], parts[4]
                        
                        # Determine if we can copy (fast) or need to re-encode (slow)
                        can_copy = (
                            ext == "mp4" and 
                            acodec not in ["none", "unknown"] and 
                            vcodec.startswith(("avc", "h264"))
                        )
                        
                        logger.info(f"[{task_id}] Selected format: {format_info}")
                        logger.info(f"[{task_id}] Can copy streams: {can_copy} (ext={ext}, vcodec={vcodec}, acodec={acodec})")
                        
                        return (format_selector, can_copy)
                    
            except Exception as e:
                logger.warning(f"[{task_id}] Format selector '{format_selector}' failed: {e}")
                continue
        
        logger.error(f"[{task_id}] No suitable format found with any selector")
        return None
        
    except Exception as e:
        logger.error(f"[{task_id}] Error getting format selector: {e}")
        return None

async def verify_video_quality(video_path: str, task_id: str) -> Optional[str]:
    """Verify the actual quality of a downloaded video using ffprobe"""
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            video_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            logger.error(f"[{task_id}] Failed to get video info: {result.stderr}")
            return None
        
        data = json.loads(result.stdout)
        
        # Find video stream
        video_stream = None
        for stream in data.get('streams', []):
            if stream.get('codec_type') == 'video':
                video_stream = stream
                break
        
        if not video_stream:
            logger.error(f"[{task_id}] No video stream found")
            return None
        
        # Get resolution
        width = video_stream.get('width', 0)
        height = video_stream.get('height', 0)
        
        # Determine quality based on height
        if height >= 1080:
            quality = '1080p'
        elif height >= 720:
            quality = '720p'
        elif height >= 480:
            quality = '480p'
        elif height >= 360:
            quality = '360p'
        elif height >= 240:
            quality = '240p'
        else:
            quality = f"{height}p"
        
        logger.info(f"[{task_id}] Video resolution: {width}x{height} -> {quality}")
        return quality
        
    except Exception as e:
        logger.error(f"[{task_id}] Error verifying video quality: {e}")
        return None

async def download_youtube_video(video_url: str, task_id: str):
    """Download YouTube video using yt-dlp with smart copy vs re-encode logic"""
    
    # Get the best format selector and copy capability
    format_result = await get_best_format_id(video_url, "1080p", task_id)
    
    if not format_result:
        logger.error(f"[{task_id}] No suitable format found for video")
        return None
    
    format_selector, can_copy = format_result
    
    # Download the video
    output_path = os.path.join(DOWNLOAD_DIR, f"{task_id}.mp4")
    
    try:
        if can_copy:
            # Fast path: copy streams (no re-encoding)
            postprocessor_args = "ffmpeg:-c:v copy -c:a copy -avoid_negative_ts make_zero -movflags +faststart"
            logger.info(f"[{task_id}] Using FAST COPY mode (no re-encoding)")
        else:
            # Slow path: re-encode for compatibility
            postprocessor_args = "ffmpeg:-c:v libx264 -preset fast -crf 23 -c:a aac -b:a 128k -avoid_negative_ts make_zero -movflags +faststart"
            logger.info(f"[{task_id}] Using RE-ENCODE mode (format conversion)")
        
        # Build yt-dlp command
        cmd = [
            "yt-dlp",
            "-f", format_selector,
            "-o", output_path,
            "--no-playlist",
            "--no-warnings", 
            "--merge-output-format", "mp4",
            "--postprocessor-args", postprocessor_args,
            video_url
        ]
        
        logger.info(f"[{task_id}] Downloading with format: {format_selector}")
        
        # Run yt-dlp with timeout
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)  # 30 minutes timeout
        
        if result.returncode != 0:
            logger.error(f"[{task_id}] yt-dlp failed: {result.stderr}")
            return None
        
        # Check if file was created and has content
        if not os.path.exists(output_path):
            logger.error(f"[{task_id}] Output file not created")
            return None
        
        file_size = os.path.getsize(output_path)
        if file_size == 0:
            logger.error(f"[{task_id}] Downloaded file is empty")
            os.remove(output_path)
            return None
        
        logger.info(f"[{task_id}] Successfully downloaded: {output_path} ({file_size / (1024*1024):.1f}MB)")
        
        # Verify the actual quality of the downloaded video
        actual_quality = await verify_video_quality(output_path, task_id)
        if actual_quality:
            logger.info(f"[{task_id}] Actual downloaded quality: {actual_quality}")
        
        return (output_path, actual_quality or "unknown")
        
    except subprocess.TimeoutExpired:
        logger.error(f"[{task_id}] Download timeout (30 minutes)")
        return None
    except Exception as e:
        logger.error(f"[{task_id}] Download error: {e}")
        return None

async def handle_youtube_download_task(task_id: str, video_url: str, tmdb_id: int, lang: str, dub: str, video_title: str, video_poster: str):
    """Handle YouTube video download task - follows same interface as HDRezka executor"""
    redis = RedisClient.get_client()
    await redis.set(f"download:{task_id}:status", "downloading", ex=3600)

    # Remove from user's active downloads set when done (success or error)
    tg_user_id = None
    output_path = None
    
    try:
        # Download the video
        download_result = await download_youtube_video(video_url, task_id)
        if not download_result:
            #TODO:analyse what happens on error outcomes
            raise Exception("Failed to download YouTube video")
        
        output_path, selected_quality = download_result

        await redis.set(f"download:{task_id}:status", "uploading", ex=3600)
        
        # Upload to Telegram using existing infrastructure
        upload_result: Optional[dict] = None
        async for db in get_db():
            upload_result = await check_size_upload_large_file(output_path, task_id, db)
            break  # Only need one session

        if not upload_result:
            #TODO:analyse what happens on error outcomes
            raise Exception("Upload to Telegram failed across all delivery bots.")

        tg_bot_token_file_owner = upload_result["bot_token"]
        parts = upload_result["parts"]
        session_name = upload_result["session_name"]

        # Save in DB using existing structure - handle duplicates gracefully
        async for session in get_db():
            # Check if file already exists
            existing_file = await get_file_id(session, tmdb_id, lang, dub)
            
            if existing_file:
                # Update existing record with new file info
                logger.info(f"[{task_id}] Updating existing YouTube file record (ID: {existing_file.id})")
                for attr, value in [
                    ("quality", selected_quality),
                    ("tg_bot_token_file_owner", tg_bot_token_file_owner),
                    ("movie_title", video_title),
                    ("movie_poster", video_poster),
                    ("movie_url", video_url),
                    ("session_name", session_name)
                ]:
                    setattr(existing_file, attr, value)
                
                # Delete old parts and add new ones
                from sqlalchemy import delete
                delete_parts_stmt = delete(DownloadedFilePart).where(
                    DownloadedFilePart.downloaded_file_id == existing_file.id
                )
                await session.execute(delete_parts_stmt)
                
                db_id_to_get_parts = existing_file.id
            else:
                # Create new record
                db_entry = DownloadedFile(
                    tmdb_id=tmdb_id,
                    lang=lang,
                    dub=dub,
                    quality=selected_quality,
                    tg_bot_token_file_owner=tg_bot_token_file_owner,
                    created_at=datetime.now(timezone.utc),
                    movie_title=video_title,
                    movie_poster=video_poster,
                    movie_url=video_url,
                    session_name=session_name
                )
                session.add(db_entry)
                await session.flush()  # Get db_entry.id
                db_id_to_get_parts = db_entry.id

            # Add parts (works for both new and updated records)
            if parts is None:
                raise Exception("Upload to Telegram failed: parts is None")
            else:
                for part in parts:
                    session.add(DownloadedFilePart(
                        downloaded_file_id=db_id_to_get_parts,
                        part_number=part["part"],
                        telegram_file_id=part["file_id"]
                    ))
            
            await session.commit()
            break  # Only need one iteration

        await redis.set(f"download:{task_id}:status", "done", ex=3600)

        if len(parts) == 1:
            await redis.set(f"download:{task_id}:result", json.dumps({
                "tg_bot_token_file_owner": tg_bot_token_file_owner,
                "telegram_file_id": parts[0]["file_id"]
            }), ex=86400)
        else:
            await redis.set(f"download:{task_id}:result", json.dumps({
                "db_id_to_get_parts": db_id_to_get_parts,
            }), ex=86400)
            
        logger.info(f"[{task_id}] YouTube download completed successfully")
        
    except RETRYABLE_EXCEPTIONS as e:
        logger.error(f"[Download Task {task_id}] Failed RETRYABLE_EXCEPTIONS: {e}")
        raise RetryableDownloadError(f"Temporary issue during YouTube download: {e}")
    except Exception as e:
        logger.error(f"[Download Task {task_id}] Failed Exception: {e}")
        await redis.set(f"download:{task_id}:status", "error", ex=3600)
        await redis.set(f"download:{task_id}:error", str(e), ex=3600)
        await notify_admin(f"[Download Task {task_id}] YouTube download failed: {e}")
    finally:
        # Clean up downloaded file
        if output_path and os.path.exists(output_path):
            try:
                os.remove(output_path)
                logger.info(f"[{task_id}] Cleaned up downloaded file: {output_path}")
            except Exception as e:
                logger.warning(f"[{task_id}] Failed to clean up file {output_path}: {e}")
        
        # Remove from user's active downloads set
        if tg_user_id is None:
            # Try to get from Redis
            tg_user_id = await redis.get(f"download:{task_id}:user_id")
        if tg_user_id:
            await redis.srem(f"active_downloads:{tg_user_id}", task_id) # type: ignore
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

async def get_available_qualities(video_url: str) -> list[str]:
    """Get available qualities for a YouTube video using yt-dlp"""
    try:
        cmd = [
            "yt-dlp",
            "--list-formats",
            "--no-playlist",
            video_url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            logger.error(f"Failed to get formats: {result.stderr}")
            #TODO:analyse what happens on error outcomes
            return []
        
        # Parse yt-dlp output to extract available qualities
        lines = result.stdout.strip().split('\n')
        qualities = []
        
        for line in lines:
            # Look for video formats with resolution information
            if any(q in line for q in ['1080p', '720p', '480p', '360p', '240p']):
                # Check if it's a video format (not just audio)
                if any(ext in line.lower() for ext in ['mp4', 'webm', 'avi', 'mov']) or 'video' in line.lower():
                    if '1080p' in line or '1920x1080' in line:
                        qualities.append('1080p')
                    elif '720p' in line or '1280x720' in line:
                        qualities.append('720p')
                    elif '480p' in line or '854x480' in line:
                        qualities.append('480p')
                    elif '360p' in line or '640x360' in line:
                        qualities.append('360p')
                    elif '240p' in line or '426x240' in line:
                        qualities.append('240p')
        
        # Remove duplicates and sort by preference
        unique_qualities = list(dict.fromkeys(qualities))
        quality_order = ['1080p', '720p', '480p', '360p', '240p']
        sorted_qualities = [q for q in quality_order if q in unique_qualities]
        
        logger.info(f"Available qualities: {sorted_qualities}")
        
        # Log all available formats for debugging (first 10 lines)
        logger.info(f"All available formats (first 10):")
        for i, line in enumerate(lines[:10]):
            logger.info(f"  {i+1}: {line}")
        
        return sorted_qualities
        
    except subprocess.TimeoutExpired:
        logger.error("Timeout getting video formats")
        #TODO:analyse what happens on error outcomes
        return []
    except Exception as e:
        logger.error(f"Error getting video formats: {e}")
        #TODO:analyse what happens on error outcomes
        return []

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
    """Download YouTube video using yt-dlp with quality fallback"""
    
    # Get available qualities
    available_qualities = await get_available_qualities(video_url)
    
    if not available_qualities:
        logger.error(f"[{task_id}] No available qualities found for video")
        #TODO:analyse what happens on error outcomes
        return None
    
    # Find the best available quality (fallback from preferred)
    quality_order = ['1080p', '720p', '480p', '360p', '240p']
    selected_quality = None
    
    for quality in quality_order:
        if quality in available_qualities:
            selected_quality = quality
            break
    
    if not selected_quality:
        logger.error(f"[{task_id}] No suitable quality found")
        #TODO:analyse what happens on error outcomes
        return None
    
    logger.info(f"[{task_id}] Selected quality: {selected_quality}")
    
    # Download the video
    output_path = os.path.join(DOWNLOAD_DIR, f"{task_id}.mp4")
    
    try:
        # Build yt-dlp command for the selected quality
        # Use simple format selection - yt-dlp will convert to MP4 anyway
        height = selected_quality.replace('p', '')
        format_spec = f"best[height={height}]/best"
        
        cmd = [
            "yt-dlp",
            "-f", format_spec,
            "-o", output_path,
            "--no-playlist",
            "--no-warnings",
            "--merge-output-format", "mp4",
            "--postprocessor-args", "ffmpeg:-c:v copy -c:a copy -avoid_negative_ts make_zero -movflags +faststart",
            video_url
        ]
        
        logger.info(f"[{task_id}] Downloading with command: {' '.join(cmd)}")
        
        # Log the format specification for debugging
        logger.info(f"[{task_id}] Format specification: {format_spec}")
        
        # Run yt-dlp with timeout
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)  # 30 minutes timeout
        
        if result.returncode != 0:
            logger.error(f"[{task_id}] yt-dlp failed: {result.stderr}")
            #TODO:analyse what happens on error outcomes
            return None
        
        # Check if file was created and has content
        if not os.path.exists(output_path):
            logger.error(f"[{task_id}] Output file not created")
            #TODO:analyse what happens on error outcomes
            return None
        
        file_size = os.path.getsize(output_path)
        if file_size == 0:
            logger.error(f"[{task_id}] Downloaded file is empty")
            os.remove(output_path)
            #TODO:analyse what happens on error outcomes
            return None
        
        logger.info(f"[{task_id}] Successfully downloaded: {output_path} ({file_size / (1024*1024):.1f}MB)")
        
        # Verify the actual quality of the downloaded video
        actual_quality = await verify_video_quality(output_path, task_id)
        if actual_quality:
            logger.info(f"[{task_id}] Actual downloaded quality: {actual_quality}")
            if actual_quality != selected_quality:
                logger.warning(f"[{task_id}] Quality mismatch: requested {selected_quality}, got {actual_quality}")
        
        return (output_path, actual_quality or selected_quality)
        
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
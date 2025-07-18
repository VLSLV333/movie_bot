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
    """Get the best format ID that has both video and audio, or merge video+audio IDs - ROBUST VERSION"""
    
    # Strategy 1: Try JSON-based format detection (most reliable)
    try:
        logger.info(f"[{task_id}] Getting video formats using JSON method...")
        
        cmd = [
            "yt-dlp",
            "--dump-json",
            "--no-playlist", 
            "--no-warnings",
            video_url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0:
            try:
                video_info = json.loads(result.stdout)
                formats = video_info.get('formats', [])
                
                if formats:
                    logger.info(f"[{task_id}] Found {len(formats)} formats via JSON method")
                    json_result = await _analyze_formats_from_json(formats, target_quality, task_id)
                    if json_result:  # Only return if we found a good format
                        return json_result
                else:
                    logger.warning(f"[{task_id}] No formats in JSON response")
            except json.JSONDecodeError as e:
                logger.warning(f"[{task_id}] Failed to parse JSON: {e}")
        else:
            logger.warning(f"[{task_id}] JSON method failed: {result.stderr}")
    
    except Exception as e:
        logger.warning(f"[{task_id}] JSON format detection failed: {e}")
    
    # Strategy 2: Try text parsing method (backup)
    try:
        logger.info(f"[{task_id}] Fallback to text parsing method...")
        
        cmd = [
            "yt-dlp", 
            "--list-formats",
            "--no-playlist",
            "--no-warnings",
            video_url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0:
            # Log the actual output for debugging
            logger.info(f"[{task_id}] yt-dlp output preview: {result.stdout[:500]}...")
            
            # Try to parse text output with more flexible patterns
            text_result = await _analyze_formats_from_text(result.stdout, target_quality, task_id)
            if text_result:  # Only return if we found a good format
                return text_result
        else:
            logger.warning(f"[{task_id}] Text method failed: {result.stderr}")
    
    except Exception as e:
        logger.warning(f"[{task_id}] Text format detection failed: {e}")
    
    # Strategy 3: Simple format selectors (most compatible)
    logger.warning(f"[{task_id}] Using simple format selectors as final fallback")
    
    # Try different format selectors in order of preference
    fallback_formats = [
        ("best[height<=1080][ext=mp4]", True),  # Best 1080p MP4
        ("best[ext=mp4]", True),                # Best MP4
        ("best[height<=1080]", False),           # Best 1080p (any format)
        ("best", False)                         # Absolute fallback
    ]
    
    for format_selector, can_copy in fallback_formats:
        try:
            # Test if this format selector works
            test_cmd = [
                "yt-dlp",
                "-f", format_selector,
                "--no-download",
                "--no-playlist",
                "--quiet",
                video_url
            ]
            
            test_result = subprocess.run(test_cmd, capture_output=True, timeout=30)
            
            if test_result.returncode == 0:
                logger.info(f"[{task_id}] Using fallback format: {format_selector}")
                return (format_selector, can_copy)
        
        except Exception as e:
            logger.info(f"[{task_id}] Format {format_selector} test failed: {e}")
            continue
    
    # If all else fails
    logger.error(f"[{task_id}] All format detection methods failed")
    return None

async def _analyze_formats_from_json(formats: list, target_quality: str, task_id: str) -> Optional[tuple]:
    """Analyze formats from JSON data"""
    video_only_formats = []
    audio_only_formats = []  
    combined_formats = []
    
    target_height = int(target_quality.replace('p', ''))
    
    # Categorize formats using reliable JSON data
    for fmt in formats:
        format_id = fmt.get('format_id')
        ext = fmt.get('ext', 'unknown')
        vcodec = fmt.get('vcodec', 'none')
        acodec = fmt.get('acodec', 'none')
        width = fmt.get('width')
        height = fmt.get('height')
        
        if not format_id:
            continue
        
        # Audio-only format
        if vcodec == 'none' and acodec != 'none':
            audio_only_formats.append({
                'id': format_id,
                'ext': ext,
                'acodec': acodec,
                'abr': fmt.get('abr', 0)
            })
            
        # Video-only format  
        elif vcodec != 'none' and acodec == 'none' and width and height:
            video_only_formats.append({
                'id': format_id,
                'ext': ext,
                'vcodec': vcodec,
                'width': width,
                'height': height,
                'tbr': fmt.get('tbr', 0)
            })
            
        # Combined video+audio format
        elif vcodec != 'none' and acodec != 'none' and width and height:
            combined_formats.append({
                'id': format_id,
                'ext': ext,
                'vcodec': vcodec,
                'acodec': acodec,
                'width': width,
                'height': height,
                'tbr': fmt.get('tbr', 0)
            })
    
    logger.info(f"[{task_id}] Format analysis: {len(combined_formats)} combined, {len(video_only_formats)} video-only, {len(audio_only_formats)} audio-only")
    
    # Strategy 1: Try good quality combined formats first
    if combined_formats:
        # Sort by height (descending), then prefer MP4
        combined_formats.sort(key=lambda x: (x['height'], x['ext'] == 'mp4'), reverse=True)
        
        for fmt in combined_formats:
            if fmt['height'] >= 1080:  # Accept 1080p+ combined formats
                can_copy = fmt['ext'] == 'mp4'
                logger.info(f"[{task_id}] Selected combined format: {fmt['id']} ({fmt['width']}x{fmt['height']} {fmt['ext']}) - Copy: {can_copy}")
                return (fmt['id'], can_copy)
    
    # Strategy 2: Merge video-only + audio-only
    if video_only_formats and audio_only_formats:
        # Sort formats
        video_only_formats.sort(key=lambda x: (x['height'], x['ext'] == 'mp4'), reverse=True)
        audio_only_formats.sort(key=lambda x: x['ext'] in ['m4a', 'mp4'], reverse=True)
        
        # Find best video
        best_video = None
        for fmt in video_only_formats:
            if fmt['height'] <= target_height * 1.2:  # Allow some tolerance
                best_video = fmt
                break
        
        if not best_video:
            best_video = video_only_formats[0]  # Use highest quality
        
        best_audio = audio_only_formats[0]
        
        can_copy = (best_video['ext'] == 'mp4' and best_audio['ext'] in ['m4a', 'mp4'])
        merge_format = f"{best_video['id']}+{best_audio['id']}"
        
        logger.info(f"[{task_id}] Selected merge format: {merge_format} - Copy: {can_copy}")
        return (merge_format, can_copy)
    
    # If we can't find good formats, return None to allow main function's Strategy 3
    logger.warning(f"[{task_id}] JSON analysis found no suitable formats, will try fallback methods")
    return None

async def _analyze_formats_from_text(output: str, target_quality: str, task_id: str) -> Optional[tuple]:
    """Analyze formats from text output with flexible parsing"""
    
    lines = output.strip().split('\n')
    
    # Look for format table with more flexible patterns
    table_start = -1
    
    patterns = [
        "ID      EXT   RESOLUTION",  # Standard pattern
        "format code",               # Alternative pattern  
        "ID     EXT  RESOLUTION",    # Slightly different spacing
        "format_id",                 # JSON-like output mixed in
        "---",                       # Separator line
    ]
    
    for i, line in enumerate(lines):
        line_lower = line.lower()
        for pattern in patterns:
            if pattern.lower() in line_lower:
                table_start = i + 1
                logger.info(f"[{task_id}] Found format table at line {i} with pattern '{pattern}'")
                break
        if table_start != -1:
            break
    
    if table_start == -1:
        # Try to find any line that looks like a format
        for i, line in enumerate(lines):
            # Look for lines that start with format ID (number or alphanumeric)
            stripped = line.strip()
            if stripped and len(stripped.split()) >= 3:
                parts = stripped.split()
                # Check if first part looks like a format ID
                if parts[0].replace('-', '').replace('_', '').isalnum():
                    table_start = i
                    logger.info(f"[{task_id}] Guessed format table start at line {i}")
                    break
    
    if table_start == -1:
        logger.warning(f"[{task_id}] Could not find format table in text output")
        return None  
    # Parse what we can from the text output (simplified approach)
    video_only_formats = []
    audio_only_formats = []
    combined_formats = []
    
    target_height = int(target_quality.replace('p', ''))
    
    # Parse format lines with more flexible approach
    for line in lines[table_start:]:
        line = line.strip()
        if not line or line.startswith('---') or line.startswith('[') or 'only' not in line.lower():
            continue
        
        # Parse format line: ID EXT RESOLUTION FPS CH | FILESIZE TBR PROTO | VCODEC VBR ACODEC ABR ASR MORE INFO
        parts = line.split()
        if len(parts) < 3:
            continue
        
        format_id = parts[0]
        ext = parts[1] 
        resolution = parts[2]
        
        # Categorize formats
        if resolution == 'audio' or 'audio only' in line.lower():
            # Audio-only format
            audio_only_formats.append({
                'id': format_id,
                'ext': ext,
                'line': line
            })
            logger.info(f"[{task_id}]   {format_id}: AUDIO-ONLY ({ext})")
            
        elif 'video only' in line.lower():
            # Video-only format  
            if 'x' in resolution:
                try:
                    width, height = map(int, resolution.split('x'))
                    video_only_formats.append({
                        'id': format_id,
                        'ext': ext,
                        'width': width,
                        'height': height,
                        'line': line
                    })
                    logger.info(f"[{task_id}]   {format_id}: {width}x{height} ({ext}) - VIDEO-ONLY")
                except ValueError:
                    continue
                    
        elif 'x' in resolution and resolution != 'audio':
            # Combined video+audio format
            try:
                width, height = map(int, resolution.split('x'))
                combined_formats.append({
                    'id': format_id,
                    'ext': ext,
                    'width': width,
                    'height': height,
                    'line': line
                })
                logger.info(f"[{task_id}]   {format_id}: {width}x{height} ({ext}) - COMBINED")
            except ValueError:
                continue
    
    # Strategy 1: Try good quality combined formats first
    if combined_formats:
        # Sort combined formats: prefer MP4, then by height (descending)
        combined_formats.sort(key=lambda x: (x['height'], x['ext'] == 'mp4'), reverse=True)
        
        logger.info(f"[{task_id}] Available combined (video+audio) formats:")
        for fmt in combined_formats[:3]:
            logger.info(f"[{task_id}]   {fmt['id']}: {fmt['width']}x{fmt['height']} ({fmt['ext']})")
        
        # Find good quality combined format
        for fmt in combined_formats:
            if fmt['height'] >= 1080:  # Accept 1080+ combined formats
                can_copy = fmt['ext'] == 'mp4'
                logger.info(f"[{task_id}] Selected COMBINED format: {fmt['id']} ({fmt['width']}x{fmt['height']} {fmt['ext']}) - Can copy: {can_copy}")
                return (fmt['id'], can_copy)
    
    # Strategy 2: Merge best video-only + audio-only for higher quality
    if video_only_formats and audio_only_formats:
        # Sort video formats: prefer MP4, then by height (descending)
        video_only_formats.sort(key=lambda x: (x['height'], x['ext'] == 'mp4'), reverse=True)
        # Sort audio formats: prefer m4a/mp4, then others
        audio_only_formats.sort(key=lambda x: x['ext'] in ['m4a', 'mp4'], reverse=True)
        
        logger.info(f"[{task_id}] Available video-only formats:")
        for fmt in video_only_formats[:3]:
            logger.info(f"[{task_id}]   {fmt['id']}: {fmt['width']}x{fmt['height']} ({fmt['ext']})")
        
        logger.info(f"[{task_id}] Available audio-only formats:")
        for fmt in audio_only_formats[:3]:
            logger.info(f"[{task_id}]   {fmt['id']}: ({fmt['ext']})")
        
        # Find best video at target quality
        best_video = None
        for fmt in video_only_formats:
            if fmt['height'] <= target_height * 1.2:  # Allow some tolerance
                best_video = fmt
                break
        
        if not best_video:
            # Use highest available video quality
            best_video = video_only_formats[0]
        
        # Use best audio (prefer m4a/mp4 for compatibility)
        best_audio = audio_only_formats[0]
        
        # Check if we can use fast copy (both MP4-compatible)
        can_copy = (best_video['ext'] == 'mp4' and best_audio['ext'] in ['m4a', 'mp4'])
        
        merge_format = f"{best_video['id']}+{best_audio['id']}"
        logger.info(f"[{task_id}] Selected MERGE format: {merge_format}")
        logger.info(f"[{task_id}]   Video: {best_video['id']} ({best_video['width']}x{best_video['height']} {best_video['ext']})")
        logger.info(f"[{task_id}]   Audio: {best_audio['id']} ({best_audio['ext']})")
        logger.info(f"[{task_id}]   Can copy: {can_copy}")
        
        return (merge_format, can_copy)
    
    # If we can't find good formats, return None to allow main function's Strategy 3
    logger.warning(f"[{task_id}] Text analysis found no suitable formats, will try fallback methods")
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
    
    # Get the best format ID and copy capability
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
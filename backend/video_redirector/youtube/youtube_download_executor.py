import asyncio
import json
import logging
import os
import subprocess
import shutil
from datetime import datetime, timezone
from typing import Optional
from backend.video_redirector.db.models import DownloadedFile, DownloadedFilePart
from backend.video_redirector.db.session import get_db
from backend.video_redirector.db.crud_downloads import get_file_id
from backend.video_redirector.hdrezka.hdrezka_download_executor import (
    process_parallel_uploads,
    consolidate_upload_results,
)
from backend.video_redirector.utils.notify_admin import notify_admin
from backend.video_redirector.utils.redis_client import RedisClient
from backend.video_redirector.config import MAX_CONCURRENT_DOWNLOADS
import re

logger = logging.getLogger(__name__)

# Base download directory - each task will get its own subdirectory
BASE_DOWNLOAD_DIR = "downloads"
os.makedirs(BASE_DOWNLOAD_DIR, exist_ok=True)

def get_task_download_dir(task_id: str) -> str:
    """
    Create a unique download directory for this task based on MAX_CONCURRENT_DOWNLOADS
    This ensures each download has its own isolated directory for progress tracking
    """
    # Use hash of task_id to get consistent directory assignment
    # Use abs() to ensure positive numbers and % to get range 0 to MAX_CONCURRENT_DOWNLOADS-1
    task_hash = abs(hash(task_id)) % MAX_CONCURRENT_DOWNLOADS
    task_dir = f"{BASE_DOWNLOAD_DIR}{task_hash}"
    os.makedirs(task_dir, exist_ok=True)
    return task_dir

async def debug_available_formats(video_url: str, task_id: str, use_cookies: bool = False):
    """Debug function to log all available formats for troubleshooting"""
    try:
        logger.debug(f"[{task_id}] 🔍 Debug: Getting all available formats...")
        
        cmd = [
            "yt-dlp",
            "--list-formats",
            "--no-playlist",
            "--no-warnings",
        ]
        if use_cookies:
            cmd += ["--cookies", "cookies.txt"]
        cmd += [
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "--add-header", "Accept-Language:en-US,en;q=0.9,en;q=0.8",
            "--add-header", "Accept-Encoding:gzip, deflate, br",
            "--add-header", "Accept:text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "--add-header", "Accept-Charset:utf-8, iso-8859-1;q=0.5, *;q=0.1",
            "--add-header", "Connection:keep-alive",
            "--add-header", "Upgrade-Insecure-Requests:1",
            "--add-header", "Sec-Fetch-Dest:document",
            "--add-header", "Sec-Fetch-Mode:navigate",
            "--add-header", "Sec-Fetch-Site:none",
            "--add-header", "Sec-Fetch-User:?1",
            "--add-header", "Cache-Control:max-age=0",
            "--add-header", "DNT:1",
            video_url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            
            # Log full format table for debugging
            logger.debug(f"[{task_id}] 🔍 Debug: FULL format list ({len(lines)} lines):")
            for i, line in enumerate(lines):
                logger.debug(f"[{task_id}] 🔍 {i+1:3d}: {line}")
            
            # Focus on audio-only formats specifically
            logger.debug(f"[{task_id}] 🔍 Debug: AUDIO-ONLY formats analysis:")
            audio_count = 0
            for i, line in enumerate(lines):
                line_lower = line.lower()
                if 'audio only' in line_lower or ('audio' in line_lower and ('only' in line_lower or 'm4a' in line_lower)):
                    audio_count += 1
                    # Check for original/default indicators
                    original_indicators = []
                    if 'original' in line_lower:
                        original_indicators.append('ORIGINAL')
                    if 'default' in line_lower:
                        original_indicators.append('DEFAULT')
                    if 'primary' in line_lower:
                        original_indicators.append('PRIMARY')
                    if not any(lang in line_lower for lang in ['-auto', 'dubbed']):
                        original_indicators.append('NO_DUB_MARKER')
                    
                    indicator_str = f" [{', '.join(original_indicators)}]" if original_indicators else " [NO_INDICATORS]"
                    logger.debug(f"[{task_id}] 🔍 AUDIO #{audio_count:2d}: {line}{indicator_str}")
            
            if audio_count == 0:
                logger.warning(f"[{task_id}] 🔍 Debug: NO audio-only formats found in text output!")
        else:
            logger.warning(f"[{task_id}] 🔍 Debug: Failed to get formats: {result.stderr}")
            
    except Exception as e:
        logger.warning(f"[{task_id}] 🔍 Debug: Error getting formats: {e}")

async def get_best_format_id(video_url: str, target_quality: str, task_id: str, use_cookies: bool = False) -> Optional[tuple]:
    """Get the best format ID that has both video and audio, or merge video+audio IDs - ROBUST VERSION"""

    # Debug what formats are available (can be disabled for less verbose logs)
    # await debug_available_formats(video_url, task_id, use_cookies=use_cookies)

    # Strategy 1: Try JSON-based format detection (most reliable)
    try:
        #logger.debug(f"[{task_id}] Getting video formats using JSON method...")
        
        cmd = [
            "yt-dlp",
            "--dump-json",
            "--no-playlist", 
            "--no-warnings",
        ]
        if use_cookies:
            cmd += ["--cookies", "cookies.txt"]
        cmd += [
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "--add-header", "Accept-Language:en-US,en;q=0.9,en;q=0.8",
            "--add-header", "Accept-Encoding:gzip, deflate, br",
            "--add-header", "Accept:text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "--add-header", "Accept-Charset:utf-8, iso-8859-1;q=0.5, *;q=0.1",
            "--add-header", "Connection:keep-alive",
            "--add-header", "Upgrade-Insecure-Requests:1",
            "--add-header", "Sec-Fetch-Dest:document",
            "--add-header", "Sec-Fetch-Mode:navigate",
            "--add-header", "Sec-Fetch-Site:none",
            "--add-header", "Sec-Fetch-User:?1",
            "--add-header", "Cache-Control:max-age=0",
            "--add-header", "DNT:1",
            # "--sleep-interval", "2",  # Sleep 2 seconds between requests
            # "--max-sleep-interval", "5",  # Max 5 seconds sleep
            video_url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if "Failed to extract any player response" in result.stderr:
            logger.error(f"[{task_id}] 🛑UPDATE YT-DLP EMMERGENCY🛑: {result.stderr}")
            await notify_admin(f"🛑UPDATE YT-DLP EMMERGENCY🛑\nTask: {task_id}\n{result.stderr}")
            raise Exception("do not retry")
        
        if result.returncode == 0:
            try:
                video_info = json.loads(result.stdout)
                video_duration = video_info.get('duration', 0)
                formats = video_info.get('formats', [])

                if formats:
                    #logger.debug(f"[{task_id}] Found {len(formats)} formats via JSON method")
                    json_result = await _analyze_formats_from_json(formats, target_quality, task_id, video_duration)
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
        #logger.debug(f"[{task_id}] Fallback to text parsing method...")
        
        cmd = [
            "yt-dlp", 
            "--list-formats",
            "--no-playlist",
            "--no-warnings",
        ]
        if use_cookies:
            cmd += ["--cookies", "cookies.txt"]
        cmd += [
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "--add-header", "Accept-Language:en-US,en;q=0.9,en;q=0.8",
            "--add-header", "Accept-Encoding:gzip, deflate, br",
            "--add-header", "Accept:text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "--add-header", "Accept-Charset:utf-8, iso-8859-1;q=0.5, *;q=0.1",
            "--add-header", "Connection:keep-alive",
            "--add-header", "Upgrade-Insecure-Requests:1",
            "--add-header", "Sec-Fetch-Dest:document",
            "--add-header", "Sec-Fetch-Mode:navigate",
            "--add-header", "Sec-Fetch-Site:none",
            "--add-header", "Sec-Fetch-User:?1",
            "--add-header", "Cache-Control:max-age=0",
            "--add-header", "DNT:1",
            # "--sleep-interval", "2",  # Sleep 2 seconds between requests
            # "--max-sleep-interval", "5",  # Max 5 seconds sleep
            video_url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if "Failed to extract any player response" in result.stderr:
            logger.error(f"[{task_id}] 🛑UPDATE YT-DLP EMMERGENCY🛑: {result.stderr}")
            await notify_admin(f"🛑UPDATE YT-DLP EMMERGENCY🛑\nTask: {task_id}\n{result.stderr}")
            raise Exception("do not retry")
        
        if result.returncode == 0:
            # Log the actual output for debugging
            #logger.debug(f"[{task_id}] yt-dlp output preview: {result.stdout[:500]}...")
            
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
            ]
            if use_cookies:
                test_cmd += ["--cookies", "cookies.txt"]
            test_cmd += [
                "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "--add-header", "Accept-Language:en-US,en;q=0.9,en;q=0.8",
                "--add-header", "Accept-Encoding:gzip, deflate, br",
                "--add-header", "Accept:text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
                "--add-header", "Accept-Charset:utf-8, iso-8859-1;q=0.5, *;q=0.1",
                "--add-header", "Connection:keep-alive",
                "--add-header", "Upgrade-Insecure-Requests:1",
                "--add-header", "Sec-Fetch-Dest:document",
                "--add-header", "Sec-Fetch-Mode:navigate",
                "--add-header", "Sec-Fetch-Site:none",
                "--add-header", "Sec-Fetch-User:?1",
                "--add-header", "Cache-Control:max-age=0",
                "--add-header", "DNT:1",
                # "--sleep-interval", "2",  # Sleep 2 seconds between requests
                # "--max-sleep-interval", "5",  # Max 5 seconds sleep
                video_url
            ]
            
            test_result = subprocess.run(test_cmd, capture_output=True, timeout=30)
            
            if test_result.returncode == 0:
                #logger.debug(f"[{task_id}] Using fallback format: {format_selector}")
                estimated_size = 700_000_000  # 700MB default estimate
                return (format_selector, can_copy, estimated_size)
        
        except Exception as e:
            logger.debug(f"[{task_id}] Format {format_selector} test failed: {e}")
            continue

    # If all else fails
    logger.error(f"[{task_id}] All format detection methods failed")
    return None

async def _analyze_formats_from_json(formats: list, target_quality: str, task_id: str, video_duration: float = 0) -> Optional[tuple]:
    """Analyze formats from JSON data with original audio preference and return estimated size"""
    video_only_formats = []
    audio_only_formats = []  
    combined_formats = []
    target_height = int(target_quality.replace('p', ''))
    for fmt in formats:
        format_id = fmt.get('format_id')
        ext = fmt.get('ext', 'unknown')
        vcodec = fmt.get('vcodec', 'none')
        acodec = fmt.get('acodec', 'none')
        width = fmt.get('width')
        height = fmt.get('height')
        language = fmt.get('language', 'unknown')
        language_preference = fmt.get('language_preference', -1)
        filesize = fmt.get('filesize') or fmt.get('filesize_approx') or 0
        if not format_id:
            continue
        if vcodec == 'none' and acodec != 'none':
            is_original = (
                language_preference == 10 or
                language in ['original', 'default', 'primary'] or
                'original' in str(fmt).lower()
            )
            audio_only_formats.append({
                'id': format_id,
                'ext': ext,
                'acodec': acodec,
                'abr': fmt.get('abr', 0),
                'language': language,
                'language_preference': language_preference,
                'is_original': is_original,
                'filesize': filesize
            })
        elif vcodec != 'none' and acodec == 'none' and width and height:
            video_only_formats.append({
                'id': format_id,
                'ext': ext,
                'vcodec': vcodec,
                'width': width,
                'height': height,
                'tbr': fmt.get('tbr', 0),
                'filesize': filesize
            })
        elif vcodec != 'none' and acodec != 'none' and width and height:
            is_original = (
                language_preference == 10 or
                language in ['original', 'default', 'primary'] or
                'original' in str(fmt).lower()
            )
            combined_formats.append({
                'id': format_id,
                'ext': ext,
                'vcodec': vcodec,
                'acodec': acodec,
                'width': width,
                'height': height,
                'tbr': fmt.get('tbr', 0),
                'language': language,
                'language_preference': language_preference,
                'is_original': is_original,
                'filesize': filesize
            })
    # Strategy 1: Try good quality combined formats with original audio first
    if combined_formats:
        combined_formats.sort(key=lambda x: (not x.get('is_original', False), x['height'], x['ext'] == 'mp4'), reverse=True)
        for fmt in combined_formats:
            if fmt['height'] >= 1080 and fmt.get('is_original', False):
                can_copy = fmt['ext'] == 'mp4'
                estimated_size = fmt.get('filesize', 0)
                return (fmt['id'], can_copy, estimated_size)
    # Strategy 2: Merge video-only + original audio-only
    if video_only_formats and audio_only_formats:
        video_only_formats.sort(key=lambda x: (x['height'], x['ext'] == 'mp4'), reverse=True)
        def audio_sort_key(fmt):
            is_orig = fmt.get('is_original', False)
            lang_pref = fmt.get('language_preference', -999)
            is_m4a = fmt['ext'] in ['m4a', 'mp4']
            abr = fmt.get('abr', 0)
            return (is_orig, lang_pref, is_m4a, abr)
        audio_only_formats.sort(key=audio_sort_key, reverse=True)
        best_video = None
        for fmt in video_only_formats:
            if fmt['height'] <= target_height * 1.2:
                best_video = fmt
                break
        if not best_video:
            best_video = video_only_formats[0]
        best_audio = audio_only_formats[0]
        
        # LOG ALL AVAILABLE METADATA for selected formats
        logger.debug(f"[{task_id}] 🔍 SELECTED VIDEO FORMAT METADATA:")
        for key, value in best_video.items():
            logger.debug(f"[{task_id}] 🔍   video.{key}: {value}")
        
        logger.debug(f"[{task_id}] 🔍 SELECTED AUDIO FORMAT METADATA:")
        for key, value in best_audio.items():
            logger.debug(f"[{task_id}] 🔍   audio.{key}: {value}")
        
        can_copy = (best_video['ext'] == 'mp4' and best_audio['ext'] in ['m4a', 'mp4'])
        merge_format = f"{best_video['id']}+{best_audio['id']}"
        
        # Extract file sizes with detailed analysis
        video_size = best_video.get('filesize', 0) or best_video.get('filesize_approx', 0) or 0
        audio_size = best_audio.get('filesize', 0) or best_audio.get('filesize_approx', 0) or 0
        estimated_size = video_size + audio_size
        
        # Try to estimate size from bitrate if filesize is missing/wrong
        video_tbr = best_video.get('tbr', 0) or best_video.get('vbr', 0) or 0
        audio_abr = best_audio.get('abr', 0) or 0
        duration = video_duration or best_video.get('duration', 0) or best_audio.get('duration', 0) or 0
        
        # If we still don't have duration, estimate from bitrate and typical video lengths
        if duration == 0 and video_tbr > 0:
            # Estimate duration from audio file size and bitrate
            if audio_size > 0 and audio_abr > 0:
                duration = audio_size * 8 / (audio_abr * 1000)  # Convert back to seconds
                logger.debug(f"[{task_id}] 🔍 Estimated duration from audio: {duration:.1f}s")
            else:
                # Default to 10 minutes for typical videos
                duration = 600
                logger.warning(f"[{task_id}] 🔍 No duration available, assuming 10 minutes")
        
        logger.debug(f"[{task_id}] 🔍 SIZE CALCULATION:")
        logger.debug(f"[{task_id}] 🔍   video_size (from metadata): {video_size} bytes ({video_size/1024/1024:.1f}MB)")
        logger.debug(f"[{task_id}] 🔍   audio_size (from metadata): {audio_size} bytes ({audio_size/1024/1024:.1f}MB)")
        logger.debug(f"[{task_id}] 🔍   estimated_size (sum): {estimated_size} bytes ({estimated_size/1024/1024:.1f}MB)")
        logger.debug(f"[{task_id}] 🔍   video_tbr: {video_tbr} kbps, audio_abr: {audio_abr} kbps, duration: {duration}s")
        
        # Calculate size from bitrate if available and duration exists
        if duration > 0 and (video_tbr > 0 or audio_abr > 0):
            # Convert kbps to bytes: (kbps * 1000 / 8) * duration_seconds
            video_size_from_br = int((video_tbr * 1000 / 8) * duration) if video_tbr > 0 else 0
            audio_size_from_br = int((audio_abr * 1000 / 8) * duration) if audio_abr > 0 else 0
            total_size_from_br = video_size_from_br + audio_size_from_br
            
            logger.debug(f"[{task_id}] 🔍 BITRATE-BASED CALCULATION:")
            logger.debug(f"[{task_id}] 🔍   video_size (from bitrate): {video_size_from_br} bytes ({video_size_from_br/1024/1024:.1f}MB)")
            logger.debug(f"[{task_id}] 🔍   audio_size (from bitrate): {audio_size_from_br} bytes ({audio_size_from_br/1024/1024:.1f}MB)")
            logger.debug(f"[{task_id}] 🔍   total_size (from bitrate): {total_size_from_br} bytes ({total_size_from_br/1024/1024:.1f}MB)")
            
            # Use bitrate calculation if metadata size seems wrong or missing
            if estimated_size == 0 or (estimated_size > 0 and estimated_size < 10_000_000):
                logger.debug(f"[{task_id}] 🔍 Metadata size seems wrong ({estimated_size/1024/1024:.1f}MB), using bitrate calculation instead")
                estimated_size = total_size_from_br
            elif abs(estimated_size - total_size_from_br) > estimated_size * 0.5:  # >50% difference
                logger.debug(f"[{task_id}] 🔍 Large discrepancy between metadata ({estimated_size/1024/1024:.1f}MB) and bitrate ({total_size_from_br/1024/1024:.1f}MB)")
                logger.debug(f"[{task_id}] 🔍 Using average of both: {(estimated_size + total_size_from_br)/2/1024/1024:.1f}MB")
                estimated_size = (estimated_size + total_size_from_br) // 2
        
        # Final sanity check and fallback
        if estimated_size == 0:
            logger.warning(f"[{task_id}] 🔍 No size info available, using 150MB default estimate")
            estimated_size = 150_000_000
        elif estimated_size < 5_000_000:  # Less than 5MB
            logger.warning(f"[{task_id}] 🔍 Size {estimated_size/1024/1024:.1f}MB seems too small, using 100MB estimate")
            estimated_size = 100_000_000
        
        logger.debug(f"[{task_id}] 🔍 FINAL RESULT: {merge_format}, size: {estimated_size} bytes ({estimated_size/1024/1024:.1f}MB)")
        return (merge_format, can_copy, estimated_size)
    logger.debug(f"[{task_id}] JSON analysis found no suitable formats, will try fallback methods")
    return None

async def _analyze_formats_from_text(output: str, target_quality: str, task_id: str) -> Optional[tuple]:
    """Analyze formats from text output with original audio preference and return estimated size (not always possible)"""
    
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
                #logger.debug(f"[{task_id}] Found format table at line {i} with pattern '{pattern}'")
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
                    #logger.debug(f"[{task_id}] Guessed format table start at line {i}")
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
        
        # Check if this is original audio (look for language indicators in the line)
        is_original = any(indicator in line.lower() for indicator in [
            'original', 'default', 'primary', 'first', 'main'
        ])
        
        # Categorize formats
        if resolution == 'audio' or 'audio only' in line.lower():
            # Audio-only format
            audio_only_formats.append({
                'id': format_id,
                'ext': ext,
                'line': line,
                'is_original': is_original
            })
            #logger.debug(f"[{task_id}]   {format_id}: AUDIO-ONLY ({ext}) - Original: {is_original}")
            
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
                    #logger.debug(f"[{task_id}]   {format_id}: {width}x{height} ({ext}) - VIDEO-ONLY")
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
                    'line': line,
                    'is_original': is_original
                })
            except ValueError:
                continue
    
    # Strategy 1: Try good quality combined formats with original audio first
    if combined_formats:
        combined_formats.sort(key=lambda x: (not x.get('is_original', False), x['height'], x['ext'] == 'mp4'), reverse=True)
        
        # Find good quality combined format with original audio
        for fmt in combined_formats:
            if fmt['height'] >= 1080 and fmt.get('is_original', False):  # Accept 1080+ combined formats + only original audio
                can_copy = fmt['ext'] == 'mp4'
                is_original = fmt.get('is_original', False)
                # If we can't get a real size, use 1GB as a fallback
                estimated_size = 1_000_000_000
                return (fmt['id'], can_copy, estimated_size)
    
    # Strategy 2: Merge best video-only + original audio-only for higher quality
    if video_only_formats and audio_only_formats:
        # Sort video formats: prefer MP4, then by height (descending)
        video_only_formats.sort(key=lambda x: (x['height'], x['ext'] == 'mp4'), reverse=True)
        
        # Sort audio formats: original audio first, then prefer m4a/mp4, then others
        audio_only_formats.sort(key=lambda x: (
            not x.get('is_original', False),  # Original audio first
            x.get('language_preference', -999), # Higher preference = more "original"
            x['ext'] in ['m4a', 'mp4'], # Then prefer m4a/mp4
            x.get('abr', 0) # Then by bitrate
        ), reverse=True)
   
        # Find best video at target quality
        best_video = None
        for fmt in video_only_formats:
            if fmt['height'] <= target_height * 1.2:  # Allow some tolerance
                best_video = fmt
                break
        
        if not best_video:
            # Use highest available video quality
            best_video = video_only_formats[0]
        
        # Use best original audio (prefer m4a/mp4 for compatibility)
        best_audio = audio_only_formats[0]
        
        # Check if we can use fast copy (both MP4-compatible)
        can_copy = (best_video['ext'] == 'mp4' and best_audio['ext'] in ['m4a', 'mp4'])
        
        merge_format = f"{best_video['id']}+{best_audio['id']}"
        is_original = best_audio.get('is_original', False)
        # If we can't get a real size, use 1GB as a fallback
        estimated_size = 1_000_000_000
        return (merge_format, can_copy, estimated_size)
    
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
        
        #logger.debug(f"[{task_id}] Video resolution: {width}x{height} -> {quality}")
        return quality
        
    except Exception as e:
        logger.error(f"[{task_id}] Error verifying video quality: {e}")
        return None

def get_downloaded_bytes(task_id, download_dir):
    """
    Simple function to sum all file sizes in the task-specific download directory.
    Since each task has its own directory, we can safely count all files.
    """
    total = 0
    files_found = []
    
    try:
        if not os.path.exists(download_dir):
            return 0
            
        all_files = os.listdir(download_dir)
        
        # Sum all files in the directory - they all belong to this task
        for fname in all_files:
            fpath = os.path.join(download_dir, fname)
            if os.path.isfile(fpath):
                file_size = os.path.getsize(fpath)
                total += file_size
                files_found.append(f"{fname}:{file_size}")
        
        # Log progress periodically for debugging
        call_key = f"_call_count_{task_id}"
        if hasattr(get_downloaded_bytes, call_key):
            count = getattr(get_downloaded_bytes, call_key) + 1
            setattr(get_downloaded_bytes, call_key, count)
        else:
            count = 1
            setattr(get_downloaded_bytes, call_key, count)
            
        # Enhanced debugging - log more frequently when we have files
        should_log = (count == 1 or count % 12 == 0 or len(files_found) > 0)
        
        if should_log:
            logger.debug(f"[{task_id}] 🔍 Downloads scan #{count}: total={total} bytes from {len(files_found)} files in {download_dir}")
            if len(files_found) <= 20:  # Show files if not too many
                logger.debug(f"[{task_id}] 🔍 Files: {files_found}")
            
            # Also check what's in parent directories for debugging
            if count <= 3:  # Only for first few checks to avoid spam
                try:
                    parent_dir = os.path.dirname(download_dir)
                    if os.path.exists(parent_dir):
                        parent_files = []
                        for fname in os.listdir(parent_dir):
                            fpath = os.path.join(parent_dir, fname)
                            if os.path.isfile(fpath):
                                file_size = os.path.getsize(fpath)
                                parent_files.append(f"{fname}:{file_size}")
                        logger.debug(f"[{task_id}] 🔍 Parent dir ({parent_dir}) files: {parent_files[:10]}")  # Show max 10
                except Exception as e:
                    logger.debug(f"[{task_id}] Could not check parent directory: {e}")
            
    except Exception as e:
        logger.error(f"[{task_id}] Error in get_downloaded_bytes: {e}")
        
    return total

async def handle_youtube_download_task_with_retries(task_id: str, video_url: str, tmdb_id: int, lang: str, dub: str, video_title: str, video_poster: str):
    """Handle YouTube video download task with simple retry strategy and IP rotation - retries on any error until max attempts"""
    
    max_attempts = 3
    sleep_between_retries = 5  # seconds

    for attempt in range(max_attempts):
        logger.debug(f"[{task_id}] 🚀 Download attempt {attempt + 1}/{max_attempts}")
        
        # Set status to downloading for each attempt
        redis = RedisClient.get_client()
        await redis.set(f"download:{task_id}:status", "downloading", ex=3600)
        logger.debug(f"[{task_id}] ✅ Status set to 'downloading' for attempt {attempt + 1}")

        try:
            # Call the main download handler
            use_cookies = (attempt == max_attempts - 1)
            await handle_youtube_download_task(task_id, video_url, tmdb_id, lang, dub, video_title, video_poster, use_cookies=use_cookies)
            logger.debug(f"[{task_id}] ✅ Download successful on attempt {attempt + 1}")
            return  # Success - exit the retry loop

        except Exception as e:
            if 'do not retry' in str(e):
                await redis.set(f"download:{task_id}:status", "error", ex=3600)
                await redis.set(f"download:{task_id}:error", 'YT-DLP needs update, YT download wont work', ex=3600)
                return

            logger.error(f"[{task_id}] Error on attempt {attempt + 1}: {e}")
            
            if attempt < max_attempts - 1:
                await notify_admin(f"[Download Task {task_id}] Retrying YouTube download (attempt {attempt + 1}/{max_attempts}). Error: {e}")
                from backend.video_redirector.utils.pyrogram_acc_manager import rotate_proxy_ip_immediate
                logger.warning(f"[{task_id}] Triggering IP rotation due to YouTube download failure")
                await rotate_proxy_ip_immediate("YouTube download failures")
                await asyncio.sleep(sleep_between_retries)
                continue
            else:
                logger.error(f"[{task_id}] All {max_attempts} attempts failed")
                # Set final error status only when all retries are exhausted
                redis = RedisClient.get_client()
                await redis.set(f"download:{task_id}:status", "error", ex=3600)
                await redis.set(f"download:{task_id}:error", str(e), ex=3600)
                raise

    # This should never be reached, but just in case
    logger.error(f"[{task_id}] All download attempts failed")
    raise Exception("All download attempts failed")

async def handle_youtube_download_task(task_id: str, video_url: str, tmdb_id: int, lang: str, dub: str, video_title: str, video_poster: str, use_cookies: bool = False):
    """
    Handle YouTube video download task - FULLY NON-BLOCKING
    
    """
    redis = RedisClient.get_client()
    
    # Remove from user's active downloads set when done (success or error)
    tg_user_id = None
    output_path = None
    
    try:
        # Get the best format ID and copy capability
        format_result = await get_best_format_id(video_url, "1080p", task_id, use_cookies=use_cookies)
        
        if not format_result:
            raise Exception("No suitable format found for video")
        
        # After starting the yt-dlp process, add a background task to periodically check progress by file size
        progress_check_interval = 5  # seconds
        progress_stop_flag = {'stop': False}
        estimated_size = 0
        last_progress = 0
        
        if isinstance(format_result, tuple) and len(format_result) == 3:
            format_selector, can_copy, estimated_size = format_result
        else:
            format_selector, can_copy = format_result
            
        async def progress_watcher():
            nonlocal last_progress
            start_time = asyncio.get_event_loop().time()
            last_size = 0
            default_size_estimate = 700_000_000  # 700MB default estimate
            loop_count = 0
            
            logger.debug(f"[{task_id}] 🔍 Progress watcher started with estimated_size={estimated_size}")
            
            try:
                while not progress_stop_flag['stop']:
                    loop_count += 1
                    downloaded = get_downloaded_bytes(task_id, get_task_download_dir(task_id))
                    
                    # Also check the output file directly (might be growing without temp files)
                    output_file_size = 0
                    if os.path.exists(output_path):
                        output_file_size = os.path.getsize(output_path)
                        if output_file_size > downloaded:
                            downloaded = output_file_size
                            if loop_count % 10 == 1:  # Debug every 10 loops
                                logger.debug(f"[{task_id}] 🔍 Using output file size: {output_file_size} bytes ({output_file_size/1024/1024:.1f}MB)")
                    
                    # Enhanced debugging - check multiple locations where yt-dlp might create files
                    if loop_count % 10 == 1:  # First loop and every 10th
                        logger.debug(f"[{task_id}] 🔍 Progress debug: loop={loop_count}, downloaded={downloaded}, estimated_size={estimated_size}, last_progress={last_progress}")
                        logger.debug(f"[{task_id}] 🔍 Output file exists: {os.path.exists(output_path)}, size: {output_file_size}")
                        
                        # Check for any files matching our task_id pattern in various locations
                        task_pattern_files = []
                        locations_to_check = [
                            get_task_download_dir(task_id),  # Our task directory
                            BASE_DOWNLOAD_DIR,               # Base downloads directory
                            "/tmp",                          # System temp (Linux)
                            "/var/tmp",                      # Alternative temp
                            ".",                             # Current working directory
                        ]
                        
                        for location in locations_to_check:
                            if os.path.exists(location):
                                try:
                                    for fname in os.listdir(location):
                                        if task_id in fname or any(pattern in fname.lower() for pattern in ['.part', '.tmp', '.ytdl', f'{task_id[:8]}']):
                                            fpath = os.path.join(location, fname)
                                            if os.path.isfile(fpath):
                                                file_size = os.path.getsize(fpath)
                                                task_pattern_files.append(f"{location}/{fname}:{file_size}")
                                except Exception as e:
                                    logger.debug(f"[{task_id}] Could not check {location}: {e}")
                        
                        if task_pattern_files:
                            logger.debug(f"[{task_id}] 🔍 Found task-related files: {task_pattern_files}")
                            # Use the largest file we found as progress
                            largest_size = max(int(f.split(':')[-1]) for f in task_pattern_files)
                            if largest_size > downloaded:
                                downloaded = largest_size
                                logger.debug(f"[{task_id}] 🔍 Updated downloaded from task files: {downloaded} bytes")
                        else:
                            logger.debug(f"[{task_id}] 🔍 No task-related files found in any location")
                    
                    if estimated_size > 0:
                        percent = min(int((downloaded / estimated_size) * 100), 100)
                        if percent != last_progress and percent > 0:
                            await redis.set(f"download:{task_id}:yt_download_progress", percent, ex=3600)
                            last_progress = percent
                            logger.debug(f"[{task_id}] Progress: {percent}% ({downloaded}/{estimated_size} bytes)")
                        elif loop_count % 10 == 1:  # Debug every 10 loops
                            logger.debug(f"[{task_id}] 🔍 Progress not updated: percent={percent}, last_progress={last_progress}, downloaded={downloaded}")
                                                        
                    elif downloaded > 0:
                        elapsed_time = asyncio.get_event_loop().time() - start_time
                        size_growth = downloaded - last_size
                        last_size = downloaded
                        
                        if elapsed_time > 30 and size_growth > 0:
                            estimated_rate = downloaded / elapsed_time
                            estimated_total_time = max(300, min(900, downloaded / estimated_rate * 3))
                            percent = min(int((elapsed_time / estimated_total_time) * 100), 95)
                        else:
                            percent = min(int((downloaded / default_size_estimate) * 100), 95)
                        
                        if percent != last_progress and percent > 0:
                            await redis.set(f"download:{task_id}:yt_download_progress", percent, ex=3600)
                            last_progress = percent
                            logger.debug(f"[{task_id}] Progress (estimated): {percent}% ({downloaded} bytes downloaded)")
                        elif loop_count % 10 == 1:  # Debug every 10 loops
                            logger.debug(f"[{task_id}] 🔍 Progress not updated (no estimate): percent={percent}, last_progress={last_progress}, downloaded={downloaded}")
                    
                    else:
                        # No files detected yet - provide time-based progress estimate
                        elapsed_time = asyncio.get_event_loop().time() - start_time
                        
                        # Adaptive time estimate based on what we know
                        if elapsed_time > 15:  # Start after 15 seconds instead of 30
                            # For very fast downloads (small files), be more aggressive
                            if elapsed_time > 60:
                                # After 1 minute with no progress, something might be wrong OR it's a very slow download
                                time_progress = min(int(10 + (elapsed_time - 60) / 420 * 80), 95)  # 10% to 95% over 7 minutes
                            else:
                                # First minute: slower progress to allow for actual progress to kick in
                                time_progress = min(int((elapsed_time - 15) / 45 * 10), 10)  # 0% to 10% over 45 seconds
                            
                            if time_progress != last_progress:
                                await redis.set(f"download:{task_id}:yt_download_progress", time_progress, ex=3600)
                                last_progress = time_progress
                                logger.debug(f"[{task_id}] Progress (time-based fallback): {time_progress}% (no stdout progress detected, elapsed: {elapsed_time:.0f}s)")
                        
                        elif loop_count % 10 == 1:  # Debug when no download detected
                            logger.debug(f"[{task_id}] 🔍 No download detected: downloaded={downloaded}, estimated_size={estimated_size}, elapsed={elapsed_time:.0f}s")
                    
                    await asyncio.sleep(progress_check_interval)
                    
            except Exception as e:
                logger.error(f"[{task_id}] ❌ Progress watcher error: {e}", exc_info=True)
            finally:
                logger.debug(f"[{task_id}] 🔍 Progress watcher stopped after {loop_count} loops")
                
        progress_task = asyncio.create_task(progress_watcher())
        logger.debug(f"[{task_id}] 🔍 Progress watcher task created and started")

        # Download the video
        # IMPORTANT: name the file with a _part0 suffix so upload pipeline can infer part numbering
        output_path = os.path.join(get_task_download_dir(task_id), f"{task_id}_part0.mp4")
        
        if can_copy:
            # Fast path: copy streams (no re-encoding)
            postprocessor_args = "ffmpeg:-c:v copy -c:a copy -avoid_negative_ts make_zero -movflags +faststart"
            logger.debug(f"[{task_id}] Using FAST COPY mode")
        else:
            # Slow path: re-encode for compatibility
            postprocessor_args = "ffmpeg:-c:v libx264 -preset fast -crf 23 -c:a aac -b:a 128k -avoid_negative_ts make_zero -movflags +faststart"
            logger.debug(f"[{task_id}] Using RE-ENCODE mode")
        
        # Build yt-dlp command with enhanced anti-detection
        cmd = [
            "yt-dlp",
            "-f", format_selector,
            "-o", output_path,
            "--no-playlist",
            "--merge-output-format", "mp4",
            "--postprocessor-args", postprocessor_args,
            "--progress",  # Enable progress reporting
            "--newline",   # Output progress as new lines for easier parsing
        ]
        if use_cookies:
            cmd += ["--cookies", "cookies.txt"]
        cmd += [
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "--add-header", "Accept-Language:en-US,en;q=0.9,en;q=0.8",
            "--add-header", "Accept-Encoding:gzip, deflate, br",
            "--add-header", "Accept:text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "--add-header", "Accept-Charset:utf-8, iso-8859-1;q=0.5, *;q=0.1",
            "--add-header", "Connection:keep-alive",
            "--add-header", "Upgrade-Insecure-Requests:1",
            "--add-header", "Sec-Fetch-Dest:document",
            "--add-header", "Sec-Fetch-Mode:navigate",
            "--add-header", "Sec-Fetch-Site:none",
            "--add-header", "Sec-Fetch-User:?1",
            "--add-header", "Cache-Control:max-age=0",
            "--add-header", "DNT:1",
            "--paths", f"temp:{get_task_download_dir(task_id)}",  # Set temp directory to downloads folder
            video_url
        ]
        
        logger.debug(f"[{task_id}] Starting download with format: {format_selector}")
        if estimated_size > 0:
            logger.debug(f"[{task_id}] Estimated size: {estimated_size} bytes ({estimated_size/1024/1024:.1f}MB)")
        else:
            logger.debug(f"[{task_id}] No size estimate available, using adaptive progress tracking")
        logger.debug(f"[{task_id}] 🔍 Executing command: {' '.join(cmd)}")
        
        # Run yt-dlp with asyncio.subprocess - CAPTURE STDOUT for progress, stderr for errors
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,  # Progress is output to stdout!
            stderr=asyncio.subprocess.PIPE   # Errors go to stderr
        )

        logger.debug(f"[{task_id}] 🔍 Subprocess created with PID: {process.pid}")

        stdout_lines = []
        stderr_lines = []

        async def read_stdout():
            """Read stdout for progress information"""
            nonlocal last_progress
            frag_tracking_enabled = False  # Flag to track if we're using fragment-based progress
            total_frags = 0  # Store total fragments for consistent tracking
            
            try:
                line_count = 0
                while True:
                    line = await process.stdout.readline()
                    if not line:
                        logger.debug(f"[{task_id}] 🔍 stdout stream ended after {line_count} lines")
                        break
                    line_count += 1
                    decoded = line.decode(errors="ignore").strip()
                    stdout_lines.append(decoded)
                    
                    # Log all stdout output for debugging when few lines
                    if line_count <= 100:  # Log first 100 lines for debugging
                        logger.debug(f"[{task_id}] yt-dlp stdout #{line_count}: {decoded}")
                    
                    # Parse yt-dlp progress output from stdout - PRIORITIZE FRAGMENT TRACKING
                    if '[download]' in decoded:
                        try:
                            percent = None
                            
                            # FIRST PRIORITY: Check for fragment progress
                            frag_match = re.search(r'\(frag (\d+)/(\d+)\)', decoded)
                            if frag_match:
                                current_frag = int(frag_match.group(1))
                                total_frags = int(frag_match.group(2))
                                frag_percent = int((current_frag / total_frags) * 100)
                                
                                # Enable fragment tracking if this is the first time we see it
                                if not frag_tracking_enabled:
                                    frag_tracking_enabled = True
                                    logger.debug(f"[{task_id}] 🔍 Fragment tracking ENABLED: {current_frag}/{total_frags} = {frag_percent}%")
                                
                                percent = frag_percent
                                logger.debug(f"[{task_id}] 🔍 Fragment progress: {current_frag}/{total_frags} = {frag_percent}%")
                            
                            # SECOND PRIORITY: Check for fragment-only progress (no percentage) if fragment tracking not enabled
                            elif not frag_tracking_enabled and ('fragment' in decoded.lower() or 'frag' in decoded):
                                frag_match = re.search(r'(?:fragment|frag)\s+(\d+)\s+of\s+(\d+)', decoded, re.IGNORECASE)
                                
                                if frag_match:
                                    current_frag = int(frag_match.group(1))
                                    total_frags = int(frag_match.group(2))
                                    frag_percent = int((current_frag / total_frags) * 100)
                                    
                                    # Enable fragment tracking
                                    frag_tracking_enabled = True
                                    percent = frag_percent
                                    logger.debug(f"[{task_id}] 🔍 Fragment tracking ENABLED (alternative pattern): {current_frag}/{total_frags} = {frag_percent}%")
                            
                            # THIRD PRIORITY: Use other patterns ONLY if fragment tracking is not enabled
                            elif not frag_tracking_enabled:
                                # Pattern 1: Standard percentage progress
                                # [download] 45.2% of 350.00MiB at 2.50MiB/s ETA 01:23
                                if '%' in decoded:
                                    percent_match = re.search(r'(\d+\.?\d*)%', decoded)
                                    if percent_match:
                                        percent = int(float(percent_match.group(1)))
                                        logger.debug(f"[{task_id}] 🔍 Standard percentage progress: {percent}%")
                                
                                # Pattern 2: File size progress without percentage
                                # [download] 350.00MiB at 2.50MiB/s ETA 01:23
                                elif 'MiB' in decoded or 'MB' in decoded or 'GiB' in decoded or 'GB' in decoded:
                                    # Try to estimate progress from downloaded vs estimated size
                                    size_match = re.search(r'(\d+\.?\d*)\s*(MiB|MB|GiB|GB)', decoded)
                                    if size_match and estimated_size > 0:
                                        downloaded_size_str = size_match.group(1)
                                        unit = size_match.group(2)
                                        
                                        # Convert to bytes
                                        downloaded_bytes = float(downloaded_size_str)
                                        if unit in ['MiB', 'MB']:
                                            downloaded_bytes *= 1024 * 1024 if unit == 'MiB' else 1000 * 1000
                                        elif unit in ['GiB', 'GB']:
                                            downloaded_bytes *= 1024 * 1024 * 1024 if unit == 'GiB' else 1000 * 1000 * 1000
                                        
                                        percent = min(int((downloaded_bytes / estimated_size) * 100), 99)
                                        logger.debug(f"[{task_id}] 🔍 Size-based progress: {downloaded_size_str}{unit} = {percent}%")
                                
                                # Pattern 3: Completion indicators
                                elif 'downloaded' in decoded.lower() and 'completed' not in decoded.lower():
                                    # Look for completion messages
                                    if any(word in decoded.lower() for word in ['finished', 'complete', 'done']):
                                        percent = 100
                                        logger.debug(f"[{task_id}] 🔍 Completion detected: {decoded}")
                            
                            # Update progress if we found any
                            if percent is not None and percent != last_progress and percent > 0:
                                await redis.set(f"download:{task_id}:yt_download_progress", percent, ex=3600)
                                last_progress = percent
                                logger.debug(f"[{task_id}] ✅ yt-dlp Progress: {percent}% - {decoded}")
                                
                        except Exception as e:
                            logger.debug(f"[{task_id}] Error parsing progress from stdout: {e}")
                    
                    # Pattern 4: Post-processing progress
                    elif '[ffmpeg]' in decoded:
                        logger.debug(f"[{task_id}] yt-dlp ffmpeg: {decoded}")
                        # Post-processing usually means download is 100%, processing is additional
                        if last_progress < 100:
                            await redis.set(f"download:{task_id}:yt_download_progress", 100, ex=3600)
                            last_progress = 100
                            logger.debug(f"[{task_id}] ✅ Download complete, post-processing started")
                    
                    # Pattern 5: File already exists/cached
                    elif 'already' in decoded.lower() and ('exist' in decoded.lower() or 'download' in decoded.lower()):
                        logger.debug(f"[{task_id}] File already exists/cached: {decoded}")
                        await redis.set(f"download:{task_id}:yt_download_progress", 100, ex=3600)
                        last_progress = 100
                    
            except Exception as e:
                logger.error(f"[{task_id}] Error reading stdout stream: {e}")
            finally:
                logger.debug(f"[{task_id}] 🔍 stdout reader finished after processing {line_count} lines")

        async def read_stderr():
            """Read stderr for error information"""
            try:
                line_count = 0
                while True:
                    line = await process.stderr.readline()
                    if not line:
                        logger.debug(f"[{task_id}] 🔍 stderr stream ended after {line_count} lines")
                        break
                    line_count += 1
                    decoded = line.decode(errors="ignore").strip()
                    stderr_lines.append(decoded)
                    
                    # Log stderr output for debugging when few lines or important messages
                    if line_count <= 50 or 'ERROR' in decoded.upper() or 'WARNING' in decoded.upper():
                        logger.debug(f"[{task_id}] yt-dlp stderr #{line_count}: {decoded}")
                    
                    # Catch important messages from stderr
                    if 'ERROR' in decoded.upper():
                        logger.error(f"[{task_id}] yt-dlp ERROR: {decoded}")
                    elif 'WARNING' in decoded.upper():
                        logger.warning(f"[{task_id}] yt-dlp WARNING: {decoded}")
                    
            except Exception as e:
                logger.error(f"[{task_id}] Error reading stderr stream: {e}")
            finally:
                logger.debug(f"[{task_id}] 🔍 stderr reader finished after processing {line_count} lines")

        # Set a reasonable timeout for the download (30 minutes max)
        download_timeout = 1200  # 20 minutes
        
        try:
            # Run both stdout and stderr readers concurrently with timeout
            await asyncio.wait_for(
                asyncio.gather(
                    read_stdout(),  # Progress tracking from stdout
                    read_stderr()   # Error detection from stderr
                ), 
                timeout=download_timeout
            )
            
            # Wait for process to complete
            returncode = await asyncio.wait_for(process.wait(), timeout=60)
            
        except asyncio.TimeoutError:
            logger.error(f"[{task_id}] Download timed out after {download_timeout} seconds, terminating process")
            
            # Kill the process
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=10)
            except asyncio.TimeoutError:
                logger.error(f"[{task_id}] Process didn't terminate gracefully, killing it")
                process.kill()
                await process.wait()
            
            raise Exception(f"Download timed out after {download_timeout/60:.1f} minutes")
        
        # Stop progress watcher
        progress_stop_flag['stop'] = True
        await asyncio.sleep(progress_check_interval)  # Let watcher finish last update
        progress_task.cancel()
        try:
            await progress_task
        except asyncio.CancelledError:
            pass

        # Combine stdout and stderr for error analysis
        stdout_text = '\n'.join(stdout_lines)
        stderr_text = '\n'.join(stderr_lines)
        combined_output = f"STDOUT:\n{stdout_text}\n\nSTDERR:\n{stderr_text}"

        logger.debug(f"[{task_id}] Process finished with return code: {returncode}")
        
        # Ensure progress reaches 100% on successful completion
        if returncode == 0 and last_progress < 100:
            await redis.set(f"download:{task_id}:yt_download_progress", 100, ex=3600)
            logger.debug(f"[{task_id}] ✅ Process completed successfully, setting progress to 100%")
        
        if returncode != 0:
            error_output = stderr_text or stdout_text or 'Unknown error'
            error_msg = f"yt-dlp failed: {error_output}"
            
            # Check for specific YouTube blocking patterns in both stdout and stderr
            if "HTTP Error 403" in combined_output or "Forbidden" in combined_output:
                logger.warning(f"[{task_id}] YouTube 403 Forbidden detected - likely anti-bot protection")
                raise Exception(f"YouTube blocked access (403 Forbidden): {error_output}")
            elif "fragment 1 not found" in combined_output:
                logger.warning(f"[{task_id}] Fragment not found - likely format availability issue")
                raise Exception(f"Video format not available: {error_output}")
            elif "Requested format is not available" in combined_output:
                logger.warning(f"[{task_id}] Requested format not available - trying different approach")
                raise Exception(f"Format not available: {error_output}")
            else:
                raise Exception(error_msg)
        
        # Check if file was created and has content
        if not os.path.exists(output_path):
            raise Exception("Output file not created")
        
        file_size = os.path.getsize(output_path)
        if file_size == 0:
            os.remove(output_path)
            raise Exception("Downloaded file is empty")
        
        logger.debug(f"[{task_id}] Successfully downloaded: {output_path} ({file_size / (1024*1024):.1f}MB)")
        
        # Verify the actual quality of the downloaded video
        actual_quality = await verify_video_quality(output_path, task_id)
        if actual_quality:
            logger.debug(f"[{task_id}] Actual downloaded quality: {actual_quality}")
        
        # Continue with upload (this part stays in main process like HDRezka)
        await redis.set(f"download:{task_id}:status", "uploading", ex=3600)
        logger.debug(f"[{task_id}] ✅ Status set to 'uploading' at {datetime.now().isoformat()}")

        # Upload using the shared HDRezka upload pipeline with delivery-bot rotation
        try:
            upload_results = await process_parallel_uploads([output_path], task_id)
            consolidated = await consolidate_upload_results(upload_results, task_id)
            if not consolidated:
                raise Exception("Failed to consolidate upload results.")

            tg_bot_token_file_owner = consolidated["bot_token"]
            parts = consolidated["parts"]
            session_name = consolidated["session_name"]

            # Save in DB using existing structure - handle duplicates gracefully
            async for session in get_db():
                # Check if file already exists
                existing_file = await get_file_id(session, tmdb_id, lang, dub)

                if existing_file:
                    # Update existing record with new file info
                    logger.debug(f"[{task_id}] Updating existing YouTube file record (ID: {existing_file.id})")
                    for attr, value in [
                        ("quality", actual_quality or "unknown"),
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
                        quality=actual_quality or "unknown",
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
                if not parts:
                    raise Exception("Upload to Telegram failed: consolidated parts list is empty")
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

            logger.debug(f"[{task_id}] YouTube download completed successfully")

        except Exception as upload_error:
            logger.error(f"[{task_id}] Upload failed after successful download: {upload_error}")
            raise
        
        # On completion, set progress to 100
        await redis.set(f"download:{task_id}:yt_download_progress", 100, ex=3600)
        
    except Exception as e:
        logger.error(f"[{task_id}] ❌ Download failed: {e}")
        await notify_admin(f"[Download Task {task_id}] YouTube download failed: {e}")
        raise e
    finally:
        # Get the task-specific download directory for cleanup
        task_download_dir = get_task_download_dir(task_id)
        
        # Clean up downloaded file
        if output_path and os.path.exists(output_path):
            try:
                os.remove(output_path)
                logger.debug(f"[{task_id}] Cleaned up downloaded file: {output_path}")
            except Exception as e:
                logger.warning(f"[{task_id}] Failed to clean up file {output_path}: {e}")
        
        # Clean up the entire task directory and all its contents
        if os.path.exists(task_download_dir):
            try:
                shutil.rmtree(task_download_dir)
                logger.debug(f"[{task_id}] ✅ Cleaned up task directory: {task_download_dir}")
            except Exception as e:
                logger.warning(f"[{task_id}] Failed to clean up directory {task_download_dir}: {e}")
        
        # Remove from user's active downloads set
        if tg_user_id is None:
            # Try to get from Redis
            tg_user_id = await redis.get(f"download:{task_id}:user_id")
        if tg_user_id:
            await redis.srem(f"active_downloads:{tg_user_id}", task_id) # type: ignore

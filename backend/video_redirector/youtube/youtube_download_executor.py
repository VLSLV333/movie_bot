import asyncio
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

async def debug_available_formats(video_url: str, task_id: str):
    """Debug function to log all available formats for troubleshooting"""
    try:
        logger.info(f"[{task_id}] 🔍 Debug: Getting all available formats...")
        
        cmd = [
            "yt-dlp",
            "--list-formats",
            "--no-playlist",
            "--no-warnings",
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "--add-header", "Accept-Language:en-US,en;q=0.9",
            "--add-header", "Accept-Encoding:gzip, deflate",
            video_url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            
            # Log full format table for debugging
            logger.info(f"[{task_id}] 🔍 Debug: FULL format list ({len(lines)} lines):")
            for i, line in enumerate(lines):
                logger.info(f"[{task_id}] 🔍 {i+1:3d}: {line}")
            
            # Focus on audio-only formats specifically
            logger.info(f"[{task_id}] 🔍 Debug: AUDIO-ONLY formats analysis:")
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
                    logger.info(f"[{task_id}] 🔍 AUDIO #{audio_count:2d}: {line}{indicator_str}")
            
            if audio_count == 0:
                logger.warning(f"[{task_id}] 🔍 Debug: NO audio-only formats found in text output!")
        else:
            logger.warning(f"[{task_id}] 🔍 Debug: Failed to get formats: {result.stderr}")
            
    except Exception as e:
        logger.warning(f"[{task_id}] 🔍 Debug: Error getting formats: {e}")

async def get_best_format_id(video_url: str, target_quality: str, task_id: str) -> Optional[tuple]:
    """Get the best format ID that has both video and audio, or merge video+audio IDs - ROBUST VERSION"""

    # If all else fails, debug what formats are available
    await debug_available_formats(video_url, task_id)

    # Strategy 1: Try JSON-based format detection (most reliable)
    try:
        logger.info(f"[{task_id}] Getting video formats using JSON method...")
        
        cmd = [
            "yt-dlp",
            "--dump-json",
            "--no-playlist", 
            "--no-warnings",
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "--add-header", "Accept-Language:en-US,en;q=0.9",
            "--add-header", "Accept-Encoding:gzip, deflate",
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
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "--add-header", "Accept-Language:en-US,en;q=0.9",
            "--add-header", "Accept-Encoding:gzip, deflate",
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
                "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "--add-header", "Accept-Language:en-US,en;q=0.9",
                "--add-header", "Accept-Encoding:gzip, deflate",
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
    """Analyze formats from JSON data with original audio preference"""
    video_only_formats = []
    audio_only_formats = []  
    combined_formats = []
    
    target_height = int(target_quality.replace('p', ''))
    
    # Debug: Show ALL available formats first
    logger.info(f"[{task_id}] 🔍 JSON Debug: Analyzing {len(formats)} total formats")
    
    audio_format_debug = []
    
    # Categorize formats using reliable JSON data
    for fmt in formats:
        format_id = fmt.get('format_id')
        ext = fmt.get('ext', 'unknown')
        vcodec = fmt.get('vcodec', 'none')
        acodec = fmt.get('acodec', 'none')
        width = fmt.get('width')
        height = fmt.get('height')
        language = fmt.get('language', 'unknown')  # Get audio language
        language_preference = fmt.get('language_preference', -1)  # YouTube's language preference
        
        # Debug: Capture audio format details for analysis
        if vcodec == 'none' and acodec != 'none':
            # Check ALL possible original indicators
            original_checks = {
                'lang_pref_0': language_preference == 0,
                'lang_pref_1': language_preference == 1, 
                'lang_in_original_list': language in ['original', 'default', 'primary'],
                'lang_is_en': language and language.startswith('en'),
                'lang_is_none': language is None,
                'original_in_str': 'original' in str(fmt).lower(),
                'has_no_dub_marker': not any(marker in str(fmt).lower() for marker in ['-auto', 'dubbed', 'dub'])
            }
            
            audio_format_debug.append({
                'id': format_id,
                'ext': ext,
                'acodec': acodec,
                'language': language,
                'language_preference': language_preference,
                'original_checks': original_checks,
                'raw_format': str(fmt)[:200] + "..." if len(str(fmt)) > 200 else str(fmt)
            })
        
        if not format_id:
            continue
        
        # Audio-only format
        if vcodec == 'none' and acodec != 'none':
            is_original = (
                language_preference == 0 or  # yt-dlp's primary indicator for original
                language in ['original', 'default', 'primary'] or
                language_preference == 1 or  # Often the first preference is original
                'original' in str(fmt).lower()  # Check if 'original' appears anywhere in format data
            )
            
            audio_only_formats.append({
                'id': format_id,
                'ext': ext,
                'acodec': acodec,
                'abr': fmt.get('abr', 0),
                'language': language,
                'language_preference': language_preference,
                'is_original': is_original
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
            # More flexible original audio detection for combined formats
            is_original = (
                language_preference == 0 or  # yt-dlp's primary indicator for original
                language in ['original', 'default', 'primary'] or
                language_preference == 1 or  # Often the first preference is original
                'original' in str(fmt).lower()  # Check if 'original' appears anywhere in format data
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
                'is_original': is_original
            })
    
    # Debug: Show detailed audio format analysis
    logger.info(f"[{task_id}] 🔍 JSON Debug: Found {len(audio_format_debug)} audio-only formats:")
    for i, audio_fmt in enumerate(audio_format_debug):
        checks = audio_fmt['original_checks']
        check_summary = [k for k, v in checks.items() if v]
        logger.info(f"[{task_id}] 🔍 AUDIO #{i+1}: {audio_fmt['id']} ({audio_fmt['ext']}, {audio_fmt['acodec']})")
        logger.info(f"[{task_id}] 🔍     Lang: {audio_fmt['language']}, Pref: {audio_fmt['language_preference']}")
        logger.info(f"[{task_id}] 🔍     Original checks passed: {check_summary}")
        logger.info(f"[{task_id}] 🔍     Raw: {audio_fmt['raw_format']}")
    
    logger.info(f"[{task_id}] Format analysis: {len(combined_formats)} combined, {len(video_only_formats)} video-only, {len(audio_only_formats)} audio-only")
    
    # Strategy 1: Try good quality combined formats with original audio first
    if combined_formats:
        # Sort by: original audio first, then height (descending), then prefer MP4
        combined_formats.sort(key=lambda x: (not x.get('is_original', False), x['height'], x['ext'] == 'mp4'), reverse=True)
        
        # original audio + 1080p+
        for fmt in combined_formats:
            if fmt['height'] >= 1080 and fmt.get('is_original', False):  # Accept 1080p+ combined formats + only original audio
                can_copy = fmt['ext'] == 'mp4'
                is_original = fmt.get('is_original', False)
                logger.info(f"[{task_id}] Selected combined format: {fmt['id']} ({fmt['width']}x{fmt['height']} {fmt['ext']}) - Original: {is_original} - Copy: {can_copy}")
                return (fmt['id'], can_copy)
    
    # Strategy 2: Merge video-only + original audio-only
    if video_only_formats and audio_only_formats:
        # Sort video formats: prefer MP4, then by height (descending)
        video_only_formats.sort(key=lambda x: (x['height'], x['ext'] == 'mp4'), reverse=True)
        
        # Sort audio formats: original audio first, then by quality (m4a/mp4 preferred)
        audio_only_formats.sort(key=lambda x: (
            not x.get('is_original', False),  # Original audio first
            x['ext'] in ['m4a', 'mp4'],       # Then prefer m4a/mp4
            x.get('abr', 0)                   # Then by bitrate
        ), reverse=True)
        
        # Log available audio formats for debugging
        logger.info(f"[{task_id}] Available audio formats:")
        for i, fmt in enumerate(audio_only_formats[:5]):
            logger.info(f"[{task_id}]   {i+1}. {fmt['id']}: {fmt['ext']} - Original: {fmt.get('is_original', False)} - Lang: {fmt.get('language', 'unknown')} - Pref: {fmt.get('language_preference', -1)}")
        
        # Find best video
        best_video = None
        for fmt in video_only_formats:
            if fmt['height'] <= target_height * 1.2:  # Allow some tolerance
                best_video = fmt
                break
        
        if not best_video:
            best_video = video_only_formats[0]  # Use highest quality
        
        # Use best original audio
        best_audio = audio_only_formats[0]
        
        can_copy = (best_video['ext'] == 'mp4' and best_audio['ext'] in ['m4a', 'mp4'])
        merge_format = f"{best_video['id']}+{best_audio['id']}"
        
        is_original = best_audio.get('is_original', False)
        logger.info(f"[{task_id}] Selected merge format: {merge_format}")
        logger.info(f"[{task_id}]   Video: {best_video['id']} ({best_video['width']}x{best_video['height']} {best_video['ext']})")
        logger.info(f"[{task_id}]   Audio: {best_audio['id']} ({best_audio['ext']}) - Original: {is_original} - Lang: {best_audio.get('language', 'unknown')}")
        logger.info(f"[{task_id}]   Can copy: {can_copy}")
        
        return (merge_format, can_copy)
    
    # If we can't find good formats, return None to allow main function's Strategy 3
    logger.warning(f"[{task_id}] JSON analysis found no suitable formats, will try fallback methods")
    return None

async def _analyze_formats_from_text(output: str, target_quality: str, task_id: str) -> Optional[tuple]:
    """Analyze formats from text output with original audio preference"""
    
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
            logger.info(f"[{task_id}]   {format_id}: AUDIO-ONLY ({ext}) - Original: {is_original}")
            
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
                    'line': line,
                    'is_original': is_original
                })
                logger.info(f"[{task_id}]   {format_id}: {width}x{height} ({ext}) - COMBINED - Original: {is_original}")
            except ValueError:
                continue
    
    # Strategy 1: Try good quality combined formats with original audio first
    if combined_formats:
        # Sort combined formats: original audio first, then prefer MP4, then by height (descending)
        combined_formats.sort(key=lambda x: (not x.get('is_original', False), x['height'], x['ext'] == 'mp4'), reverse=True)
        
        logger.info(f"[{task_id}] Available combined (video+audio) formats:")
        for fmt in combined_formats[:3]:
            logger.info(f"[{task_id}]   {fmt['id']}: {fmt['width']}x{fmt['height']} ({fmt['ext']}) - Original: {fmt.get('is_original', False)}")
        
        # Find good quality combined format with original audio
        for fmt in combined_formats:
            if fmt['height'] >= 1080 and fmt.get('is_original', False):  # Accept 1080+ combined formats + only original audio
                can_copy = fmt['ext'] == 'mp4'
                is_original = fmt.get('is_original', False)
                logger.info(f"[{task_id}] Selected COMBINED format: {fmt['id']} ({fmt['width']}x{fmt['height']} {fmt['ext']}) - Original: {is_original} - Can copy: {can_copy}")
                return (fmt['id'], can_copy)
    
    # Strategy 2: Merge best video-only + original audio-only for higher quality
    if video_only_formats and audio_only_formats:
        # Sort video formats: prefer MP4, then by height (descending)
        video_only_formats.sort(key=lambda x: (x['height'], x['ext'] == 'mp4'), reverse=True)
        
        # Sort audio formats: original audio first, then prefer m4a/mp4, then others
        audio_only_formats.sort(key=lambda x: (
            not x.get('is_original', False),  # Original audio first
            x['ext'] in ['m4a', 'mp4']        # Then prefer m4a/mp4
        ), reverse=True)
        
        logger.info(f"[{task_id}] Available video-only formats:")
        for fmt in video_only_formats[:3]:
            logger.info(f"[{task_id}]   {fmt['id']}: {fmt['width']}x{fmt['height']} ({fmt['ext']})")
        
        logger.info(f"[{task_id}] Available audio-only formats:")
        for fmt in audio_only_formats[:5]:
            logger.info(f"[{task_id}]   {fmt['id']}: ({fmt['ext']}) - Original: {fmt.get('is_original', False)}")
        
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
        logger.info(f"[{task_id}] Selected MERGE format: {merge_format}")
        logger.info(f"[{task_id}]   Video: {best_video['id']} ({best_video['width']}x{best_video['height']} {best_video['ext']})")
        logger.info(f"[{task_id}]   Audio: {best_audio['id']} ({best_audio['ext']}) - Original: {is_original}")
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
    """Download YouTube video with comprehensive retry strategy and IP rotation"""
    
    max_attempts = 3
    sleep_between_retries = 5  # seconds
    
    for attempt in range(max_attempts):
        logger.info(f"[{task_id}] Download attempt {attempt + 1}/{max_attempts}")
        
        try:
            result = await _try_youtube_download(video_url, task_id, attempt + 1)
            if result:
                logger.info(f"[{task_id}] ✅ Download successful on attempt {attempt + 1}")
                return result
                
        except subprocess.TimeoutExpired:
            logger.error(f"[{task_id}] Download timeout on attempt {attempt + 1}")
            if attempt < max_attempts - 1:
                logger.info(f"[{task_id}] Retrying after {sleep_between_retries}s...")
                await asyncio.sleep(sleep_between_retries)
                continue
            else:
                return None
                
        except Exception as e:
            logger.error(f"[{task_id}] Download exception on attempt {attempt + 1}: {e}")
            if attempt < max_attempts - 1:
                from backend.video_redirector.utils.pyrogram_acc_manager import rotate_proxy_ip_immediate
                logger.warning(f"[{task_id}] Triggering IP rotation due to repeated YouTube failures")
                await rotate_proxy_ip_immediate("YouTube download failures")
                await asyncio.sleep(10)
                continue
            else:
                return None
        
        # If we get here, _try_youtube_download returned None (only on attempt 3)
        logger.warning(f"[{task_id}] Download failed on attempt {attempt + 1}")
        return None  # No more attempts after attempt 3

async def _try_youtube_download(video_url: str, task_id: str, attempt_num: int):
    """Single attempt to download YouTube video with improved headers and original audio preference"""
    
    # Get the best format ID and copy capability
    format_result = await get_best_format_id(video_url, "1080p", task_id)
    
    if not format_result:
        logger.error(f"[{task_id}] No suitable format found for video (attempt {attempt_num})")
        return None
    
    format_selector, can_copy = format_result
    
    # Download the video
    output_path = os.path.join(DOWNLOAD_DIR, f"{task_id}.mp4")
    
    if can_copy:
        # Fast path: copy streams (no re-encoding)
        postprocessor_args = "ffmpeg:-c:v copy -c:a copy -avoid_negative_ts make_zero -movflags +faststart"
        logger.info(f"[{task_id}] Using FAST COPY mode (attempt {attempt_num})")
    else:
        # Slow path: re-encode for compatibility
        postprocessor_args = "ffmpeg:-c:v libx264 -preset fast -crf 23 -c:a aac -b:a 128k -avoid_negative_ts make_zero -movflags +faststart"
        logger.info(f"[{task_id}] Using RE-ENCODE mode (attempt {attempt_num})")
    
    # Build yt-dlp command with improved headers and user-agent
    # Note: Removed --audio-lang since we handle audio selection in format_selector
    cmd = [
        "yt-dlp",
        "-f", format_selector,
        "-o", output_path,
        "--no-playlist",
        "--no-warnings", 
        "--merge-output-format", "mp4",
        "--postprocessor-args", postprocessor_args,
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "--add-header", "Accept-Language:en-US,en;q=0.9",
        "--add-header", "Accept-Encoding:gzip, deflate",
        "--add-header", "Accept:text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "--add-header", "Connection:keep-alive",
        "--add-header", "Upgrade-Insecure-Requests:1",
        video_url
    ]
    
    logger.info(f"[{task_id}] Downloading with format: {format_selector} (attempt {attempt_num})")
    
    # Run yt-dlp with timeout
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)  # 15 minutes timeout
    
    if result.returncode != 0:
        stderr = result.stderr
        logger.error(f"[{task_id}] yt-dlp failed (attempt {attempt_num}): {stderr}")

        if attempt_num != 3:
            raise ConnectionError(f"YouTube retry: {stderr}")
        else:
            logger.error(f"[{task_id}] 3 tries failed (attempt {attempt_num})")
            return None
    
    # Check if file was created and has content
    if not os.path.exists(output_path):
        logger.error(f"[{task_id}] Output file not created (attempt {attempt_num})")
        raise Exception("Output file not created")
    
    file_size = os.path.getsize(output_path)
    if file_size == 0:
        logger.error(f"[{task_id}] Downloaded file is empty (attempt {attempt_num})")
        os.remove(output_path)
        raise Exception("Downloaded file is empty")
    
    logger.info(f"[{task_id}] Successfully downloaded: {output_path} ({file_size / (1024*1024):.1f}MB) (attempt {attempt_num})")
    
    # Verify the actual quality of the downloaded video
    actual_quality = await verify_video_quality(output_path, task_id)
    if actual_quality:
        logger.info(f"[{task_id}] Actual downloaded quality: {actual_quality}")
    
    return (output_path, actual_quality or "unknown")

async def handle_youtube_download_task(task_id: str, video_url: str, tmdb_id: int, lang: str, dub: str, video_title: str, video_poster: str):
    """Handle YouTube video download task - follows same interface as HDRezka executor"""
    redis = RedisClient.get_client()
    
    # Remove from user's active downloads set when done (success or error)
    tg_user_id = None
    output_path = None
    
    try:
        # Set downloading status and ensure it's visible for polling
        await redis.set(f"download:{task_id}:status", "downloading", ex=3600)
        logger.info(f"[{task_id}] ✅ Status set to 'downloading' at {datetime.now().isoformat()}")
        
        # Download the video
        download_result = await download_youtube_video(video_url, task_id)
        if not download_result:
            raise Exception("Failed to download YouTube video")
        
        output_path, selected_quality = download_result

        await redis.set(f"download:{task_id}:status", "uploading", ex=3600)
        logger.info(f"[{task_id}] ✅ Status set to 'uploading' at {datetime.now().isoformat()}")
         
        # Upload to Telegram using existing infrastructure
        upload_result: Optional[dict] = None
        async for db in get_db():
            upload_result = await check_size_upload_large_file(output_path, task_id, db)
            break  # Only need one session

        if not upload_result:
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
        logger.error(f"[{task_id}] 🔁 RETRYABLE_EXCEPTION at {datetime.now().isoformat()}: {type(e).__name__}: {e}")
        raise RetryableDownloadError(f"Temporary issue during YouTube download: {e}")
    except Exception as e:
        logger.error(f"[{task_id}] ❌ NON-RETRYABLE_EXCEPTION at {datetime.now().isoformat()}: {type(e).__name__}: {e}")
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
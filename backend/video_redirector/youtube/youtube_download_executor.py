import asyncio
import json
import logging
import os
import subprocess
import multiprocessing as mp
import psutil
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from backend.video_redirector.db.models import DownloadedFile, DownloadedFilePart
from backend.video_redirector.db.session import get_db
from backend.video_redirector.db.crud_downloads import get_file_id
from backend.video_redirector.utils.upload_video_to_tg import check_size_upload_large_file
from backend.video_redirector.utils.notify_admin import notify_admin
from backend.video_redirector.utils.redis_client import RedisClient
from backend.video_redirector.config import REDIS_HOST, REDIS_PORT

# Set multiprocessing start method for better compatibility
if __name__ == "__main__":
    mp.set_start_method('spawn', force=True)

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

class ResourceMonitor:
    """Simple resource monitoring for download analysis"""
    
    def __init__(self, task_id: str):
        self.task_id = task_id
        self.start_time = None
        self.monitoring_data = []
        self.process = None
        
    def start_monitoring(self):
        """Start monitoring resources"""
        self.start_time = time.time()
        self.monitoring_data = []
        logger.info(f"[{self.task_id}] 📊 Resource monitoring started")
        
    def capture_snapshot(self, stage: str):
        """Capture current resource usage snapshot"""
        try:
            # Get system-wide metrics
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # Get process-specific metrics if available
            process_metrics = {}
            if self.process and self.process.is_alive():
                try:
                    proc = psutil.Process(self.process.pid)
                    process_metrics = {
                        'cpu_percent': proc.cpu_percent(),
                        'memory_mb': proc.memory_info().rss / (1024 * 1024),
                        'num_threads': proc.num_threads(),
                        'io_counters': proc.io_counters()._asdict() if proc.io_counters() else None
                    }
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            snapshot = {
                'timestamp': time.time(),
                'stage': stage,
                'elapsed_seconds': time.time() - self.start_time if self.start_time else 0,
                'system': {
                    'cpu_percent': cpu_percent,
                    'memory_percent': memory.percent,
                    'memory_available_gb': memory.available / (1024**3),
                    'memory_used_gb': memory.used / (1024**3),
                    'disk_percent': disk.percent,
                    'disk_free_gb': disk.free / (1024**3)
                },
                'process': process_metrics
            }
            
            self.monitoring_data.append(snapshot)
            
            # Log key metrics
            logger.info(f"[{self.task_id}] 📊 {stage}: CPU={cpu_percent:.1f}% | "
                       f"RAM={memory.percent:.1f}% ({memory.used/(1024**3):.1f}GB) | "
                       f"Disk={disk.percent:.1f}% ({disk.free/(1024**3):.1f}GB free)")
            
            if process_metrics:
                logger.info(f"[{self.task_id}] 📊 Process: CPU={process_metrics.get('cpu_percent', 0):.1f}% | "
                           f"RAM={process_metrics.get('memory_mb', 0):.1f}MB | "
                           f"Threads={process_metrics.get('num_threads', 0)}")
            
        except Exception as e:
            logger.warning(f"[{self.task_id}] Failed to capture resource snapshot: {e}")
    
    def set_process(self, process: mp.Process):
        """Set the process to monitor"""
        self.process = process
    
    def get_summary(self) -> Dict[str, Any]:
        """Get monitoring summary"""
        if not self.monitoring_data:
            return {}
        
        # Calculate averages and peaks
        cpu_values = [s['system']['cpu_percent'] for s in self.monitoring_data]
        memory_values = [s['system']['memory_percent'] for s in self.monitoring_data]
        
        summary = {
            'total_duration_seconds': time.time() - self.start_time if self.start_time else 0,
            'snapshots_count': len(self.monitoring_data),
            'system': {
                'cpu_avg': sum(cpu_values) / len(cpu_values),
                'cpu_max': max(cpu_values),
                'memory_avg': sum(memory_values) / len(memory_values),
                'memory_max': max(memory_values),
                'final_disk_free_gb': self.monitoring_data[-1]['system']['disk_free_gb']
            },
            'stages': [s['stage'] for s in self.monitoring_data]
        }
        
        # Add process metrics if available
        process_cpu_values = [s['process'].get('cpu_percent', 0) for s in self.monitoring_data if s['process']]
        process_memory_values = [s['process'].get('memory_mb', 0) for s in self.monitoring_data if s['process']]
        
        if process_cpu_values:
            summary['process'] = {
                'cpu_avg': sum(process_cpu_values) / len(process_cpu_values),
                'cpu_max': max(process_cpu_values),
                'memory_avg': sum(process_memory_values) / len(process_memory_values),
                'memory_max': max(process_memory_values)
            }
        
        return summary
    
    def log_summary(self):
        """Log monitoring summary"""
        summary = self.get_summary()
        if not summary:
            return
        
        logger.info(f"[{self.task_id}] 📊 RESOURCE MONITORING SUMMARY:")
        logger.info(f"[{self.task_id}] 📊 Duration: {summary['total_duration_seconds']:.1f}s | Snapshots: {summary['snapshots_count']}")
        logger.info(f"[{self.task_id}] 📊 System CPU: avg={summary['system']['cpu_avg']:.1f}% | max={summary['system']['cpu_max']:.1f}%")
        logger.info(f"[{self.task_id}] 📊 System RAM: avg={summary['system']['memory_avg']:.1f}% | max={summary['system']['memory_max']:.1f}%")
        logger.info(f"[{self.task_id}] 📊 Final disk free: {summary['system']['final_disk_free_gb']:.1f}GB")
        
        if 'process' in summary:
            logger.info(f"[{self.task_id}] 📊 Process CPU: avg={summary['process']['cpu_avg']:.1f}% | max={summary['process']['cpu_max']:.1f}%")
            logger.info(f"[{self.task_id}] 📊 Process RAM: avg={summary['process']['memory_avg']:.1f}MB | max={summary['process']['memory_max']:.1f}MB")
        
        # Log all stages for timeline analysis
        logger.info(f"[{self.task_id}] 📊 Stages: {' -> '.join(summary['stages'])}")

def cleanup_process(process: mp.Process, task_id: str, timeout: int = 5):
    """Helper function to safely clean up a process"""
    if process and process.is_alive():
        logger.warning(f"[{task_id}] Terminating download process (PID: {process.pid})")
        process.terminate()
        process.join(timeout=timeout)
        if process.is_alive():
            logger.warning(f"[{task_id}] Force killing download process (PID: {process.pid})")
            process.kill()
            process.join(timeout=timeout)
            if process.is_alive():
                logger.error(f"[{task_id}] Failed to kill download process (PID: {process.pid})")
            else:
                logger.info(f"[{task_id}] Successfully killed download process (PID: {process.pid})")
        else:
            logger.info(f"[{task_id}] Successfully terminated download process (PID: {process.pid})")

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

    # Debug what formats are available (can be disabled for less verbose logs)
    # await debug_available_formats(video_url, task_id)

    # Strategy 1: Try JSON-based format detection (most reliable)
    try:
        #logger.debug(f"[{task_id}] Getting video formats using JSON method...")
        
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
                    #logger.debug(f"[{task_id}] Found {len(formats)} formats via JSON method")
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
        #logger.debug(f"[{task_id}] Fallback to text parsing method...")
        
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
                "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "--add-header", "Accept-Language:en-US,en;q=0.9",
                "--add-header", "Accept-Encoding:gzip, deflate",
                video_url
            ]
            
            test_result = subprocess.run(test_cmd, capture_output=True, timeout=30)
            
            if test_result.returncode == 0:
                #logger.debug(f"[{task_id}] Using fallback format: {format_selector}")
                return (format_selector, can_copy)
        
        except Exception as e:
            logger.debug(f"[{task_id}] Format {format_selector} test failed: {e}")
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
    #logger.debug(f"[{task_id}] 🔍 JSON Debug: Analyzing {len(formats)} total formats")
    
    # audio_format_debug = []
    
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
        # if vcodec == 'none' and acodec != 'none':
        #     # Check possible original indicators
        #     original_checks = {
        #         'lang_pref_10': language_preference == 10,
        #         'lang_pref_high': language_preference > 5,
        #         'lang_in_original_list': language in ['original', 'default', 'primary'],
        #     }
        #
        #     audio_format_debug.append({
        #         'id': format_id,
        #         'ext': ext,
        #         'acodec': acodec,
        #         'language': language,
        #         'language_preference': language_preference,
        #         'original_checks': original_checks,
        #         'raw_format': str(fmt)[:200] + "..." if len(str(fmt)) > 200 else str(fmt)
        #     })
        
        if not format_id:
            continue
        
        # Audio-only format
        if vcodec == 'none' and acodec != 'none':
            # Enhanced original audio detection
            is_original = (
                language_preference == 10 or
                language in ['original', 'default', 'primary'] or
                'original' in str(fmt).lower() # Check if 'original' appears anywhere in format data
            )
            
            # Debug: Log each audio format as it's being processed
            #logger.debug(f"[{task_id}] 🔍 Processing audio format: {format_id} - Lang: {language} - Pref: {language_preference} - Original: {is_original}")
            
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
            # Enhanced original audio detection for combined formats
            is_original = (
                language_preference == 10 or  # yt-dlp's primary indicator for original
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
                'is_original': is_original
            })

    # Log summary of original formats found
    # original_audio_found = [fmt for fmt in audio_format_debug if any(fmt['original_checks'].values())]
    # logger.info(f"[{task_id}] 🔍 JSON Debug: Found {len(original_audio_found)} original audio formats out of {len(audio_format_debug)} total")
    
    # logger.info(f"[{task_id}] Format analysis: {len(combined_formats)} combined, {len(video_only_formats)} video-only, {len(audio_only_formats)} audio-only")
    
    # Log summary of original audio formats in final selection
    # original_audio_in_selection = [fmt for fmt in audio_only_formats if fmt.get('is_original', False)]
    # #logger.debug(f"[{task_id}] 🔍 Original audio in final selection: {len(original_audio_in_selection)} formats")
    # for fmt in original_audio_in_selection:
    #     #logger.debug(f"[{task_id}] 🔍   Original: {fmt['id']} ({fmt['ext']}) - Lang: {fmt['language']}, Pref: {fmt['language_preference']}")
    
    # Debug: Log ALL audio formats in the list
    # #logger.debug(f"[{task_id}] 🔍 ALL audio formats in audio_only_formats list:")
    # for i, fmt in enumerate(audio_only_formats):
    #     #logger.debug(f"[{task_id}] 🔍   {i+1}. {fmt['id']}: {fmt['ext']} - Original: {fmt.get('is_original', False)} - Lang: {fmt.get('language', 'unknown')} - Pref: {fmt.get('language_preference', -1)}")
    
    # Strategy 1: Try good quality combined formats with original audio first
    if combined_formats:
        # Sort by: original audio first, then height (descending), then prefer MP4
        combined_formats.sort(key=lambda x: (not x.get('is_original', False), x['height'], x['ext'] == 'mp4'), reverse=True)
        
        # original audio + 1080p+
        for fmt in combined_formats:
            if fmt['height'] >= 1080 and fmt.get('is_original', False):  # Accept 1080p+ combined formats + only original audio
                can_copy = fmt['ext'] == 'mp4'
                is_original = fmt.get('is_original', False)
                #logger.debug(f"[{task_id}] Selected combined format: {fmt['id']} ({fmt['width']}x{fmt['height']} {fmt['ext']}) - Original: {is_original} - Copy: {can_copy}")
                return (fmt['id'], can_copy)
    
    # Strategy 2: Merge video-only + original audio-only
    if video_only_formats and audio_only_formats:
        # Sort video formats: prefer MP4, then by height (descending)
        video_only_formats.sort(key=lambda x: (x['height'], x['ext'] == 'mp4'), reverse=True)

        def audio_sort_key(fmt):
            is_orig = fmt.get('is_original', False)
            lang_pref = fmt.get('language_preference', -999)
            is_m4a = fmt['ext'] in ['m4a', 'mp4']
            abr = fmt.get('abr', 0)
            
            # Debug: Log the sort key for each format
            #logger.debug(f"[{task_id}] 🔍 Sort key for {fmt['id']}: is_orig={is_orig}, lang_pref={lang_pref}, is_m4a={is_m4a}, abr={abr}")
            
            return (is_orig, lang_pref, is_m4a, abr)
        
        audio_only_formats.sort(key=audio_sort_key, reverse=True)

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
        #logger.debug(f"[{task_id}] Selected merge format: {merge_format}")
        #logger.debug(f"[{task_id}]   Video: {best_video['id']} ({best_video['width']}x{best_video['height']} {best_video['ext']})")
        #logger.debug(f"[{task_id}]   Audio: {best_audio['id']} ({best_audio['ext']}) - Original: {is_original} - Lang: {best_audio.get('language', 'unknown')}")
        #logger.debug(f"[{task_id}]   Can copy: {can_copy}")
        
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
                #logger.debug(f"[{task_id}]   {format_id}: {width}x{height} ({ext}) - COMBINED - Original: {is_original}")
            except ValueError:
                continue
    
    # Strategy 1: Try good quality combined formats with original audio first
    if combined_formats:
        # Sort combined formats: original audio first, then prefer MP4, then by height (descending)
        combined_formats.sort(key=lambda x: (not x.get('is_original', False), x['height'], x['ext'] == 'mp4'), reverse=True)
        
        #logger.debug(f"[{task_id}] Available combined (video+audio) formats:")
        # for fmt in combined_formats[:3]:
            #logger.debug(f"[{task_id}]   {fmt['id']}: {fmt['width']}x{fmt['height']} ({fmt['ext']}) - Original: {fmt.get('is_original', False)}")
        
        # Find good quality combined format with original audio
        for fmt in combined_formats:
            if fmt['height'] >= 1080 and fmt.get('is_original', False):  # Accept 1080+ combined formats + only original audio
                can_copy = fmt['ext'] == 'mp4'
                is_original = fmt.get('is_original', False)
                #logger.debug(f"[{task_id}] Selected COMBINED format: {fmt['id']} ({fmt['width']}x{fmt['height']} {fmt['ext']}) - Original: {is_original} - Can copy: {can_copy}")
                return (fmt['id'], can_copy)
    
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
        
        #logger.debug(f"[{task_id}] Available video-only formats:")
        # for fmt in video_only_formats[:3]:
            #logger.debug(f"[{task_id}]   {fmt['id']}: {fmt['width']}x{fmt['height']} ({fmt['ext']})")
        
        #logger.debug(f"[{task_id}] Available audio-only formats:")
        # for fmt in audio_only_formats[:5]:
            #logger.debug(f"[{task_id}]   {fmt['id']}: ({fmt['ext']}) - Original: {fmt.get('is_original', False)}")
        
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
        #logger.debug(f"[{task_id}] Selected MERGE format: {merge_format}")
        #logger.debug(f"[{task_id}]   Video: {best_video['id']} ({best_video['width']}x{best_video['height']} {best_video['ext']})")
        #logger.debug(f"[{task_id}]   Audio: {best_audio['id']} ({best_audio['ext']}) - Original: {is_original}")
        #logger.debug(f"[{task_id}]   Can copy: {can_copy}")
        
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
        
        #logger.debug(f"[{task_id}] Video resolution: {width}x{height} -> {quality}")
        return quality
        
    except Exception as e:
        logger.error(f"[{task_id}] Error verifying video quality: {e}")
        return None

async def handle_youtube_download_task_with_retries(task_id: str, video_url: str, tmdb_id: int, lang: str, dub: str, video_title: str, video_poster: str):
    """Handle YouTube video download task with simple retry strategy and IP rotation - retries on any error until max attempts"""
    
    max_attempts = 3
    sleep_between_retries = 5  # seconds

    for attempt in range(max_attempts):
        logger.info(f"[{task_id}] 🚀 Download attempt {attempt + 1}/{max_attempts}")

        try:
            # Call the main download handler
            await handle_youtube_download_task(task_id, video_url, tmdb_id, lang, dub, video_title, video_poster)
            logger.info(f"[{task_id}] ✅ Download successful on attempt {attempt + 1}")
            return  # Success - exit the retry loop

        except Exception as e:
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
                raise

    # This should never be reached, but just in case
    logger.error(f"[{task_id}] All download attempts failed")
    raise Exception("All download attempts failed")

async def handle_youtube_download_task(task_id: str, video_url: str, tmdb_id: int, lang: str, dub: str, video_title: str, video_poster: str):
    """
    Handle YouTube video download task with process isolation.
    
    NOTE: This function does NOT include retry logic. Use handle_youtube_download_task_with_retries()
    for automatic retries and IP rotation.
    """
    redis = RedisClient.get_client()
    
    # Initialize resource monitoring
    monitor = ResourceMonitor(task_id)
    monitor.start_monitoring()
    monitor.capture_snapshot("download_start")
    
    # Remove from user's active downloads set when done (success or error)
    tg_user_id = None
    output_path = None
    process = None
    
    try:
        # Set initial status (this will be updated by the worker process)
        await redis.set(f"download:{task_id}:status", "downloading", ex=3600)
        logger.info(f"[{task_id}] ✅ Status set to 'downloading' at {datetime.now().isoformat()}")
        
        monitor.capture_snapshot("status_set")
        
        # Create download process
        result_queue = mp.Queue()
        process = mp.Process(
            target=download_worker_process, 
            args=(video_url, task_id, result_queue)
        )
        
        monitor.set_process(process)
        monitor.capture_snapshot("process_created")
        
        try:
            # Start download process
            process.start()
            monitor.capture_snapshot("process_started")
            
            # Wait for download completion (with timeout)
            try:
                result_type, result_data = result_queue.get(timeout=900)  # 15 minutes timeout
                monitor.capture_snapshot("download_completed")
            except mp.TimeoutError:
                logger.error(f"[{task_id}] Download timeout after 15 minutes")
                monitor.capture_snapshot("download_timeout")
                cleanup_process(process, task_id)
                raise Exception("Download timeout after 15 minutes")
            
            # Handle download result
            if result_type == "success":
                output_path = result_data["output_path"]
                selected_quality = result_data["quality"]
                logger.info(f"[{task_id}] ✅ Download completed: {output_path}")
                
                monitor.capture_snapshot("download_success")
                
                # Continue with upload (this part stays in main process)
                await redis.set(f"download:{task_id}:status", "uploading", ex=3600)
                logger.info(f"[{task_id}] ✅ Status set to 'uploading' at {datetime.now().isoformat()}")
                
                monitor.capture_snapshot("upload_start")
                
                # Upload to Telegram using existing infrastructure
                upload_result: Optional[dict] = None
                async for db in get_db():
                    upload_result = await check_size_upload_large_file(output_path, task_id, db)
                    break  # Only need one session

                if not upload_result:
                    monitor.capture_snapshot("upload_failed")
                    raise Exception("Upload to Telegram failed across all delivery bots.")

                tg_bot_token_file_owner = upload_result["bot_token"]
                parts = upload_result["parts"]
                session_name = upload_result["session_name"]
                
                monitor.capture_snapshot("upload_success")

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
                monitor.capture_snapshot("task_completed")
                
            else:
                error_msg = f"Download failed: {result_data}"
                logger.error(f"[{task_id}] {error_msg}")
                raise Exception(error_msg)
                
        except Exception as e:
            logger.error(f"[{task_id}] ❌ Download process error: {e}")
            monitor.capture_snapshot("process_error")
            raise e
            
    except Exception as e:
        logger.error(f"[{task_id}] ❌ Download failed: {e}")
        monitor.capture_snapshot("task_error")
        await redis.set(f"download:{task_id}:status", "error", ex=3600)
        await redis.set(f"download:{task_id}:error", str(e), ex=3600)
        await notify_admin(f"[Download Task {task_id}] YouTube download failed: {e}")
        raise e
    finally:
        # Log resource monitoring summary
        monitor.log_summary()
        
        # Clean up process
        if process:
            cleanup_process(process, task_id)
        
        # Clean up downloaded file
        if output_path and os.path.exists(output_path):
            try:
                os.remove(output_path)
                logger.debug(f"[{task_id}] Cleaned up downloaded file: {output_path}")
            except Exception as e:
                logger.warning(f"[{task_id}] Failed to clean up file {output_path}: {e}")
        
        # Remove from user's active downloads set
        if tg_user_id is None:
            # Try to get from Redis
            tg_user_id = await redis.get(f"download:{task_id}:user_id")
        if tg_user_id:
            await redis.srem(f"active_downloads:{tg_user_id}", task_id) # type: ignore

def download_worker_process(video_url: str, task_id: str, result_queue: mp.Queue):
    """
    Download worker that runs in a separate process.
    This function handles the heavy download work without blocking the main backend.
    """
    try:
        # Initialize Redis connection for this process
        import asyncio
        import redis.asyncio as redis
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Create a fresh Redis client for this process instead of using the singleton
        async def create_redis_client():
            return redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                decode_responses=True
            )
        
        redis_client = loop.run_until_complete(create_redis_client())
        
        logger.info(f"[{task_id}] 🚀 Download process started (PID: {os.getpid()})")
        
        # Initialize worker process resource monitoring
        worker_monitor = ResourceMonitor(f"{task_id}_worker")
        worker_monitor.start_monitoring()
        worker_monitor.capture_snapshot("worker_started")
        
        # Update status to downloading
        loop.run_until_complete(redis_client.set(f"download:{task_id}:status", "downloading", ex=3600))
        logger.info(f"[{task_id}] ✅ Status set to 'downloading' in worker process")
        
        worker_monitor.capture_snapshot("status_updated")
        
        # Get the best format ID and copy capability
        format_result = loop.run_until_complete(get_best_format_id(video_url, "1080p", task_id))
        
        worker_monitor.capture_snapshot("format_selected")
        
        if not format_result:
            error_msg = "No suitable format found for video"
            worker_monitor.capture_snapshot("format_selection_failed")
            result_queue.put(("error", error_msg))
            return
        
        format_selector, can_copy = format_result
        
        # Download the video
        output_path = os.path.join(DOWNLOAD_DIR, f"{task_id}.mp4")
        
        if can_copy:
            # Fast path: copy streams (no re-encoding)
            postprocessor_args = "ffmpeg:-c:v copy -c:a copy -avoid_negative_ts make_zero -movflags +faststart"
            logger.info(f"[{task_id}] Using FAST COPY mode")
        else:
            # Slow path: re-encode for compatibility
            postprocessor_args = "ffmpeg:-c:v libx264 -preset fast -crf 23 -c:a aac -b:a 128k -avoid_negative_ts make_zero -movflags +faststart"
            logger.info(f"[{task_id}] Using RE-ENCODE mode")
        
        worker_monitor.capture_snapshot("download_prepared")
        
        # Build yt-dlp command with resource optimization
        cmd = [
            "yt-dlp",
            "-f", format_selector,
            "-o", output_path,
            "--no-playlist",
            "--no-warnings", 
            "--merge-output-format", "mp4",
            "--postprocessor-args", postprocessor_args,
            # "--limit-rate", "2M",  # 2MB/s limit
            # "--concurrent-fragments", "1",  # Single fragment
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "--add-header", "Accept-Language:en-US,en;q=0.9",
            "--add-header", "Accept-Encoding:gzip, deflate",
            "--add-header", "Accept:text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "--add-header", "Connection:keep-alive",
            "--add-header", "Upgrade-Insecure-Requests:1",
            video_url
        ]
        
        logger.info(f"[{task_id}] Starting download with format: {format_selector}")
        
        worker_monitor.capture_snapshot("download_started")
        
        # Run yt-dlp with asyncio.subprocess (non-blocking)
        async def run_yt_dlp_async():
            try:
                # Create subprocess with asyncio
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                # Wait for completion with timeout
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=900)
                    return process.returncode, stdout, stderr
                except asyncio.TimeoutError:
                    logger.error(f"[{task_id}] Download timeout after 15 minutes")
                    process.terminate()
                    await process.wait()
                    raise asyncio.TimeoutError("Download timeout after 15 minutes")
                    
            except Exception as e:
                logger.error(f"[{task_id}] asyncio.subprocess error: {e}")
                raise e
        
        returncode, stdout, stderr = loop.run_until_complete(run_yt_dlp_async())
        
        worker_monitor.capture_snapshot("download_finished")
        
        if returncode != 0:
            error_msg = f"yt-dlp failed: {stderr.decode() if stderr else 'Unknown error'}"
            worker_monitor.capture_snapshot("download_failed")
            result_queue.put(("error", error_msg))
            return
        
        # Check if file was created and has content
        if not os.path.exists(output_path):
            error_msg = "Output file not created"
            worker_monitor.capture_snapshot("file_not_created")
            result_queue.put(("error", error_msg))
            return
        
        file_size = os.path.getsize(output_path)
        if file_size == 0:
            error_msg = "Downloaded file is empty"
            os.remove(output_path)
            worker_monitor.capture_snapshot("file_empty")
            result_queue.put(("error", error_msg))
            return
        
        logger.info(f"[{task_id}] Successfully downloaded: {output_path} ({file_size / (1024*1024):.1f}MB)")
        
        worker_monitor.capture_snapshot("file_verified")
        
        # Verify the actual quality of the downloaded video
        actual_quality = loop.run_until_complete(verify_video_quality(output_path, task_id))
        if actual_quality:
            logger.info(f"[{task_id}] Actual downloaded quality: {actual_quality}")
        
        worker_monitor.capture_snapshot("quality_verified")
        
        # Send success result back to main process
        result_queue.put(("success", {
            "output_path": output_path,
            "file_size": file_size,
            "quality": actual_quality or "unknown"
        }))
        
        logger.info(f"[{task_id}] ✅ Download process completed successfully")
        worker_monitor.capture_snapshot("worker_completed")
        
    except asyncio.TimeoutError:
        error_msg = "Download timeout after 15 minutes"
        worker_monitor.capture_snapshot("timeout_error")
        result_queue.put(("error", error_msg))
        
    except Exception as e:
        error_msg = f"Download process error: {str(e)}"
        worker_monitor.capture_snapshot("general_error")
        result_queue.put(("error", error_msg))
        
    finally:
        # Log worker process resource monitoring summary
        worker_monitor.log_summary()
        
        # Clean up Redis connection
        try:
            if 'redis_client' in locals():
                loop.run_until_complete(redis_client.close())
        except Exception as e:
            logger.warning(f"[{task_id}] Error closing Redis connection: {e}")
        
        loop.close()

async def get_download_progress(task_id: str) -> Optional[Dict[str, Any]]:
    """
    Get download progress from Redis.
    Returns progress data if available, None otherwise.
    """
    try:
        redis = RedisClient.get_client()
        progress_data = await redis.get(f"download:{task_id}:progress")
        
        if progress_data:
            return json.loads(progress_data)
        else:
            return None
            
    except Exception as e:
        logger.warning(f"[{task_id}] Failed to get progress: {e}")
        return None
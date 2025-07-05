import os
import asyncio
import re
import logging
import subprocess
from typing import Dict, Optional, Tuple
import certifi
import aiohttp
import ssl
import json
import time

from backend.video_redirector.config import MAX_CONCURRENT_MERGES_OF_TS_INTO_MP4
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

logger = logging.getLogger(__name__)
status_tracker: Dict[str, Dict] = {}  # Example: {task_id: {"total": 0, "done": 0, "progress": 0.0}}

semaphore = asyncio.Semaphore(MAX_CONCURRENT_MERGES_OF_TS_INTO_MP4)

class MergeError(Exception):
    """Custom exception for merge failures with detailed error information"""
    def __init__(self, message: str, ffmpeg_output: str = "", returncode: int = 1):
        self.message = message
        self.ffmpeg_output = ffmpeg_output
        self.returncode = returncode
        super().__init__(self.message)

async def log_video_metadata(file_path: str, task_id: str, description: str):
    """
    Log detailed video metadata for analysis
    """
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            file_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        if result.returncode == 0:
            metadata = json.loads(result.stdout)
            
            logger.info(f"🔍 [{task_id}] {description} metadata:")
            
            # Log format information
            if "format" in metadata:
                format_info = metadata["format"]
                logger.info(f"   Format: {format_info.get('format_name', 'Unknown')}")
                logger.info(f"   Duration: {format_info.get('duration', 'Unknown')} seconds")
                logger.info(f"   Bitrate: {format_info.get('bit_rate', 'Unknown')} bps")
                logger.info(f"   Size: {format_info.get('size', 'Unknown')} bytes")
            
            # Log stream information
            if "streams" in metadata:
                for i, stream in enumerate(metadata["streams"]):
                    codec_type = stream.get("codec_type", "unknown")
                    logger.info(f"   Stream {i} ({codec_type}):")
                    logger.info(f"     Codec: {stream.get('codec_name', 'Unknown')}")
                    
                    if codec_type == "video":
                        logger.info(f"     Resolution: {stream.get('width', 'Unknown')}x{stream.get('height', 'Unknown')}")
                        logger.info(f"     Aspect Ratio: {stream.get('display_aspect_ratio', 'Unknown')}")
                        logger.info(f"     Pixel Format: {stream.get('pix_fmt', 'Unknown')}")
                        logger.info(f"     Frame Rate: {stream.get('r_frame_rate', 'Unknown')}")
                        logger.info(f"     Bitrate: {stream.get('bit_rate', 'Unknown')} bps")
                        
                        # Check for SAR/DAR issues
                        sar = stream.get('sample_aspect_ratio', '1:1')
                        dar = stream.get('display_aspect_ratio', 'Unknown')
                        logger.info(f"     SAR (Sample Aspect Ratio): {sar}")
                        logger.info(f"     DAR (Display Aspect Ratio): {dar}")
                        
                        if sar != '1:1':
                            logger.warning(f"   ⚠️ [{task_id}] Non-square pixels detected (SAR: {sar}) - this may cause aspect ratio issues on mobile!")
                    
                    elif codec_type == "audio":
                        logger.info(f"     Sample Rate: {stream.get('sample_rate', 'Unknown')} Hz")
                        logger.info(f"     Channels: {stream.get('channels', 'Unknown')}")
                        logger.info(f"     Bitrate: {stream.get('bit_rate', 'Unknown')} bps")
        
        else:
            logger.error(f"❌ [{task_id}] Failed to get metadata for {description}: {result.stderr}")
    
    except Exception as e:
        logger.error(f"❌ [{task_id}] Error logging metadata for {description}: {e}")

async def analyze_first_ts_segment(m3u8_url: str, headers: Dict[str, str], task_id: str) -> Optional[Dict]:
    """
    Download and analyze the first TS segment to understand source quality
    Returns metadata dict if successful, None otherwise
    """
    try:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        async with aiohttp.ClientSession() as session:
            async with session.get(m3u8_url, headers=headers, ssl=ssl_context) as resp:
                if resp.status != 200:
                    logger.error(f"❌ [{task_id}] Failed to fetch m3u8: HTTP {resp.status}")
                    return None
                m3u8_text = await resp.text()
        
        # Find first .ts segment
        first_ts_url = None
        for line in m3u8_text.splitlines():
            line = line.strip()
            if line.endswith('.ts'):
                if line.startswith('http'):
                    first_ts_url = line
                else:
                    # Relative URL - construct absolute URL
                    base_url = '/'.join(m3u8_url.split('/')[:-1]) + '/'
                    first_ts_url = base_url + line
                break
        
        if first_ts_url:
            logger.info(f"📦 [{task_id}] Analyzing first TS segment: {first_ts_url}")
            
            # Download first segment
            segment_path = os.path.join(DOWNLOAD_DIR, f"{task_id}_first_segment.ts")
            async with aiohttp.ClientSession() as session:
                async with session.get(first_ts_url, headers=headers, ssl=ssl_context) as resp:
                    if resp.status == 200:
                        with open(segment_path, 'wb') as f:
                            f.write(await resp.read())
                        
                        # Analyze the segment
                        await log_video_metadata(segment_path, task_id, "First TS segment")
                        
                        # Get metadata for return
                        try:
                            cmd = [
                                "ffprobe",
                                "-v", "quiet",
                                "-print_format", "json",
                                "-show_streams",
                                segment_path
                            ]
                            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                            metadata = json.loads(result.stdout)
                            
                            # Clean up
                            os.remove(segment_path)
                            
                            return metadata
                        except Exception as e:
                            logger.error(f"❌ [{task_id}] Error getting segment metadata: {e}")
                            if os.path.exists(segment_path):
                                os.remove(segment_path)
                            return None
                    else:
                        logger.error(f"❌ [{task_id}] Failed to download first TS segment: HTTP {resp.status}")
                        return None
        else:
            logger.warning(f"⚠️ [{task_id}] No TS segments found in playlist for analysis")
            return None
    
    except Exception as e:
        logger.error(f"❌ [{task_id}] Error analyzing first TS segment: {e}")
        return None

def should_fix_aspect_ratio(metadata: Optional[Dict]) -> Tuple[bool, str]:
    """
    Determine if aspect ratio fixing is needed based on metadata
    Returns (should_fix, reason)
    """
    if not metadata or "streams" not in metadata:
        return False, "No metadata available"
    
    for stream in metadata["streams"]:
        if stream.get("codec_type") == "video":
            sar = stream.get('sample_aspect_ratio', '1:1')
            if sar != '1:1':
                return True, f"Non-square pixels detected (SAR: {sar})"
    
    return False, "Square pixels (SAR: 1:1)"

async def merge_ts_to_mp4_with_fallback(task_id: str, m3u8_url: str, headers: Dict[str, str], 
                                      segment_metadata: Optional[Dict] = None) -> str | None:
    """
    Merge TS to MP4 with fallback strategies - optimized for performance
    """
    output_file = os.path.join(DOWNLOAD_DIR, f"{task_id}.mp4")
    
    # Strategy 1: Direct copy (fastest)
    try:
        logger.info(f"🔄 [{task_id}] Attempting direct copy merge...")
        result = await merge_with_direct_copy(task_id, m3u8_url, headers, output_file)
        if result:
            return result
    except MergeError as e:
        logger.warning(f"⚠️ [{task_id}] Direct copy failed: {e.message}")
        logger.debug(f"FFmpeg output: {e.ffmpeg_output}")
    
    # Strategy 2: SAR fix with bitstream filter (fast, no re-encoding)
    try:
        logger.info(f"🔄 [{task_id}] Attempting SAR fix with bitstream filter...")
        should_fix, reason = should_fix_aspect_ratio(segment_metadata)
        if should_fix:
            logger.info(f"🎯 [{task_id}] Fixing SAR without re-encoding: {reason}")
            result = await merge_with_sar_fix(task_id, m3u8_url, headers, output_file)
            if result:
                return result
        else:
            logger.info(f"ℹ️ [{task_id}] No SAR fix needed: {reason}")
    except MergeError as e:
        logger.warning(f"⚠️ [{task_id}] SAR fix failed: {e.message}")
        logger.debug(f"FFmpeg output: {e.ffmpeg_output}")
    
    # Strategy 3: Container-level aspect ratio fix (fast, no re-encoding)
    try:
        logger.info(f"🔄 [{task_id}] Attempting container-level aspect ratio fix...")
        result = await merge_with_container_aspect_fix(task_id, m3u8_url, headers, output_file)
        if result:
            return result
    except MergeError as e:
        logger.warning(f"⚠️ [{task_id}] Container aspect fix failed: {e.message}")
        logger.debug(f"FFmpeg output: {e.ffmpeg_output}")
    
    # Strategy 4: Last resort - re-encode only if absolutely necessary
    try:
        logger.warning(f"⚠️ [{task_id}] All fast methods failed, attempting re-encode as last resort...")
        logger.warning(f"🐌 [{task_id}] This will be slow on your VPS - consider if source is compatible")
        result = await merge_with_aspect_fix(task_id, m3u8_url, headers, output_file)
        if result:
            return result
    except MergeError as e:
        logger.error(f"❌ [{task_id}] Re-encode failed: {e.message}")
        logger.error(f"FFmpeg output: {e.ffmpeg_output}")
    
    # All strategies failed
    logger.error(f"❌ [{task_id}] All merge strategies failed")
    return None

async def merge_with_direct_copy(task_id: str, m3u8_url: str, headers: Dict[str, str], 
                               output_file: str) -> str | None:
    """
    Direct copy merge - fastest but may have compatibility issues
    """
    ffmpeg_header_str = ''.join(f"{k}: {v}\r\n" for k, v in headers.items())
    
    cmd = [
        "ffmpeg",
        "-loglevel", "error",
        "-headers", ffmpeg_header_str,
        "-protocol_whitelist", "file,http,https,tcp,tls",
        "-i", m3u8_url,
        "-c", "copy",
        "-bsf:a", "aac_adtstoasc",
        "-movflags", "+faststart",
        "-y",
        output_file
    ]
    
    return await run_ffmpeg_command(cmd, task_id, "direct copy")

async def merge_with_sar_fix(task_id: str, m3u8_url: str, headers: Dict[str, str], 
                            output_file: str) -> str | None:
    """
    Merge with SAR fix using bitstream filter - fast, no re-encoding
    """
    ffmpeg_header_str = ''.join(f"{k}: {v}\r\n" for k, v in headers.items())
    
    cmd = [
        "ffmpeg",
        "-loglevel", "error",
        "-headers", ffmpeg_header_str,
        "-protocol_whitelist", "file,http,https,tcp,tls",
        "-i", m3u8_url,
        "-c", "copy",  # No re-encoding
        "-bsf:v", "h264_metadata=sample_aspect_ratio=1:1",  # Fix SAR without re-encoding
        "-bsf:a", "aac_adtstoasc",
        "-movflags", "+faststart",
        "-y",
        output_file
    ]
    
    return await run_ffmpeg_command(cmd, task_id, "SAR fix (no re-encoding)")

async def merge_with_container_aspect_fix(task_id: str, m3u8_url: str, headers: Dict[str, str], 
                                        output_file: str) -> str | None:
    """
    Merge with container-level aspect ratio fix - fast, no re-encoding
    """
    ffmpeg_header_str = ''.join(f"{k}: {v}\r\n" for k, v in headers.items())
    
    cmd = [
        "ffmpeg",
        "-loglevel", "error",
        "-headers", ffmpeg_header_str,
        "-protocol_whitelist", "file,http,https,tcp,tls",
        "-i", m3u8_url,
        "-c", "copy",  # No re-encoding
        "-aspect", "16:9",  # Force 16:9 aspect ratio at container level
        "-bsf:a", "aac_adtstoasc",
        "-movflags", "+faststart",
        "-y",
        output_file
    ]
    
    return await run_ffmpeg_command(cmd, task_id, "container aspect fix (no re-encoding)")

async def merge_with_aspect_fix(task_id: str, m3u8_url: str, headers: Dict[str, str], 
                              output_file: str) -> str | None:
    """
    Merge with aspect ratio fix - slower but fixes mobile compatibility (RE-ENCODING)
    """
    ffmpeg_header_str = ''.join(f"{k}: {v}\r\n" for k, v in headers.items())
    
    cmd = [
        "ffmpeg",
        "-loglevel", "error",
        "-headers", ffmpeg_header_str,
        "-protocol_whitelist", "file,http,https,tcp,tls",
        "-i", m3u8_url,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-vf", "setsar=1:1",  # Fix aspect ratio by setting SAR to 1:1
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-y",
        output_file
    ]
    
    return await run_ffmpeg_command(cmd, task_id, "aspect fix (RE-ENCODING)")

async def merge_with_safe_reencode(task_id: str, m3u8_url: str, headers: Dict[str, str], 
                                 output_file: str) -> str | None:
    """
    Safe re-encode merge - slowest but most compatible
    """
    ffmpeg_header_str = ''.join(f"{k}: {v}\r\n" for k, v in headers.items())
    
    cmd = [
        "ffmpeg",
        "-loglevel", "error",
        "-headers", ffmpeg_header_str,
        "-protocol_whitelist", "file,http,https,tcp,tls",
        "-i", m3u8_url,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-vf", "setsar=1:1,format=yuv420p",  # Fix aspect ratio and ensure compatible pixel format
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-profile:v", "high",
        "-level", "4.0",
        "-maxrate", "5M",
        "-bufsize", "10M",
        "-y",
        output_file
    ]
    
    return await run_ffmpeg_command(cmd, task_id, "safe re-encode")

async def run_ffmpeg_command(cmd: list, task_id: str, strategy: str) -> str | None:
    """
    Run ffmpeg command with comprehensive error handling and progress tracking
    """
    output_file = cmd[-1]  # Output file is always the last argument
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Track progress
        stderr_output = []
        ts_pattern = re.compile(r"Opening '.*?\.ts'")
        
        start_time = time.time()
        last_progress_log = 0
        
        while True:
            try:
                # Read stderr for progress tracking
                if process.stderr:
                    line = await asyncio.wait_for(process.stderr.readline(), timeout=1.0)
                    if not line:
                        break
                    decoded = line.decode().strip()
                    stderr_output.append(decoded)
                    
                    # Track TS segment progress
                    if ts_pattern.search(decoded):
                        tracker = status_tracker.get(task_id)
                        if tracker:
                            tracker["done"] += 1
                            tracker["progress"] = round((tracker["done"] / tracker["total"]) * 100, 1)
                            
                            # Log progress every 10% or every 30 seconds
                            current_time = time.time()
                            if (tracker["progress"] - last_progress_log >= 10 or 
                                current_time - start_time >= 30):
                                logger.info(f"📊 [{task_id}] {strategy} progress: {tracker['progress']:.1f}% "
                                          f"({tracker['done']}/{tracker['total']} segments)")
                                last_progress_log = tracker["progress"]
                                start_time = current_time
                else:
                    break
                    
            except asyncio.TimeoutError:
                # Check if process is still running
                if process.returncode is not None:
                    break
                continue
        
        # Wait for process to complete
        returncode = await process.wait()
        
        # Capture any remaining output
        if process.stdout:
            stdout_remaining = await process.stdout.read()
            if stdout_remaining:
                logger.debug(f"[{task_id}] FFmpeg stdout: {stdout_remaining.decode()}")
        
        if process.stderr:
            stderr_remaining = await process.stderr.read()
            if stderr_remaining:
                stderr_output.append(stderr_remaining.decode())
        
        full_stderr = '\n'.join(stderr_output)
        
        if returncode == 0:
            if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                logger.info(f"✅ [{task_id}] {strategy} merge complete: {output_file}")
                
                # Log final MP4 metadata for analysis
                await log_video_metadata(output_file, task_id, f"Final MP4 file ({strategy})")
                
                status_tracker.pop(task_id, None)
                return output_file
            else:
                error_msg = f"FFmpeg completed but output file is empty or missing"
                logger.error(f"❌ [{task_id}] {error_msg}")
                raise MergeError(error_msg, full_stderr, returncode)
        else:
            error_msg = f"FFmpeg failed with return code {returncode}"
            logger.error(f"❌ [{task_id}] {error_msg}")
            logger.error(f"FFmpeg stderr: {full_stderr}")
            raise MergeError(error_msg, full_stderr, returncode)
    
    except asyncio.TimeoutError:
        error_msg = f"FFmpeg command timed out after extended period"
        logger.error(f"❌ [{task_id}] {error_msg}")
        raise MergeError(error_msg, "", -1)
    
    except Exception as e:
        error_msg = f"Unexpected error running FFmpeg: {str(e)}"
        logger.error(f"❌ [{task_id}] {error_msg}")
        raise MergeError(error_msg, "", -1)
    
    finally:
        # Clean up partial files on failure
        if os.path.exists(output_file) and returncode != 0:
            try:
                os.remove(output_file)
                logger.info(f"🧹 [{task_id}] Removed partial output file after failure.")
            except Exception as e:
                logger.warning(f"⚠️ [{task_id}] Failed to remove partial file: {e}")

async def merge_ts_to_mp4(task_id: str, m3u8_url: str, headers: Dict[str, str]) -> str | None:
    """
    Main merge function with improved error handling and fallback strategies
    """
    try:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        async with semaphore:  # simple limiter if many tasks run
            async with asyncio.timeout(30):  # Timeout for m3u8 fetch
                async with aiohttp.ClientSession() as session:
                    async with session.get(m3u8_url, headers=headers, ssl=ssl_context) as resp:
                        if resp.status != 200:
                            logger.error(f"❌ [{task_id}] Failed to fetch m3u8: HTTP {resp.status}")
                            return None
                        m3u8_text = await resp.text()
    except asyncio.TimeoutError:
        logger.error(f"❌ [{task_id}] Timeout fetching m3u8 file")
        return None
    except Exception as e:
        logger.error(f"❌ [{task_id}] Failed to fetch m3u8 file: {e}")
        return None

    # Count segments
    segment_count = sum(1 for line in m3u8_text.splitlines() if line.strip().endswith(".ts"))

    if segment_count == 0:
        logger.error(f"❌ [{task_id}] No .ts segments found in playlist")
        return None

    status_tracker[task_id] = {"total": segment_count, "done": 0, "progress": 0.0}
    logger.info(f"📦 [{task_id}] Found {segment_count} segments")

    # Analyze the first TS segment to understand source quality
    segment_metadata = await analyze_first_ts_segment(m3u8_url, headers, task_id)
    
    # Attempt merge with fallback strategies
    try:
        result = await merge_ts_to_mp4_with_fallback(task_id, m3u8_url, headers, segment_metadata)
        return result
    except Exception as e:
        logger.error(f"❌ [{task_id}] All merge strategies failed: {e}")
        return None
    finally:
        # Clean up status tracker
        status_tracker.pop(task_id, None)

def get_task_progress(task_id: str) -> Dict:
    if task_id not in status_tracker:
        return {
            "status": "not_found",
            "message": f"No active download task found with ID: {task_id}",
        }

    return {
        "status": "in_progress",
        "message": "Download task is running.",
        **status_tracker[task_id]
    }

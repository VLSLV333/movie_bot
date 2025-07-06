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
import struct

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
    Merge TS to MP4 with mobile compatibility fixes
    Strategy: MP4Box binary → Python binary manipulation → Ultra-fast FFmpeg
    """
    output_file = os.path.join(DOWNLOAD_DIR, f"{task_id}.mp4")
    temp_output_file = os.path.join(DOWNLOAD_DIR, f"{task_id}_temp.mp4")
    
    # Check if mobile compatibility fixes are needed
    should_fix, reason = should_fix_aspect_ratio(segment_metadata)
    
    # First, always get a direct copy for fast manipulation
    logger.info(f"🚀 [{task_id}] Getting direct copy for fast SAR manipulation...")
    try:
        direct_copy_result = await merge_with_direct_copy(task_id, m3u8_url, headers, temp_output_file)
        if not direct_copy_result:
            logger.error(f"❌ [{task_id}] Could not get direct copy - trying re-encoding instead")
            # Skip to final fallback
            return await merge_with_sar_fix(task_id, m3u8_url, headers, output_file)
    except MergeError as e:
        logger.warning(f"⚠️ [{task_id}] Direct copy failed: {e.message}")
        logger.info(f"🔄 [{task_id}] Skipping to re-encoding fallback...")
        return await merge_with_sar_fix(task_id, m3u8_url, headers, output_file)
    
    # If no SAR issues detected, we're done
    if not should_fix:
        logger.info(f"✅ [{task_id}] No mobile compatibility issues detected: {reason}")
        # Move temp file to final output
        if os.path.exists(temp_output_file):
            os.rename(temp_output_file, output_file)
            return output_file
        else:
            logger.error(f"❌ [{task_id}] Temp file disappeared")
            return None
    
    # SAR issues detected - try to fix them
    logger.info(f"📱 [{task_id}] Mobile compatibility issue detected: {reason}")
    logger.info(f"🎯 [{task_id}] Trying fast SAR fixes...")
    
    # Strategy 1: Pre-compiled MP4Box binary (fastest SAR fix)
    try:
        logger.info(f"🔧 [{task_id}] Attempting MP4Box SAR fix (fastest method)...")
        mp4box_result = await merge_with_mp4box_fix(task_id, temp_output_file, output_file)
        if mp4box_result:
            # Clean up temp file
            if os.path.exists(temp_output_file):
                os.remove(temp_output_file)
            logger.info(f"✅ [{task_id}] MP4Box SAR fix successful!")
            return mp4box_result
        else:
            logger.info(f"⚠️ [{task_id}] MP4Box not available or failed, trying Python binary manipulation...")
    except Exception as e:
        logger.warning(f"⚠️ [{task_id}] MP4Box SAR fix failed: {e}")
    
    # Strategy 2: Python binary MP4 manipulation (fallback)
    # DISABLED: This strategy loads entire file into memory (4GB+ files cause crashes)
    # TODO: Implement streaming binary manipulation for large files
    # try:
    #     logger.info(f"🔧 [{task_id}] Attempting Python binary SAR fix...")
    #     binary_result = await fix_mp4_sar_binary(task_id, temp_output_file, output_file)
    #     if binary_result:
    #         # Clean up temp file
    #         if os.path.exists(temp_output_file):
    #             os.remove(temp_output_file)
    #         logger.info(f"✅ [{task_id}] Python binary SAR fix successful!")
    #         return binary_result
    #     else:
    #         logger.info(f"⚠️ [{task_id}] Python binary manipulation failed, trying ultra-fast re-encoding...")
    # except Exception as e:
    #     logger.warning(f"⚠️ [{task_id}] Python binary SAR fix failed: {e}")
    
    logger.info(f"⚠️ [{task_id}] Python binary SAR fix disabled (prevents crashes with 4GB+ files)")
    logger.info(f"🔄 [{task_id}] Skipping to ultra-fast FFmpeg re-encoding...")
    
    # Strategy 3: Ultra-fast FFmpeg re-encoding (final fallback)
    try:
        logger.info(f"🔄 [{task_id}] Attempting ultra-fast FFmpeg SAR fix (final fallback)...")
        # Clean up temp file first
        if os.path.exists(temp_output_file):
            os.remove(temp_output_file)
        
        result = await merge_with_sar_fix(task_id, m3u8_url, headers, output_file)
        if result:
            logger.info(f"✅ [{task_id}] Ultra-fast FFmpeg SAR fix successful!")
            return result
    except MergeError as e:
        logger.error(f"❌ [{task_id}] Ultra-fast FFmpeg SAR fix failed: {e.message}")
        logger.debug(f"FFmpeg output: {e.ffmpeg_output}")
    
    # All strategies failed
    logger.error(f"❌ [{task_id}] All SAR fix strategies failed")
    
    # Clean up temp file if it exists
    if os.path.exists(temp_output_file):
        try:
            os.remove(temp_output_file)
        except Exception as e:
            logger.warning(f"⚠️ [{task_id}] Could not clean up temp file: {e}")
    
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
    Merge with SAR fix using fast re-encoding - fixes SAR with minimal quality loss
    """
    ffmpeg_header_str = ''.join(f"{k}: {v}\r\n" for k, v in headers.items())
    
    cmd = [
        "ffmpeg",
        "-loglevel", "error",
        "-headers", ffmpeg_header_str,
        "-protocol_whitelist", "file,http,https,tcp,tls",
        "-i", m3u8_url,
        "-c:v", "libx264",  # Fast H.264 encoding
        "-preset", "ultrafast",  # Fastest possible preset
        "-crf", "23",  # Lower quality but much faster
        "-vf", "setsar=1:1",  # Fix SAR
        "-c:a", "copy",  # Copy audio without re-encoding
        "-movflags", "+faststart",
        "-threads", "0",  # Use all CPU cores
        "-y",
        output_file
    ]
    
    return await run_ffmpeg_command(cmd, task_id, "SAR fix (fast re-encoding)")

async def merge_with_mp4box_fix(task_id: str, temp_mp4_file: str, output_file: str) -> str | None:
    """
    Use MP4Box to fix SAR metadata without re-encoding (very fast)
    This is our Strategy 1: fastest possible SAR fix
    """
    try:
        # First, check if MP4Box is available
        check_cmd = ["MP4Box", "-version"]
        check_result = subprocess.run(check_cmd, capture_output=True, text=True, timeout=10)
        
        if check_result.returncode != 0:
            logger.info(f"[{task_id}] MP4Box not available on system")
            return None
        
        logger.info(f"🔧 [{task_id}] MP4Box available, fixing SAR metadata (no re-encoding)...")
        
        # Use MP4Box to fix SAR - try multiple approaches
        commands_to_try = [
            # Approach 1: Set pixel aspect ratio to 1:1
            [
                "MP4Box",
                "-par", "1:1",
                "-out", output_file,
                temp_mp4_file
            ],
            # Approach 2: More explicit SAR fix
            [
                "MP4Box", 
                "-par", "1",
                "-out", output_file,
                temp_mp4_file
            ],
            # Approach 3: Alternative syntax
            [
                "MP4Box",
                "-par", "1:1",
                "-new", output_file,
                temp_mp4_file
            ]
        ]
        
        for i, cmd in enumerate(commands_to_try, 1):
            try:
                logger.info(f"🔧 [{task_id}] MP4Box attempt {i}/{len(commands_to_try)}: {' '.join(cmd[1:4])}")
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                        logger.info(f"✅ [{task_id}] MP4Box SAR fix successful with approach {i}")
                        return output_file
                    else:
                        logger.warning(f"⚠️ [{task_id}] MP4Box approach {i} completed but output file is empty")
                        # Try next approach
                        continue
                else:
                    logger.warning(f"⚠️ [{task_id}] MP4Box approach {i} failed: {result.stderr}")
                    # Try next approach
                    continue
                    
            except subprocess.TimeoutExpired:
                logger.warning(f"⚠️ [{task_id}] MP4Box approach {i} timeout")
                continue
        
        # All approaches failed
        logger.info(f"[{task_id}] All MP4Box approaches failed")
        return None
            
    except Exception as e:
        logger.warning(f"⚠️ [{task_id}] MP4Box error: {e}")
        return None

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
                
                # Validate output for mobile compatibility if this was meant to fix SAR issues
                if "SAR fix" in strategy or "aspect fix" in strategy:
                    # Check if SAR was actually fixed
                    try:
                        cmd = [
                            "ffprobe",
                            "-v", "quiet",
                            "-print_format", "json",
                            "-show_streams",
                            output_file
                        ]
                        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                        if result.returncode == 0:
                            metadata = json.loads(result.stdout)
                            for stream in metadata.get("streams", []):
                                if stream.get("codec_type") == "video":
                                    sar = stream.get('sample_aspect_ratio', '1:1')
                                    if sar != '1:1':
                                        logger.warning(f"⚠️ [{task_id}] {strategy} completed but SAR still {sar} - fix failed")
                                        # For SAR/aspect fixes, fail the strategy if SAR wasn't actually fixed
                                        # This will trigger the next fallback strategy (re-encoding)
                                        error_msg = f"{strategy} succeeded but SAR still {sar}, mobile compatibility not achieved"
                                        logger.error(f"❌ [{task_id}] {error_msg}")
                                        raise MergeError(error_msg, f"SAR validation failed: {sar}", 0)
                                    else:
                                        logger.info(f"✅ [{task_id}] SAR successfully fixed to 1:1")
                                    break
                    except MergeError:
                        # Re-raise MergeError to trigger fallback
                        raise
                    except Exception as e:
                        logger.warning(f"⚠️ [{task_id}] Could not validate output SAR: {e}")
                        # If we can't validate, assume it worked to avoid infinite retry
                
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

async def fix_mp4_sar_binary(task_id: str, input_file: str, output_file: str) -> str | None:
    """
    Fix MP4 SAR using pure Python binary manipulation (very fast)
    Modifies the PASP (Pixel Aspect Ratio) atom directly
    """
    try:
        logger.info(f"🔧 [{task_id}] Attempting Python binary SAR fix...")
        
        if not os.path.exists(input_file):
            logger.error(f"❌ [{task_id}] Input file doesn't exist: {input_file}")
            return None
        
        file_size = os.path.getsize(input_file)
        if file_size == 0:
            logger.error(f"❌ [{task_id}] Input file is empty")
            return None
        
        start_time = time.time()
        
        with open(input_file, 'rb') as f:
            data = bytearray(f.read())
        
        # Look for existing PASP atom or create one
        pasp_modified = False
        
        # Find video track (moov -> trak -> mdia -> minf -> stbl -> stsd -> first entry)
        # This is a simplified approach - look for common patterns
        
        # Pattern 1: Look for existing PASP atom (4 bytes size + 4 bytes 'pasp' + 8 bytes data)
        pasp_pattern = b'pasp'
        pasp_pos = data.find(pasp_pattern)
        
        if pasp_pos > 4:  # Found existing PASP atom
            # PASP atom structure: [size:4][type:4][hSpacing:4][vSpacing:4]
            # We want hSpacing = vSpacing = 1 for square pixels
            pasp_start = pasp_pos - 4  # Position of size field
            
            # Read current PASP atom size
            current_size = struct.unpack('>I', data[pasp_start:pasp_start+4])[0]
            
            if current_size >= 16:  # Valid PASP atom size
                # Set hSpacing and vSpacing to 1:1 (square pixels)
                struct.pack_into('>I', data, pasp_start + 8, 1)   # hSpacing = 1
                struct.pack_into('>I', data, pasp_start + 12, 1)  # vSpacing = 1
                pasp_modified = True
                logger.info(f"✅ [{task_id}] Modified existing PASP atom to 1:1")
        
        # Pattern 2: Look for visual sample description and try to inject PASP
        if not pasp_modified:
            # Look for video sample description atoms (avc1, mp4v, etc.)
            video_codecs = [b'avc1', b'mp4v', b'hvc1', b'hev1']
            
            for codec in video_codecs:
                codec_pos = data.find(codec)
                if codec_pos > 8:
                    # Found video codec atom, try to add PASP after it
                    # This is more complex and risky, so we'll try a simple approach
                    
                    # Look for the end of this atom to insert PASP
                    atom_start = codec_pos - 4
                    atom_size = struct.unpack('>I', data[atom_start:atom_start+4])[0]
                    
                    if atom_size > 0 and atom_size < len(data):
                        atom_end = atom_start + atom_size
                        
                        # Create new PASP atom: [size:16][type:'pasp'][hSpacing:1][vSpacing:1]
                        pasp_atom = struct.pack('>I4sII', 16, b'pasp', 1, 1)
                        
                        # Insert PASP atom at the end of the video sample description
                        # This is simplified - real MP4 structure is more complex
                        data[atom_end:atom_end] = pasp_atom
                        
                        # Update the parent atom size
                        parent_size = struct.unpack('>I', data[atom_start:atom_start+4])[0]
                        struct.pack_into('>I', data, atom_start, parent_size + 16)
                        
                        pasp_modified = True
                        logger.info(f"✅ [{task_id}] Injected new PASP atom (1:1) into {codec.decode()} atom")
                        break
        
        if not pasp_modified:
            # Fallback: Try to modify any existing aspect ratio information
            # Look for STSD atom and modify aspect ratio fields if present
            stsd_pos = data.find(b'stsd')
            if stsd_pos > 0:
                logger.info(f"📝 [{task_id}] Found STSD atom, attempting heuristic SAR fix...")
                
                # This is a heuristic approach - look for aspect ratio patterns
                # and try to normalize them (very simplified)
                
                # Look for common non-square pixel ratios in the vicinity
                search_start = max(0, stsd_pos - 1000)
                search_end = min(len(data), stsd_pos + 2000)
                
                # Look for potential aspect ratio values near 1041:1040
                for i in range(search_start, search_end - 8, 4):
                    try:
                        val1 = struct.unpack('>I', data[i:i+4])[0]
                        val2 = struct.unpack('>I', data[i+4:i+8])[0]
                        
                        # Check if this looks like our problematic SAR (1041:1040)
                        if (val1 == 1041 and val2 == 1040) or (val1 == 1040 and val2 == 1041):
                            # Replace with 1:1
                            struct.pack_into('>I', data, i, 1)
                            struct.pack_into('>I', data, i+4, 1)
                            pasp_modified = True
                            logger.info(f"✅ [{task_id}] Found and fixed SAR values {val1}:{val2} -> 1:1 at offset {i}")
                            break
                            
                        # Also check for the inverted SAR ratio we saw (347:360)
                        if (val1 == 347 and val2 == 360) or (val1 == 360 and val2 == 347):
                            struct.pack_into('>I', data, i, 1)
                            struct.pack_into('>I', data, i+4, 1)
                            pasp_modified = True
                            logger.info(f"✅ [{task_id}] Found and fixed SAR values {val1}:{val2} -> 1:1 at offset {i}")
                            break
                            
                    except (struct.error, IndexError):
                        continue
        
        if pasp_modified:
            # Write the modified data
            with open(output_file, 'wb') as f:
                f.write(data)
            
            elapsed = time.time() - start_time
            output_size = len(data)
            logger.info(f"✅ [{task_id}] Python binary SAR fix complete in {elapsed:.2f}s")
            logger.info(f"📁 [{task_id}] Output file: {output_file} ({output_size / (1024*1024):.1f}MB)")
            
            return output_file
        else:
            logger.warning(f"⚠️ [{task_id}] Could not locate or modify SAR information in MP4 structure")
            return None
            
    except Exception as e:
        logger.error(f"❌ [{task_id}] Python binary SAR fix failed: {e}")
        return None

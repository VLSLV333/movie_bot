import os
import asyncio
import re
import logging
import subprocess
from typing import Dict
import certifi
import aiohttp
import ssl

from backend.video_redirector.config import MAX_CONCURRENT_MERGES_OF_TS_INTO_MP4
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

logger = logging.getLogger(__name__)
status_tracker: Dict[str, Dict] = {}  # Example: {task_id: {"total": 0, "done": 0, "progress": 0.0}}

semaphore = asyncio.Semaphore(MAX_CONCURRENT_MERGES_OF_TS_INTO_MP4)

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
            import json
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

async def analyze_first_ts_segment(m3u8_url: str, headers: Dict[str, str], task_id: str):
    """
    Download and analyze the first TS segment to understand source quality
    """
    try:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        async with aiohttp.ClientSession() as session:
            async with session.get(m3u8_url, headers=headers, ssl=ssl_context) as resp:
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
                        
                        # Clean up
                        os.remove(segment_path)
                    else:
                        logger.error(f"❌ [{task_id}] Failed to download first TS segment: HTTP {resp.status}")
        else:
            logger.warning(f"⚠️ [{task_id}] No TS segments found in playlist for analysis")
    
    except Exception as e:
        logger.error(f"❌ [{task_id}] Error analyzing first TS segment: {e}")

async def merge_ts_to_mp4(task_id: str, m3u8_url: str, headers: Dict[str, str]) -> str | None:
    output_file = os.path.join(DOWNLOAD_DIR, f"{task_id}.mp4")
    ffmpeg_header_str = ''.join(f"{k}: {v}\r\n" for k, v in headers.items())

    try:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        async with semaphore:  # simple limiter if many tasks run
            async with asyncio.timeout(10):
                async with aiohttp.ClientSession() as session:
                    async with session.get(m3u8_url, headers=headers, ssl=ssl_context) as resp:
                        m3u8_text = await resp.text()
    except Exception as e:
        logger.error(f"❌ [{task_id}] Failed to fetch m3u8 file: {e}")
        return None

    segment_count = sum(1 for line in m3u8_text.splitlines() if line.strip().endswith(".ts"))

    if segment_count == 0:
        logger.error(f"❌ [{task_id}] No .ts segments found in playlist")
        return None

    status_tracker[task_id] = {"total": segment_count, "done": 0, "progress": 0.0}
    logger.info(f"📦 [{task_id}] Found {segment_count} segments")

    # Analyze the first TS segment to understand source quality
    await analyze_first_ts_segment(m3u8_url, headers, task_id)

    # Merge TS files directly to MP4 using stream copying
    cmd = [
        "ffmpeg",
        "-loglevel", "info",
        "-headers", ffmpeg_header_str,
        "-protocol_whitelist", "file,http,https,tcp,tls",
        "-i", m3u8_url,
        "-c", "copy",
        "-bsf:a", "aac_adtstoasc",
        "-movflags", "+faststart",        # Optimize for streaming
        output_file
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )

    ts_pattern = re.compile(r"Opening '.*?\.ts'")

    while True:
        if process.stdout is None:
            break
        line = await process.stdout.readline()
        if not line:
            break
        decoded = line.decode().strip()
        if ts_pattern.search(decoded):
            tracker = status_tracker.get(task_id)
            if tracker:
                tracker["done"] += 1
                tracker["progress"] = round((tracker["done"] / tracker["total"]) * 100, 1)

    returncode = await process.wait()

    if returncode == 0:
        logger.info(f"✅ [{task_id}] Merge complete: {output_file}")
        
        # Log final MP4 metadata for analysis
        await log_video_metadata(output_file, task_id, "Final MP4 file")
        
        status_tracker.pop(task_id, None)
        return output_file
    else:
        if os.path.exists(output_file):
            try:
                os.remove(output_file)
                logger.info(f"🧹 [{task_id}] Removed partial output file after failure.")
            except Exception as e:
                logger.warning(f"⚠️ [{task_id}] Failed to remove partial file: {e}")

        try:
            del status_tracker[task_id]
        except KeyError:
            pass

        logger.error(f"❌ [{task_id}] Merge failed")
        return None

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

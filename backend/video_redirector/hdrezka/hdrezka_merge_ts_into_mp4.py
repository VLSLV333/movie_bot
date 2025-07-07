import os
import asyncio
import re
import logging
from typing import Dict, Optional
import certifi
import aiohttp
import ssl

from backend.video_redirector.config import MAX_CONCURRENT_MERGES_OF_TS_INTO_MP4
from backend.video_redirector.utils.notify_admin import notify_admin

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

logger = logging.getLogger(__name__)
status_tracker: Dict[str, Dict] = {}  # Example: {task_id: {"total": 0, "done": 0, "progress": 0.0}}

semaphore = asyncio.Semaphore(MAX_CONCURRENT_MERGES_OF_TS_INTO_MP4)

async def merge_ts_to_mp4(task_id: str, m3u8_url: str, headers: Dict[str, str]) -> Optional[str]:
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
        await notify_admin(f"❌ [{task_id}] Failed to fetch m3u8 file: {e}")
        return None

    try:
        segment_count = sum(1 for line in m3u8_text.splitlines() if line.strip().endswith(".ts"))

        if segment_count == 0:
            logger.error(f"❌ [{task_id}] No .ts segments found in playlist")
            await notify_admin(f"❌ [{task_id}] No .ts segments found in playlist")
            return None

        status_tracker[task_id] = {"total": segment_count, "done": 0, "progress": 0.0}
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

        logger.info(f"▶️ [{task_id}] Starting ffmpeg merge...")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )

        ts_pattern = re.compile(r"Opening '.*?\.ts'")

        if process.stdout:
            while True:
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
            status_tracker.pop(task_id, None)
            return output_file
        else:
            logger.error(f"❌ [{task_id}] FFmpeg merge failed with code {returncode}")
            await notify_admin(f"❌ [{task_id}] FFmpeg merge failed with return code {returncode}")
            
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

            return None

    except Exception as e:
        logger.error(f"❌ [{task_id}] Merge operation failed: {e}")
        await notify_admin(f"❌ [{task_id}] Merge operation failed: {e}")
        
        # Clean up on error
        if os.path.exists(output_file):
            try:
                os.remove(output_file)
                logger.info(f"🧹 [{task_id}] Removed partial output file after error.")
            except Exception as cleanup_e:
                logger.warning(f"⚠️ [{task_id}] Failed to remove partial file: {cleanup_e}")

        try:
            del status_tracker[task_id]
        except KeyError:
            pass

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
import os
import subprocess
import requests
import threading
import re
import certifi
import logging

from typing import Dict

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

logger = logging.getLogger(__name__)

status_tracker = {}  # Example: {task_id: {"total": 0, "done": 0, "progress": 0.0}}

def merge_ts_to_mp4(task_id: str, m3u8_url: str, headers: Dict[str, str]) -> str or None:
    output_file = os.path.join(DOWNLOAD_DIR, f"{task_id}.mp4")
    m3u8_path = os.path.join(DOWNLOAD_DIR, f"{task_id}.m3u8")

    ffmpeg_header_str = ''.join(f"{k}: {v}\r\n" for k, v in headers.items())

    # Step 1: Download m3u8 to count .ts segments
    try:
        r = requests.get(m3u8_url, headers=headers, timeout=10, verify=certifi.where())
        r.raise_for_status()
    except Exception as e:
        logger.error(f"❌ Failed to fetch m3u8: {e}")
        return None

    with open(m3u8_path, "w", encoding="utf-8") as f:
        f.write(r.text)

    segment_count = sum(1 for line in r.text.splitlines() if line.strip().endswith(".ts"))
    status_tracker[task_id] = {"total": segment_count, "done": 0, "progress": 0.0}
    logger.info(f"📦 [{task_id}] Found {segment_count} segments")

    # Step 2: Prepare ffmpeg command
    cmd = [
        "ffmpeg",
        "-loglevel", "info",
        "-headers", ffmpeg_header_str,
        "-protocol_whitelist", "file,http,https,tcp,tls",
        "-i", m3u8_url,
        "-c", "copy",
        "-bsf:a", "aac_adtstoasc",
        output_file
    ]

    logger.info(f"▶️ [{task_id}] Starting ffmpeg merge...")

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    segment_pattern = re.compile(r"Opening '.*?\\.ts'")

    try:
        os.remove(m3u8_path)
    except Exception as e:
        logger.warning(f"[{task_id}] Failed to delete .m3u8 file: {e}")

    def track_progress():
        for line in process.stdout:
            if segment_pattern.search(line):
                status_tracker[task_id]["done"] += 1
                total = status_tracker[task_id]["total"]
                done = status_tracker[task_id]["done"]
                status_tracker[task_id]["progress"] = round((done / total) * 100, 1)

    tracker_thread = threading.Thread(target=track_progress)
    tracker_thread.start()

    process.wait()
    tracker_thread.join()

    if process.returncode == 0:
        logger.info(f"✅ [{task_id}] Merge complete. Output: {output_file}")
        return output_file
    else:
        # Collect last few lines from ffmpeg output
        try:
            process_output = process.stdout.read() if process.stdout else ""
        except Exception:
            process_output = ""
        last_lines = process_output.strip().splitlines()[-10:]
        error_summary = "\n".join(last_lines) if last_lines else "No output captured"
        logger.error(f"❌ [{task_id}] Merge failed!\nLast output:\n{error_summary}")
        return None

def get_task_progress(task_id: str) -> Dict:
    if task_id not in status_tracker:
        return {
            "status": "not_found",
            "message": f"No active download task found with ID: {task_id}",
        }

    task = status_tracker[task_id]
    return {
        "status": "in_progress",
        "message": "Download task is running.",
        **task
    }

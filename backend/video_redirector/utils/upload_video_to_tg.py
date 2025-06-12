import os
import logging
import aiohttp
import random
from dotenv import load_dotenv
import math
import subprocess
import asyncio

from backend.video_redirector.utils.notify_admin import notify_admin

logger = logging.getLogger(__name__)
load_dotenv()


bot_tokens = os.getenv("DELIVERY_BOT_TOKEN", "").split(",")
bot_tokens = [t.strip() for t in bot_tokens if t.strip()]

MAX_MB = 1900  # safety limit to stay below Telegram's 2GB
PARTS_DIR = "downloads/parts"
os.makedirs(PARTS_DIR, exist_ok=True)

async def upload_part_to_tg(file_path: str, task_id: str, token: str, part_num: int):
    if not os.path.exists(file_path):
        logger.error(f"[{task_id}] Part {part_num} file not found: {file_path}")
        return None

    upload_url = f"https://api.telegram.org/bot{token}/sendVideo"
    chat_id_url = f"https://api.telegram.org/bot{token}/getMe"

    try:
        async with aiohttp.ClientSession() as session:
            # Get bot's own chat ID
            async with session.get(chat_id_url) as res:
                data = await res.json()
                chat_id = data["result"]["id"]

            with open(file_path, "rb") as f:
                form = aiohttp.FormData()
                form.add_field("chat_id", str(chat_id))
                form.add_field("video", f, filename=f"{task_id}_part{part_num}.mp4", content_type="video/mp4")
                form.add_field("supports_streaming", "true")
                form.add_field("disable_notification", "false")

                async with session.post(upload_url, data=form) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        logger.error(f"❌ [{task_id}] Part {part_num} upload failed: HTTP {resp.status}: {text}")
                        await notify_admin(f"❌ [{task_id}] Part {part_num} upload failed: HTTP {resp.status}: {text}")
                        return None

                    data = await resp.json()
                    file_id = data["result"]["video"]["file_id"]
                    logger.info(f"✅ [{task_id}] Uploaded part {part_num}. file_id: {file_id}")
                    return file_id
    except Exception as e:
        logger.error(f"❌ [{task_id}] Part {part_num} upload exception: {e}")
        await notify_admin(f"❌ [{task_id}] Part {part_num} upload exception: {e}")
        return None
    finally:
        try:
            os.remove(file_path)
        except Exception as e:
            logger.warning(f"[{task_id}] Failed to delete part file {file_path}: {e}")

def split_video_by_duration(file_path: str, task_id: str, num_parts: int, part_duration: float) -> list[str] | None:
    part_paths = []

    for i in range(num_parts):
        start_time = i * part_duration
        part_output = os.path.join(PARTS_DIR, f"{task_id}_part{i+1}.mp4")

        cmd = [
            "ffmpeg",
            "-ss", str(int(start_time)),
            "-i", file_path,
            "-t", str(int(part_duration)),
            "-c", "copy",
            part_output,
            "-y"
        ]

        logger.info(f"[{task_id}] Generating part {i+1}: {cmd}")
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if result.returncode != 0:
            logger.error(f"[{task_id}] FFmpeg failed on part {i+1}: {result.stderr}")
            return None

        part_paths.append(part_output)

    return part_paths

async def check_size_upload_large_file(file_path: str, task_id: str):
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    global bot_tokens
    tokens = bot_tokens[:]  # Copy to preserve original
    random.shuffle(tokens)

    for token in tokens:
        await asyncio.sleep(1.5)
        parts_result = []

        try:
            if file_size_mb <= MAX_MB:
                logger.info(f"[{task_id}] File is {round(file_size_mb)} MB — uploading as one part")
                file_id = await upload_part_to_tg(file_path, task_id, token, 1)
                if file_id:
                    return {
                        "bot_token": token,
                        "parts": [{"part": 1, "file_id": file_id}]
                    }
                else:
                    logger.error(f"[{task_id}] Upload of single-part file failed.")
                    await notify_admin(f"[{task_id}] Upload of single-part file failed.")
                    continue

            logger.info(f"[{task_id}] File is {round(file_size_mb)} MB — splitting...")

            # Step 1: Get duration
            try:
                result = subprocess.run([
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    file_path
                ], capture_output=True, text=True, check=True)
                if not result.stdout.strip():
                    raise ValueError("FFprobe returned empty duration.")
                duration = float(result.stdout.strip())
            except Exception as e:
                logger.exception(f"[{task_id}] FFprobe failed")
                await notify_admin(f"❌ [Task {task_id}] Failed to get video duration: {e}")
                continue

            num_parts = math.ceil(file_size_mb / MAX_MB)
            part_duration = duration / num_parts

            part_paths = split_video_by_duration(file_path, task_id, num_parts, part_duration)
            if not part_paths:
                await notify_admin(f"❌ [Task {task_id}] Failed to split movie during ffmpeg slicing.")
                continue

            for idx, part_path in enumerate(part_paths):
                try:
                    file_id = await upload_part_to_tg(part_path, task_id, token, idx + 1)
                    if not file_id:
                        raise RuntimeError(f"Upload failed for part {idx + 1}")
                    parts_result.append({"part": idx + 1, "file_id": file_id})
                except Exception as e:
                    logger.exception(f"[{task_id}] Error uploading part {idx + 1}")
                    await notify_admin(f"❌ [Task {task_id}] Part {idx + 1} upload failed: {e}")
                    break

            if len(parts_result) == num_parts:
                try:
                    os.remove(file_path)
                except Exception as e:
                    logger.warning(f"[{task_id}] Couldn't clean up original movie file: {e}")
                logger.info(f"[{task_id}] Upload successful with bot: {token[:10]}...")
                return {
                    "bot_token": token,
                    "parts": parts_result
                }
            else:
                logger.warning(f"[{task_id}] Upload incomplete with bot {token[:10]}... Trying another...")
                await notify_admin(f"⚠️ [Task {task_id}] Upload incomplete. Trying next delivery bot.")

        except Exception as e:
            logger.exception(f"[{task_id}] Critical error with token {token[:10]}")
            await notify_admin(f"🧨 Critical failure while handling {task_id} with bot {token[:10]}:\n{e}")

    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            logger.info(f"[{task_id}] Cleaned up leftover movie file after failed upload.")
        except Exception as e:
            logger.warning(f"[{task_id}] Couldn't delete leftover .mp4: {e}")

    logger.critical(f"🆘 [{task_id}] All delivery bots failed. No movie uploaded.")
    await notify_admin(f"🆘 [{task_id}] All delivery bots failed. User can't get content.")
    return None

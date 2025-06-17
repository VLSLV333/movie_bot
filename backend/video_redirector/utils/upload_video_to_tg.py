import os
import logging
import aiohttp
import random
from dotenv import load_dotenv
import math
import subprocess
import asyncio
from pyrogram import Client

from backend.video_redirector.utils.notify_admin import notify_admin

logger = logging.getLogger(__name__)
load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
SESSION_NAME = os.getenv("SESSION_NAME")
TG_DELIVERY_BOT_USERNAME = os.getenv("TG_DELIVERY_BOT_USERNAME")

bot_tokens = os.getenv("DELIVERY_BOT_TOKEN", "").split(",")
bot_tokens = [t.strip() for t in bot_tokens if t.strip()]

MAX_MB = 1900
PARTS_DIR = "downloads/parts"
TG_USER_ID_TO_UPLOAD = 7841848291
os.makedirs(PARTS_DIR, exist_ok=True)

async def upload_part_to_tg(file_path: str, task_id: str, part_num: int):
    if not os.path.exists(file_path):
        logger.error(f"[{task_id}] Part {part_num} file not found: {file_path}")
        return None

    logger.info(f"[{task_id}] Starting upload of part {part_num}: {file_path}")
    try:
        print(f"API_ID={API_ID}, API_HASH={API_HASH}, SESSION_NAME={SESSION_NAME}")
        async with Client(f"session_files/{SESSION_NAME}", api_id=API_ID, api_hash=API_HASH) as app:
            logger.info(f"[{task_id}] Uploading part {part_num} with Pyrogram...")
            msg = await app.send_video(
                chat_id=TG_DELIVERY_BOT_USERNAME,
                video=file_path,
                caption=f"🎬 Part {part_num}",
                disable_notification=True,
                supports_streaming=True
            )
            file_id = msg.video.file_id
            logger.info(f"✅ [{task_id}] Uploaded part {part_num} successfully. file_id: {file_id}")
            return file_id
    except Exception as err:
        logger.error(f"❌ [{task_id}] Pyrogram upload failed for part {part_num}: {err}")
        await notify_admin(f"❌ [{task_id}] Pyrogram upload failed for part {part_num}: {err}")
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
        logger.debug(f"[{task_id}] ffprobe output: {result.stdout}")
        logger.debug(f"[{task_id}] ffprobe errors: {result.stderr}")
        logger.info(f"✅ [{task_id}] Part {i + 1} generated: {part_output}")

        if result.returncode != 0:
            logger.error(f"[{task_id}] FFmpeg failed on part {i+1}: {result.stderr}")
            return None


        part_paths.append(part_output)

    logger.info(f"✅ [{task_id}] All {num_parts} parts generated successfully.")
    return part_paths

async def check_size_upload_large_file(file_path: str, task_id: str):
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    logger.info(f"[{task_id}] Checking file: {file_path} ({file_size_mb:.2f} MB)")
    global bot_tokens
    tokens = bot_tokens[:]  # Copy to preserve original
    random.shuffle(tokens)

    for token in tokens:
        await asyncio.sleep(1.5)
        parts_result = []

        try:
            if file_size_mb <= MAX_MB:
                logger.info(f"[{task_id}] File is {round(file_size_mb)} MB — uploading as one part")
                file_id = await upload_part_to_tg(file_path, task_id, 1)
                if file_id:
                    logger.info(f"✅ [{task_id}] Single-part upload complete. file_id: {file_id}")
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
                logger.debug(f"[{task_id}] ffprobe output: {result.stdout}")
                logger.debug(f"[{task_id}] ffprobe errors: {result.stderr}")
                if not result.stdout.strip():
                    raise ValueError("FFprobe returned empty duration.")
                duration = float(result.stdout.strip())
            except Exception as ero:
                logger.exception(f"[{task_id}] FFprobe failed")
                await notify_admin(f"❌ [Task {task_id}] Failed to get video duration: {ero}")
                continue

            num_parts = math.ceil(file_size_mb / MAX_MB)
            part_duration = duration / num_parts

            part_paths = split_video_by_duration(file_path, task_id, num_parts, part_duration)
            if not part_paths:
                await notify_admin(f"❌ [Task {task_id}] Failed to split movie during ffmpeg slicing.")
                continue

            for idx, part_path in enumerate(part_paths):
                try:
                    file_id = await upload_part_to_tg(part_path, task_id, idx + 1)
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
                except Exception as errr:
                    logger.warning(f"[{task_id}] Couldn't clean up original movie file: {errr}")
                logger.info(f"[{task_id}] Upload successful with bot: {token[:10]}...")
                logger.info(f"✅ [{task_id}] Multipart upload complete. {len(parts_result)} parts uploaded.")
                return {
                    "bot_token": token,
                    "parts": parts_result
                }
            else:
                logger.warning(f"[{task_id}] Upload incomplete with bot {token[:10]}... Trying another...")
                await notify_admin(f"⚠️ [Task {task_id}] Upload incomplete with bot `{token[:10]}...`. Uploaded {len(parts_result)} of {num_parts}. Trying next...")

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

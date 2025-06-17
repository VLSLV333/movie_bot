import json
import logging
import time
from backend.video_redirector.db.models import DownloadedFile, DownloadedFilePart
from backend.video_redirector.db.session import get_db
from backend.video_redirector.hdrezka.extract_to_download_from_hdrezka import extract_to_download_from_hdrezka
from backend.video_redirector.hdrezka.hdrezka_merge_ts_into_mp4 import merge_ts_to_mp4
from backend.video_redirector.utils.upload_video_to_tg import check_size_upload_large_file
from backend.video_redirector.utils.notify_admin import notify_admin
from backend.video_redirector.exceptions import RetryableDownloadError, RETRYABLE_EXCEPTIONS
from backend.video_redirector.utils.redis_client import RedisClient
from typing import Optional

logger = logging.getLogger(__name__)

async def handle_download_task(task_id: str, movie_url: str, tmdb_id: int, lang: str, dub: str):
    redis = RedisClient.get_client()
    await redis.set(f"download:{task_id}:status", "extracting", ex=3600)

    try:
        result = await extract_to_download_from_hdrezka(url=movie_url, selected_dub=dub)
        if not result:
            raise RetryableDownloadError("No playable stream found for selected dub. Or probably something went wrong")

        await redis.set(f"download:{task_id}:status", "merging", ex=3600)
        output_path = await merge_ts_to_mp4(task_id, result["url"], result['headers'])

        await redis.set(f"download:{task_id}:status", "uploading", ex=3600)
        upload_result: Optional[dict] = await check_size_upload_large_file(output_path, task_id)

        if not upload_result:
            raise Exception("Upload to Telegram failed across all delivery bots.")

        tg_bot_token_file_owner = upload_result["bot_token"]
        parts = upload_result["parts"]

        # Save in DB
        async with get_db() as session:
            db_entry = DownloadedFile(
                tmdb_id=tmdb_id,
                lang=lang,
                dub=dub,
                quality=result["quality"],
                tg_bot_token_file_owner=tg_bot_token_file_owner,
                created_at=time.time()
            )
            session.add(db_entry)
            await session.flush()  # Get db_entry.id

            db_id_to_get_parts = db_entry.id

            for part in parts:
                session.add(DownloadedFilePart(
                    downloaded_file_id=db_entry.id,
                    part_number=part["part"],
                    telegram_file_id=part["file_id"]
                ))
            await session.commit()

        await redis.set(f"download:{task_id}:status", "done", ex=3600)

        if len(parts) == 1:
            await redis.set(f"download:{task_id}:result", json.dumps({
                "tg_bot_token_file_owner":tg_bot_token_file_owner,
                "telegram_file_id":parts[0]["file_id"]
            }), ex=86400)
        else:
            await redis.set(f"download:{task_id}:result", json.dumps({
                "db_id_to_get_parts": db_id_to_get_parts,
            }), ex=86400)

    except RETRYABLE_EXCEPTIONS as e:
        logger.error(f"[Download Task {task_id}] Failed RETRYABLE_EXCEPTIONS: {e}")
        raise RetryableDownloadError(f"Temporary issue during extract: {e}")
    except Exception as e:
        logger.error(f"[Download Task {task_id}] Failed Exception: {e}")
        await redis.set(f"download:{task_id}:status", "error", ex=3600)
        await redis.set(f"download:{task_id}:error", str(e), ex=3600)
        await notify_admin(f"[Download Task {task_id}] Failed: {e}")

import json
import time
import logging
from uuid import uuid4
from fastapi import APIRouter,HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from backend.video_redirector.utils.redis_client import RedisClient
from backend.video_redirector.utils.signed_token_manager import SignedTokenManager
from backend.video_redirector.db.models import DownloadedFile, DownloadedFilePart
from backend.video_redirector.db.session import get_db
from backend.video_redirector.hdrezka.extract_to_download_from_hdrezka import extract_to_download_from_hdrezka
from backend.video_redirector.hdrezka.hdrezka_merge_ts_into_mp4 import merge_ts_to_mp4
from backend.video_redirector.utils.upload_video_to_tg import check_size_upload_large_file
from backend.video_redirector.utils.download_queue_manager import DownloadQueueManager
from backend.video_redirector.utils.notify_admin import notify_admin
from backend.video_redirector.exceptions import RetryableDownloadError, RETRYABLE_EXCEPTIONS
from typing import Optional, Union

router = APIRouter()
logger = logging.getLogger(__name__)

async def secure_download(data: str, sig: str, background_tasks: BackgroundTasks):
    try:
        payload = SignedTokenManager.verify_token(data, sig)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    tmdb_id = payload["tmdb_id"]
    lang = payload["lang"]
    dub = payload["dub"]
    tg_user_id = payload["tg_user_id"]
    movie_url= payload["movie_url"]
    task_id = str(uuid4())

    redis = RedisClient.get_client()

    await redis.set(f"download:{task_id}:status", "queued", ex=3600)
    await redis.set(f"download:{task_id}:progress", 0, ex=3600)
    await redis.set(f"download:{task_id}:user_id", tg_user_id, ex=3600)
    await redis.set(f"download:{task_id}:retries", 0, ex=3600)

    # Create task payload
    task = {
        "task_id": task_id,
        "movie_url": movie_url,
        "tmdb_id": tmdb_id,
        "lang": lang,
        "dub": dub,
        "tg_user_id": tg_user_id,
    }

    # Enqueue the task
    position = await DownloadQueueManager.enqueue(task)

    await redis.set(f"download:{task_id}:queue_position", position, ex=3600)

    return JSONResponse({
        "task_id": task_id,
        "status": "queued",
        "queue_position": position
    })


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
                "telegram_file_id":part["file_id"]
            }), ex=86400)
        else:
            await redis.set(f"download:{task_id}:result", json.dumps({
                "db_id_to_get_parts": db_id_to_get_parts,
            }), ex=86400)

    except RETRYABLE_EXCEPTIONS as e:
        logger.error(f"[Download Task {task_id}] Failed: {e}")
        raise RetryableDownloadError(f"Temporary issue during extract: {e}")
    except Exception as e:
        logger.error(f"[Download Task {task_id}] Failed: {e}")
        await redis.set(f"download:{task_id}:status", "error", ex=3600)
        await redis.set(f"download:{task_id}:error", str(e), ex=3600)
        await notify_admin(f"[Download Task {task_id}] Failed: {e}")

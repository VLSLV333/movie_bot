import logging
from uuid import uuid4
from fastapi import HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from backend.video_redirector.utils.redis_client import RedisClient
from backend.video_redirector.utils.signed_token_manager import SignedTokenManager

logger = logging.getLogger(__name__)

async def download_setup(data: str, sig: str, background_tasks: BackgroundTasks):
    from backend.video_redirector.utils.download_queue_manager import DownloadQueueManager
    try:
        payload = SignedTokenManager.verify_token(data, sig)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    tmdb_id = payload["tmdb_id"]
    lang = payload["lang"]
    dub = payload["dub"]
    tg_user_id = payload["tg_user_id"]
    movie_url= payload["movie_url"]
    movie_title = payload.get("movie_title")
    movie_poster = payload.get("movie_poster")
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
        "movie_title": movie_title,
        "movie_poster": movie_poster,
    }

    # Enqueue the task
    position = await DownloadQueueManager.enqueue(task)

    await redis.set(f"download:{task_id}:queue_position", position, ex=3600)

    return JSONResponse({
        "task_id": task_id,
        "status": "queued",
        "queue_position": position
    })

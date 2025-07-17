import logging
import json
from uuid import uuid4
from fastapi import HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from backend.video_redirector.utils.redis_client import RedisClient
from backend.video_redirector.utils.signed_token_manager import SignedTokenManager
from backend.video_redirector.db.session import get_db
from backend.video_redirector.db.crud_users import get_user_by_telegram_id
from backend.video_redirector.config import DEFAULT_USER_DOWNLOAD_LIMIT, PREMIUM_USER_DOWNLOAD_LIMIT

logger = logging.getLogger(__name__)

async def get_user_download_limit(tg_user_id):
    # Check if user is premium in DB
    async for session in get_db():
        user = await get_user_by_telegram_id(session, tg_user_id)
        if user and getattr(user, 'is_premium', False):
            return PREMIUM_USER_DOWNLOAD_LIMIT
        else:
            return DEFAULT_USER_DOWNLOAD_LIMIT
    return DEFAULT_USER_DOWNLOAD_LIMIT

async def check_duplicate_download(tg_user_id: str, tmdb_id: int, lang: str, dub: str) -> bool:
    """
    Check if user is already downloading the same movie (same tmdb_id, lang, dub)
    Returns True if duplicate found, False otherwise
    """
    redis = RedisClient.get_client()
    user_active_key = f"active_downloads:{tg_user_id}"
    
    # Get all active download task IDs for this user
    active_task_ids = await redis.smembers(user_active_key) # type: ignore
    
    for task_id in active_task_ids:
        # Check if this task is for the same movie
        task_data = await redis.get(f"download:{task_id}:task_data")
        if task_data:
            try:
                task = json.loads(task_data)
                if (task.get("tmdb_id") == tmdb_id and 
                    task.get("lang") == lang and 
                    task.get("dub") == dub):
                    return True
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Error parsing task data for {task_id}: {e}")
                continue
    
    return False

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

    # --- Check for duplicate downloads ---
    is_duplicate = await check_duplicate_download(tg_user_id, tmdb_id, lang, dub)
    if is_duplicate:
        return JSONResponse({
            "error": f"🎬 You're already downloading this video in {dub} dub. Please wait for it to finish and you will enjoy content 🥰",
            "status": "duplicate_download",
            "movie_title": movie_title
        }, status_code=409)

    # --- Check active downloads for this user ---
    user_active_key = f"active_downloads:{tg_user_id}"
    active_count = await redis.scard(user_active_key)  # type: ignore
    user_limit = await get_user_download_limit(tg_user_id)
    if active_count >= user_limit:
        return JSONResponse({
            "error": f"😮 You are already downloading the maximum number of videos allowed at once ({user_limit}). Please wait for your current download(s) to finish and then download another video 🥰",
            "status": "limit_reached",
            "user_limit": user_limit
        }, status_code=429)

    # Track this download as active for the user
    await redis.sadd(user_active_key, task_id)  # type: ignore
    await redis.expire(user_active_key, 10800)  # Optional: auto-expire

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
        "source_type": "hdrezka"
    }

    # Store task data for duplicate checking
    await redis.set(f"download:{task_id}:task_data", json.dumps(task), ex=10800)

    # Enqueue the task
    position = await DownloadQueueManager.enqueue(task)

    await redis.set(f"download:{task_id}:queue_position", position, ex=3600)

    return JSONResponse({
        "task_id": task_id,
        "status": "queued",
        "queue_position": position
    })

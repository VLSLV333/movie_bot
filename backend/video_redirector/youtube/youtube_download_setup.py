import json
import logging
from uuid import uuid4
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from backend.video_redirector.utils.signed_token_manager import SignedTokenManager
from backend.video_redirector.utils.redis_client import RedisClient
from backend.video_redirector.hdrezka.hdrezka_download_setup import check_duplicate_download, get_user_download_limit

logger = logging.getLogger(__name__)

async def youtube_download_setup(data: str, sig: str):
    from backend.video_redirector.utils.download_queue_manager import DownloadQueueManager
    """Setup YouTube download - follows same pattern as HDRezka setup"""
    try:
        payload = SignedTokenManager.verify_token(data, sig)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
        #TODO:analyse what happens on error outcomes

    tmdb_id = payload["tmdb_id"]
    lang = payload["lang"]
    dub = payload["dub"]
    tg_user_id = payload["tg_user_id"]
    video_url = payload["video_url"]
    video_title = payload.get("video_title", "YouTube Video")
    video_poster = payload.get("video_poster")
    task_id = str(uuid4())

    redis = RedisClient.get_client()

    # --- Check for duplicate downloads ---
    is_duplicate = await check_duplicate_download(tg_user_id, tmdb_id, lang, dub)
    if is_duplicate:
        return JSONResponse({
            "error": f"🎬 You're already downloading this video. Please wait for it to finish and you will enjoy content 🥰",
            "status": "duplicate_download",
            "video_title": video_title
        }, status_code=409)

    # --- Check active downloads for this user ---
    user_active_key = f"active_downloads:{tg_user_id}"
    active_count = await redis.scard(user_active_key)
    user_limit = await get_user_download_limit(tg_user_id)
    if active_count >= user_limit:
        return JSONResponse({
            "error": f"😮 You are already downloading the maximum number of videos allowed at once ({user_limit}). Please wait for your current download(s) to finish and then download another video 🥰",
            "status": "limit_reached",
            "user_limit": user_limit
        }, status_code=429)

    # Track this download as active for the user
    await redis.sadd(user_active_key, task_id)
    await redis.expire(user_active_key, 10800)  # Optional: auto-expire

    await redis.set(f"download:{task_id}:status", "queued", ex=3600)
    await redis.set(f"download:{task_id}:yt_download_progress", 0, ex=3600)
    await redis.set(f"download:{task_id}:user_id", tg_user_id, ex=3600)
    await redis.set(f"download:{task_id}:retries", 0, ex=3600)

    # Create task payload with source_type for routing
    task = {
        "task_id": task_id,
        "video_url": video_url,
        "tmdb_id": tmdb_id,
        "lang": lang,
        "dub": dub,
        "tg_user_id": tg_user_id,
        "video_title": video_title,
        "video_poster": video_poster,
        "source_type": "youtube"  # This will be used to route to YouTube executor
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
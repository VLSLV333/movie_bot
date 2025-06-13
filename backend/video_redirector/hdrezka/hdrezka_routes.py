import logging

import json
from fastapi import APIRouter, Request, BackgroundTasks, HTTPException, Response
from fastapi.responses import HTMLResponse,JSONResponse,PlainTextResponse
from pydantic import BaseModel
from uuid import uuid4
from urllib.parse import quote

from backend.video_redirector.hdrezka.hdrezka_extractor import extract_from_hdrezka
from backend.video_redirector.hdrezka.hdrezka_proxy_handler import proxy_video, proxy_segment
from backend.video_redirector.utils.templates import templates
from backend.video_redirector.utils.redis_client import RedisClient

from backend.video_redirector.hdrezka.hdrezka_all_dubs_scrapper import scrape_dubs_for_movie
from backend.video_redirector.hdrezka.hdrezka_download_setup import download_setup
from backend.video_redirector.hdrezka.hdrezka_merge_ts_into_mp4 import get_task_progress
from backend.video_redirector.utils.download_queue_manager import DownloadQueueManager


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class MovieInput(BaseModel):
    url: str
    lang: str = "ua"

router = APIRouter(prefix="/hd", tags=["HDRezka watch+download video"])

async def extract_and_generate_master_m3u8(task_id: str, url: str, lang: str):
    redis = RedisClient.get_client()

    try:
        # Step 1: Extraction
        result = await extract_from_hdrezka(url, user_lang=lang, task_id=task_id)
        await redis.set(f"extract:{task_id}:status", "extracted", ex=3600)
        await redis.set(f"extract:{task_id}:raw", json.dumps(result), ex=3600)
        print(f"[extract:{task_id}] Extraction done.")
    except Exception as e:
        await redis.set(f"extract:{task_id}:status", "error", ex=3600)
        await redis.set(f"extract:{task_id}:error", str(e), ex=3600)
        print(f"[extract:{task_id}] Extraction error: {e}")

    try:
        config_response = await get_watch_config(task_id)

        if not config_response:
            raise Exception("❌ watch_config was empty or None")

        if isinstance(config_response, JSONResponse):
            config = config_response.body.decode()
        else:
            config = json.dumps(config_response)

        if isinstance(config_response, JSONResponse):
            print(f"[{task_id}] get_watch_config returned:", config_response.body.decode())
        else:
            print(f"[{task_id}] get_watch_config returned (non-JSON):", config_response)


        await redis.set(f"extract:{task_id}:watch_config", config, ex=3600)
        await redis.set(f"extract:{task_id}:status", "done", ex=3600)
    except Exception as e:
        print(f"[extract:{task_id}] Error building watch_config: {e}")
        await redis.set(f"extract:{task_id}:status", "error", ex=3600)
        await redis.set(f"extract:{task_id}:error", f"watch_config error: {str(e)}", ex=3600)


@router.post("/extract")
async def extract_entry(data: MovieInput, background_tasks: BackgroundTasks):
    task_id = str(uuid4())
    redis = RedisClient.get_client()
    await redis.set(f"extract:{task_id}:status", "pending", ex=3600)

    background_tasks.add_task(extract_and_generate_master_m3u8, task_id, data.url, data.lang)
    print(f"[extract:{task_id}] Extraction started for {data.url}")

    return {"task_id": task_id, "status": "started"}

@router.get("/status/watch/{task_id}")
async def check_watch_status(task_id: str):
    redis = RedisClient.get_client()

    status = await redis.get(f"extract:{task_id}:status")
    if not status:
        raise HTTPException(status_code=404, detail="Task not found")

    if status == "done":
        data = await redis.get(f"extract:{task_id}:watch_config")
        return {"status": status, "data": json.loads(data)}
    elif status == "error":
        error = await redis.get(f"extract:{task_id}:error")
        return {"status": status, "error": error}
    else:
        return {"status": status}

@router.get("/status/merge_progress/{task_id}")
async def check_merge_status(task_id: str):
    """
    Check the progress of .ts -> .mp4 merging for a given task_id.
    Returns: {status, message, progress, done, total}
    """
    return JSONResponse(content=get_task_progress(task_id))

@router.get("/watch-config/{task_id}")
async def get_watch_config(task_id: str):
    redis = RedisClient.get_client()
    status = await redis.get(f"extract:{task_id}:status")

    if not status:
        return JSONResponse(content={"error": f"Task ID '{task_id}' not found in Redis"}, status_code=404)

    if status == "done":
        raw_data = await redis.get(f"extract:{task_id}:watch_config")
        print("[get_watch_config returned]:", json.dumps(raw_data, ensure_ascii=False, indent=2))
        if not raw_data:
            print(f"🛑 Inconsistent Redis state: {task_id} has status=done but no config found")
            return JSONResponse(content={"error": "Config missing despite status=done"}, status_code=500)
        try:
            return JSONResponse(content=json.loads(raw_data))
        except Exception as e:
            return JSONResponse(content={"error": f"Corrupted config JSON: {str(e)}"}, status_code=500)

    if status == "pending":
        return JSONResponse(content={"error": "Extraction still pending"}, status_code=202)

    if status == "extracted":

        raw_data = await redis.get(f"extract:{task_id}:raw")
        if not raw_data:
            print(f"🛑 Extraction raw data missing, but status is 'extracted', task_id: {task_id} ")
            return JSONResponse(content={"error": "Extraction raw data missing"}, status_code=500)

        try:
            parsed = json.loads(raw_data)
        except Exception as e:
            return JSONResponse(content={"error": f"Invalid JSON in raw data: {str(e)}"}, status_code=500)

        watch_config = {}

        for lang, dubs in parsed.items():
            watch_config[lang] = {}
            for dub_name, dub_data in dubs.items():
                qualities = dub_data.get("all_m3u8", [])
                subtitles = dub_data.get("subtitles", [])

                # Build master m3u8 content
                lines = ["#EXTM3U"]
                for item in qualities:
                    quality = item.get("quality")
                    url = item.get("url")
                    if not quality or not url:
                        continue
                    encoded = quote(url, safe="")

                    bandwidth = {
                        "360p": 800000,
                        "480p": 1400000,
                        "720p": 2800000,
                        "1080p": 5000000,
                        "1080pUltra": 6500000
                    }.get(quality, 1000000)

                    resolution = {
                        "360p": "640x360",
                        "480p": "854x480",
                        "720p": "1280x720",
                        "1080p": "1920x1080",
                        "1080pUltra": "1920x1080"
                    }.get(quality, "1280x720")

                    lines.append(f"#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},RESOLUTION={resolution}")
                    lines.append(f"/hd/proxy-video/{task_id}/{encoded}")

                master_m3u8 = "\n".join(lines)

                await redis.set(f"master_m3u8:{task_id}:{lang}:{dub_name}", master_m3u8, ex=28800)

                watch_config[lang][dub_name] = {
                    "m3u8": f"/hd/proxy-master/{task_id}?lang={lang}&dub={quote(dub_name)}",
                    "subtitles": subtitles
                }

        return JSONResponse(content=watch_config)

    return JSONResponse(content={"error": f"Unexpected status value: {status}"}, status_code=500)


@router.get("/proxy-master/{task_id}")
async def serve_master_m3u8(task_id: str, lang: str, dub: str):
    redis = RedisClient.get_client()
    key = f"master_m3u8:{task_id}:{lang}:{dub}"
    master_m3u8 = await redis.get(key)
    if not master_m3u8:
        return PlainTextResponse("Master M3U8 not found", status_code=404)

    return PlainTextResponse(content=master_m3u8, media_type="application/vnd.apple.mpegurl")

# --- New proxy-video route for individual segments ---
@router.get("/proxy-video/{movie_id}/{encoded_path:path}")
async def proxy_video_router(movie_id: str, encoded_path: str, request: Request):
    if encoded_path.endswith(".ts"):
        return await proxy_segment(movie_id, encoded_path, request)
    else:
        return await proxy_video(movie_id, request)

@router.get("/proxy-segment/{movie_id}/{encoded_path:path}")
async def proxy_segment_router(movie_id: str, encoded_path: str, request: Request) -> Response :
    return await proxy_segment(movie_id, encoded_path, request)

@router.post("/log-client-error")
async def log_client_error(request: Request):
    data = await request.json()
    print(f"⚠️ Client Error: {json.dumps(data, ensure_ascii=False, indent=2)}")
    return {"status": "logged"}

#TODO: DO we really need movie_id? We probably should change it to smth else

# --- Updated watch route ---
@router.get("/watch/{movie_id}", response_class=HTMLResponse)
async def watch_movie(movie_id: str, request: Request):
    return templates.TemplateResponse("hdrezka/watch.html", {
        "request": request,
        "movie_id": movie_id,
    })

@router.get("/download")
async def download(data: str, sig: str, background_tasks: BackgroundTasks):
    return await download_setup(data, sig, background_tasks)

@router.get("/status/download/{task_id}")
async def check_full_download_status(task_id: str):
    redis = RedisClient.get_client()

    status = await redis.get(f"download:{task_id}:status")
    if not status:
        raise HTTPException(status_code=404, detail="Download task not found")

    response = {"status": status}

    if status == "error":
        response["error"] = await redis.get(f"download:{task_id}:error")

    elif status == "done":
        result = await redis.get(f"download:{task_id}:result")
        if result:
            response["result"] = json.loads(result)

    retries = await redis.get(f"download:{task_id}:retries")
    if retries is not None:
        response["retries"] = int(retries)

    position = await DownloadQueueManager.get_position_by_task_id(task_id)
    if position:
        response["queue_position"] = position

    return response

@router.post("/alldubs")
async def get_all_dubs(data: MovieInput):
    try:
        result = await scrape_dubs_for_movie(data.url, data.lang)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Failed to scrape dubs: {e}")
        return JSONResponse(status_code=500, content={"error": "Internal error while scraping dubs"})

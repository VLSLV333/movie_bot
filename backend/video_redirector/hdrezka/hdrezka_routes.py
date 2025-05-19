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

class ExtractRequest(BaseModel):
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

        print(f"[{task_id}] get_watch_config returned:", config_response)
        await redis.set(f"extract:{task_id}:watch_config", config, ex=3600)
        await redis.set(f"extract:{task_id}:status", "done", ex=3600)
    except Exception as e:
        print(f"[extract:{task_id}] Error building watch_config: {e}")
        await redis.set(f"extract:{task_id}:status", "error", ex=3600)
        await redis.set(f"extract:{task_id}:error", f"watch_config error: {str(e)}", ex=3600)


@router.post("/extract")
async def extract_entry(data: ExtractRequest, background_tasks: BackgroundTasks):
    task_id = str(uuid4())
    redis = RedisClient.get_client()
    await redis.set(f"extract:{task_id}:status", "pending", ex=3600)

    background_tasks.add_task(extract_and_generate_master_m3u8, task_id, data.url, data.lang)
    print(f"[extract:{task_id}] Extraction started for {data.url}")

    return {"task_id": task_id, "status": "started"}

@router.get("/status/{task_id}")
async def check_status(task_id: str):
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

@router.get("/watch-config/{task_id}")
async def get_watch_config(task_id: str):
    redis = RedisClient.get_client()

    status = await redis.get(f"extract:{task_id}:status")

    if status == "done":
        raw_data = await redis.get(f"extract:{task_id}:watch_config")
        if not raw_data:
            raise HTTPException(status_code=404, detail="Config missing despite status=done")
        try:
            return JSONResponse(content=json.loads(raw_data))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Corrupted config: {e}")

    if status == "pending":
        raise HTTPException(status_code=400, detail="Extraction not completed yet")

    elif status == 'extracted':

        raw_data = await redis.get(f"extract:{task_id}:raw")
        if not raw_data:
            raise HTTPException(status_code=404, detail="Extraction result not found")

        parsed = json.loads(raw_data)
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


#TODO: DO we really need movie_id? We probably should change it to smth else

# --- Updated watch route ---
@router.get("/watch/{movie_id}", response_class=HTMLResponse)
async def watch_movie(movie_id: str, request: Request):
    return templates.TemplateResponse("hdrezka/watch.html", {
        "request": request,
        "movie_id": movie_id,
    })

@router.get("/download/{movie_id}", response_class=HTMLResponse)
async def redirect_download(movie_id: str, request: Request):
    # TODO: create download logic
    return

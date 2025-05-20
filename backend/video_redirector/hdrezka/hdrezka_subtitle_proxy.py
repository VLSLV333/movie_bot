from fastapi import APIRouter, Response
from backend.video_redirector.utils.redis_client import RedisClient
import aiohttp

router = APIRouter(prefix="/hd", tags=["HDRezka subtitles"])

FORWARD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Origin": "https://hdrezka.ag",
    "Referer": "https://hdrezka.ag/",
    "Connection": "keep-alive"
}


@router.get("/subs/{task_id}/{dub_name}/{lang}.vtt")
async def proxy_subtitle(task_id: str, dub_name: str, lang: str):
    redis = RedisClient.get_client()
    subtitle_key = f"subs:{task_id}:{dub_name}:{lang}"
    subtitle_url = await redis.get(subtitle_key)

    if not subtitle_url:
        return Response(content=f"Subtitle not found for key: {subtitle_key}", status_code=404)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(subtitle_url, headers=FORWARD_HEADERS) as resp:
                if resp.status != 200:
                    return Response(content=f"Failed to fetch subtitle (status: {resp.status})", status_code=resp.status)
                content = await resp.read()
                return Response(content=content, media_type="text/vtt")
    except Exception as e:
        return Response(content=f"Subtitle proxy error: {e}", status_code=500)

@router.get("/subs/{task_id}.vtt")
async def fallback_subtitle_proxy(task_id: str):
    redis = RedisClient.get_client()
    # Your extractor saves with no dub/lang, just single flat fallback
    keys = await redis.keys(f"subs:{task_id}:fallback")
    if not keys:
        return Response(content="Fallback subtitle not found", status_code=404)

    first_key = keys[0]
    subtitle_url = await redis.get(first_key)
    if not subtitle_url:
        return Response(content="Subtitle URL missing", status_code=404)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(subtitle_url, headers=FORWARD_HEADERS) as resp:
                content = await resp.read()
                return Response(content=content, media_type="text/vtt")
    except Exception as e:
        return Response(content=f"Subtitle proxy error: {e}", status_code=500)
import aiohttp
import asyncio
import json

from fastapi import Request, Response
from starlette.responses import StreamingResponse, PlainTextResponse
from urllib.parse import unquote, quote, urljoin
from backend.video_redirector.utils.redis_client import RedisClient

REAL_M3U8_URL = "https://prx3-cogent.ukrtelcdn.net/s__pixel/fe5f320a468509a7d4b5eb499f791dc8:2025050813:VWtDQkdHQnZZZWk2NE9uc1M4UTJMcFl4UUtCck85Yi9tNTFxRDJUcnRsaXdsRk9qUEp4N1QwZVRiYmVjeDBTTVhGN2RTc0xhWHpuUExRdWZRelF0NUE9PQ==/8/5/6/0/1/8/swe1d.mp4:hls:manifest.m3u8"

FORWARD_HEADERS = {
    "Host": "prx4-cogent.ukrtelcdn.net",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:135.0) Gecko/20100101 Firefox/135.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "identity",  # disable compression for video chunks
    "Origin": "https://hdrezka.ag",
    "Referer": "https://hdrezka.ag/",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site"
}


async def proxy_video(movie_id: str, request: Request) -> Response:
    lang = request.query_params.get("lang")
    dub = request.query_params.get("dub")

    if not lang or not dub:
        return PlainTextResponse("Missing lang or dub", status_code=400)

    redis = RedisClient.get_client()
    key = f"extract:{movie_id}:watch_config"
    raw_config = await redis.get(key)
    if not raw_config:
        return PlainTextResponse("Watch config not found", status_code=404)

    try:
        config = json.loads(raw_config)
        dub_config = config.get(lang, {}).get(dub)
        if not dub_config:
            return PlainTextResponse("Dub config not found", status_code=404)

        master_m3u8 = dub_config["master_m3u8"]
        # Extract the first streamline (assuming player requests /hd/proxy-video with no path)
        for line in master_m3u8.splitlines():
            if line.startswith("/hd/proxy-video/"):
                # Reconstruct original m3u8 URL
                encoded = line.split("/")[-1]
                real_url = unquote(encoded)
                return await fetch_and_rewrite_m3u8(real_url, movie_id)

        return PlainTextResponse("No valid stream found", status_code=404)
    except Exception as e:
        return PlainTextResponse(f"Error: {e}", status_code=500)


async def proxy_segment(movie_id: str, segment_encoded: str, request: Request) -> Response:
    real_url = unquote(segment_encoded)
    print(f"[Segment] Proxying segment: {real_url}")
    session_timeout = aiohttp.ClientTimeout(total=15)

    try:
        async with aiohttp.ClientSession(timeout=session_timeout) as session:
            async with session.get(real_url, headers=FORWARD_HEADERS) as resp:
                if resp.status != 200:
                    print(f"[Segment Error] {real_url} returned {resp.status}")
                    return PlainTextResponse("Segment failed", status_code=resp.status)

                content_type = resp.headers.get("Content-Type", "video/MP2T")
                body = await resp.read()
                return Response(content=body, media_type=content_type, status_code=200)

    except Exception as e:
        print(f"[Proxy Segment Error]: {e} | Segment: {real_url}")
        return PlainTextResponse("Internal proxy error", status_code=500)


async def fetch_and_rewrite_m3u8(url: str, movie_id: str) -> Response:
    session_timeout = aiohttp.ClientTimeout(total=30)
    base_url = url.rsplit('/', 1)[0] + '/'

    async with aiohttp.ClientSession(timeout=session_timeout) as session:
        async with session.get(url, headers=FORWARD_HEADERS) as remote_response:
            if remote_response.status != 200:
                return PlainTextResponse(f"Error fetching m3u8: {remote_response.status}", status_code=remote_response.status)

            m3u8_text = await remote_response.text()
            rewritten_lines = []

            for line in m3u8_text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    rewritten_lines.append(line)
                    continue

                if not line.startswith("http"):
                    line = urljoin(base_url, line)
                encoded = quote(line, safe='')
                proxy_url = f"/hd/proxy-video/{movie_id}/{encoded}"
                rewritten_lines.append(proxy_url)

            rewritten_m3u8 = "\n".join(rewritten_lines)
            return PlainTextResponse(content=rewritten_m3u8, media_type="application/vnd.apple.mpegurl")

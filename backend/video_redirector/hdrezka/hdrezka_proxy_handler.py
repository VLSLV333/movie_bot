import aiohttp
from fastapi import Request, Response
from starlette.responses import StreamingResponse, PlainTextResponse
from urllib.parse import unquote, quote, urljoin
from backend.video_redirector.utils.redis_client import RedisClient

FORWARD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:135.0) Gecko/20100101 Firefox/135.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "identity",  # Disable compression for video chunks
    "Origin": "https://hdrezka.ag",
    "Referer": "https://hdrezka.ag/",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site"
}

async def proxy_video(movie_id: str, request: Request) -> Response:
    """
    Handles /hd/proxy-video/{movie_id}/{encoded_real_m3u8_url}
    """
    full_path = request.url.path
    encoded_url = full_path.split(f"/hd/proxy-video/{movie_id}/", 1)[-1]
    real_url = unquote(encoded_url)

    print(f"[proxy_video] Decoded URL: {real_url}")
    return await fetch_and_rewrite_m3u8(real_url, movie_id)


async def proxy_segment(movie_id: str, segment_encoded: str, request: Request) -> Response:
    """
    Handles .ts segment requests by downloading and forwarding the content.
    """

    redis = RedisClient.get_client()
    base_url = await redis.get(f"extract:{movie_id}:segment_base")
    if not base_url:
        print(f"[Segment Error] Base URL not found for movie_id={movie_id}")
        return PlainTextResponse("Base URL missing", status_code=500)


    real_url = urljoin(base_url, unquote(segment_encoded))
    session_timeout = aiohttp.ClientTimeout(total=15)

    print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!        [Proxy Segment] Using base_url={base_url}")

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

    redis = RedisClient.get_client()
    await redis.set(f"extract:{movie_id}:segment_base", base_url, ex=3600)

    try:
        async with aiohttp.ClientSession(timeout=session_timeout) as session:
            async with session.get(url, headers=FORWARD_HEADERS) as remote_response:
                if remote_response.status != 200:
                    return PlainTextResponse(f"Error fetching m3u8: {remote_response.status}", status_code=remote_response.status)

                m3u8_text = await remote_response.text()

                if not "#EXTM3U" in m3u8_text:
                    print(f"[proxy_video] Not a valid .m3u8 playlist: {url}")
                    return PlainTextResponse("Not a valid .m3u8 playlist", status_code=500)

                if not url.endswith(".m3u8"):
                    print("[proxy_video] URL doesn't end with .m3u8 — skipping rewrite.")
                    return PlainTextResponse("Not a playlist URL", status_code=400)

                print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!         Original M3U8 content:")
                print(m3u8_text)

                lines = m3u8_text.splitlines()
                rewritten_lines = []

                for line in lines:
                    print(f'line:{line}')
                    stripped = line.strip()

                    # Leave comments and tags as-is
                    if stripped.startswith("#") or not stripped:
                        rewritten_lines.append(stripped)
                        continue

                    # Build full URL from relative path
                    if not stripped.startswith("http"):
                        full_url = urljoin(base_url, stripped)
                    else:
                        full_url = stripped

                    # Optionally normalize colons
                    safe_url = full_url.replace(":", "%3A")
                    encoded = quote(safe_url, safe='')

                    # Route based on type
                    if ".m3u8" in stripped:
                        proxy_url = f"/hd/proxy-video/{movie_id}/{encoded}"
                    else:
                        proxy_url = f"/hd/proxy-segment/{movie_id}/{encoded}"

                    rewritten_lines.append(proxy_url)

                rewritten_m3u8 = "\n".join(rewritten_lines)
                print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!        Rewritten M3U8 content:")
                print(rewritten_m3u8)

                if ".hls:" in url:
                    base_url = url.rsplit('/', 1)[0] + '/'
                    await redis.set(f"extract:{movie_id}:segment_base", base_url, ex=3600)
                    print(f"[proxy_video] Saved segment_base for {movie_id}: {base_url}")

                return PlainTextResponse(content=rewritten_m3u8, media_type="application/vnd.apple.mpegurl")

    except Exception as e:
        print(f"[M3U8 Proxy Error]: {e}")
        return PlainTextResponse("Internal proxy error", status_code=500)

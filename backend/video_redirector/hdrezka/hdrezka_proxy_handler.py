import aiohttp
import asyncio
import logging
from fastapi import Request, Response
from starlette.responses import StreamingResponse, PlainTextResponse
from urllib.parse import unquote, quote, urljoin
from backend.video_redirector.utils.redis_client import RedisClient

logger = logging.getLogger(__name__)

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

    return await fetch_and_rewrite_m3u8(real_url, movie_id)


async def proxy_segment(movie_id: str, segment_encoded: str, request: Request) -> Response:
    """
    Handles .ts segment requests by downloading and forwarding the content.
    """
    redis = RedisClient.get_client()
    base_url = await redis.get(f"extract:{movie_id}:segment_base")
    if not base_url:
        logger.error(f"[Segment Error] Base URL not found for movie_id={movie_id}")
        return PlainTextResponse("Base URL missing", status_code=500)

    real_url = urljoin(base_url, unquote(segment_encoded))
    session_timeout = aiohttp.ClientTimeout(total=15)
    max_retries = 3
    retry_delay = 2

    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession(timeout=session_timeout) as session:
                async with session.get(real_url, headers=FORWARD_HEADERS) as resp:
                    if resp.status != 200:
                        logger.warning(f"[Segment Error] {real_url} returned {resp.status} (attempt {attempt + 1}/{max_retries})")
                        if attempt == max_retries - 1:
                            return PlainTextResponse(f"Segment failed after {max_retries} attempts", status_code=resp.status)
                        continue

                    content_type = resp.headers.get("Content-Type", "video/MP2T")
                    body = await resp.read()
                    
                    if not body:
                        logger.warning(f"[Segment Error] Empty response for {real_url} (attempt {attempt + 1}/{max_retries})")
                        if attempt == max_retries - 1:
                            return PlainTextResponse("Empty segment data", status_code=500)
                        continue
                    
                    logger.debug(f"[Segment Success] {real_url} - {len(body)} bytes")
                    return Response(content=body, media_type=content_type, status_code=200)

        except aiohttp.ClientTimeout as e:
            logger.warning(f"[Segment Timeout] {real_url} (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                return PlainTextResponse("Segment timeout", status_code=408)
        except aiohttp.ClientError as e:
            logger.warning(f"[Segment Client Error] {real_url} (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                return PlainTextResponse("Segment client error", status_code=502)
        except Exception as e:
            logger.error(f"[Proxy Segment Error] {real_url} (attempt {attempt + 1}/{max_retries}): {type(e).__name__}: {e}")
            if attempt == max_retries - 1:
                return PlainTextResponse("Internal proxy error", status_code=500)
        
        # Wait before retry (exponential backoff)
        if attempt < max_retries - 1:
            await asyncio.sleep(retry_delay * (2 ** attempt))

    return PlainTextResponse("All retry attempts failed", status_code=500)


async def fetch_and_rewrite_m3u8(url: str, movie_id: str) -> Response:
    session_timeout = aiohttp.ClientTimeout(total=30)
    base_url = url.rsplit('/', 1)[0] + '/'

    redis = RedisClient.get_client()
    await redis.set(f"extract:{movie_id}:segment_base", base_url, ex=3600)

    try:
        async with aiohttp.ClientSession(timeout=session_timeout) as session:
            async with session.get(url, headers=FORWARD_HEADERS) as remote_response:
                if remote_response.status != 200:
                    logger.error(f"[M3U8 Error] {url} returned {remote_response.status}")
                    return PlainTextResponse(f"Error fetching m3u8: {remote_response.status}", status_code=remote_response.status)

                m3u8_text = await remote_response.text()

                if not "#EXTM3U" in m3u8_text:
                    logger.error(f"[proxy_video] Not a valid .m3u8 playlist: {url}")
                    return PlainTextResponse("Not a valid .m3u8 playlist", status_code=500)

                if not url.endswith(".m3u8"):
                    logger.warning("[proxy_video] URL doesn't end with .m3u8 — skipping rewrite.")
                    return PlainTextResponse("Not a playlist URL", status_code=400)

                lines = m3u8_text.splitlines()
                rewritten_lines = []

                for line in lines:
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

                    encoded = quote(full_url, safe='')

                    # Route based on type
                    if ".m3u8" in stripped:
                        proxy_url = f"/hd/proxy-video/{movie_id}/{encoded}"
                    else:
                        proxy_url = f"/hd/proxy-segment/{movie_id}/{encoded}"

                    rewritten_lines.append(proxy_url)

                rewritten_m3u8 = "\n".join(rewritten_lines)

                if ".hls:" in url:
                    base_url = url.rsplit('/', 1)[0] + '/'
                    await redis.set(f"extract:{movie_id}:segment_base", base_url, ex=3600)

                return PlainTextResponse(content=rewritten_m3u8, media_type="application/vnd.apple.mpegurl")

    except aiohttp.ClientTimeout as e:
        logger.error(f"[M3U8 Timeout] {url}: {e}")
        return PlainTextResponse("M3U8 fetch timeout", status_code=408)
    except aiohttp.ClientError as e:
        logger.error(f"[M3U8 Client Error] {url}: {e}")
        return PlainTextResponse("M3U8 client error", status_code=502)
    except Exception as e:
        logger.error(f"[M3U8 Proxy Error] {url}: {type(e).__name__}: {e}")
        return PlainTextResponse("Internal proxy error", status_code=500)

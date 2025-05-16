import aiohttp
from fastapi import Request, Response
from starlette.responses import StreamingResponse, PlainTextResponse
from urllib.parse import unquote, quote, urljoin

# Placeholder default (will be replaced by actual incoming request URLs)
REAL_M3U8_URL = "https://example.com/fallback/manifest.m3u8"

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
    encoded_url = request.url.path.rsplit("/", 1)[-1]
    real_url = unquote(encoded_url)
    return await fetch_and_rewrite_m3u8(real_url, movie_id)


async def proxy_segment(movie_id: str, segment_encoded: str, request: Request) -> Response:
    """
    Handles .ts segment requests by downloading and forwarding the content.
    """
    real_url = unquote(segment_encoded)
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

    try:
        async with aiohttp.ClientSession(timeout=session_timeout) as session:
            async with session.get(url, headers=FORWARD_HEADERS) as remote_response:
                if remote_response.status != 200:
                    return PlainTextResponse(f"Error fetching m3u8: {remote_response.status}", status_code=remote_response.status)

                m3u8_text = await remote_response.text()
                lines = m3u8_text.splitlines()
                rewritten_lines = []

                is_master = any("#EXT-X-STREAM-INF" in line for line in lines)
                print(f"🎬 Serving {'master' if is_master else 'variant'} playlist for: {url}")

                for line in lines:
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        rewritten_lines.append(line)
                        continue

                    if not stripped.startswith("http"):
                        full_url = urljoin(base_url, stripped)
                    else:
                        full_url = stripped

                    encoded = quote(full_url, safe='')

                    if is_master:
                        proxy_url = f"/hd/proxy-video/{movie_id}/{encoded}"
                    else:
                        proxy_url = f"/hd/proxy-video/{movie_id}/{encoded}" if ".m3u8" in stripped else f"/hd/proxy-segment/{movie_id}/{encoded}"

                    rewritten_lines.append(proxy_url)

                rewritten_m3u8 = "\n".join(rewritten_lines)
                return PlainTextResponse(content=rewritten_m3u8, media_type="application/vnd.apple.mpegurl")

    except Exception as e:
        print(f"[M3U8 Proxy Error]: {e}")
        return PlainTextResponse("Internal proxy error", status_code=500)

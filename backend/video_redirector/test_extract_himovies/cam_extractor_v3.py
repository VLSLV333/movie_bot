import asyncio
from camoufox.async_api import AsyncCamoufox
import re
import httpx

MOVIE_PAGE = "https://himovies.sx/watch-movie/john-wick-19789.5297287"
EPISODE_API = "https://himovies.sx/ajax/episode/sources/5297287"

async def get_iframe_url():
    async with httpx.AsyncClient() as client:
        r = await client.get(EPISODE_API, headers={
            "Referer": MOVIE_PAGE,
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

    match = re.search(r'id=(.*?)&', r.text)
    if match:
        iframe_id = match.group(1)
        return f"https://megacloud.store/embed-1/?id={iframe_id}"
    else:
        print("❌ Failed to extract iframe ID.")
        return None

async def extract_video_requests_from_iframe(iframe_url):
    extracted = {
        "m3u8_urls": [],
        "ts_segments": [],
        "cookies": {},
    }

    async with AsyncCamoufox(headless=False, humanize=True) as browser:
        page = await browser.new_page()

        def handle_response(response):
            url = response.url
            if ".m3u8" in url:
                print("🎯 .m3u8 URL:", url)
                extracted["m3u8_urls"].append(url)
            elif any(url.endswith(ext) for ext in [".ts", ".m4s"]):
                print("📦 Segment:", url)
                extracted["ts_segments"].append(url)

        page.on("response", handle_response)

        await page.goto(iframe_url, wait_until="domcontentloaded")
        await page.wait_for_selector(".vjs-big-play-button", timeout=10000)
        await page.click(".vjs-big-play-button")
        print("▶️ Clicked play on iframe")

        # Wait for video traffic
        await asyncio.sleep(15)

        extracted["cookies"] = await page.context.cookies()
        return extracted

async def main():
    iframe_url = await get_iframe_url()
    if iframe_url:
        result = await extract_video_requests_from_iframe(iframe_url)
        print("\n✅ M3U8:", result["m3u8_urls"][:1])
        print("✅ Segments:", result["ts_segments"][:3])
        print("✅ Cookies:", result["cookies"])

if __name__ == "__main__":
    asyncio.run(main())

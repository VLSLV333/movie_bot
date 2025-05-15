import asyncio
from camoufox.async_api import AsyncCamoufox
from typing import Dict, List, Any


async def extract_m3u8_from_himovies(url: str) -> Dict:
    extracted = {
        "all_m3u8": [],
        "all_segments": [],
        "first_m3u8": {},
    }

    async with AsyncCamoufox(window=(1280, 720), humanize=True, headless=False) as browser:
        page = await browser.new_page()

        await page.goto(url, wait_until="domcontentloaded")

        # --- Wait for iframe containing video ---
        try:
            await page.wait_for_selector("iframe", timeout=10000)
        except Exception as e:
            print(f"[Extractor] Iframe not found within timeout, error: {e}")
            return extracted

        # Simulate user interaction to trigger playback
        await asyncio.sleep(1)  # Give the page a moment to stabilize
        await page.mouse.click(949, 394)  # Click center-bottom area to hide "share add"
        await page.mouse.click(912  , 337)  # Click center-bottom area to hit Play
        print("[Extractor] Clicked on center to trigger playback")

        async def handle_response(response):
            req_url = response.url
            if ".m3u8" in req_url:
                extracted["all_m3u8"].append({
                    "url": req_url,
                    "headers": dict(response.request.headers),
                    "referer": response.request.headers.get("referer")
                })
                if not extracted["first_m3u8"]:
                    extracted["first_m3u8"] = {
                    "url": req_url,
                    "headers": dict(response.request.headers),
                    "referer": response.request.headers.get("referer")
                }
            elif any(ext in req_url for ext in [".ts", ".m4s"]):
                extracted["all_segments"].append({
                    "url": req_url,
                    "headers": dict(response.request.headers),
                    "referer": response.request.headers.get("referer")
                })

        page.on("response", handle_response)

        # --- Wait 15–30 seconds for network requests to appear ---
        print("[Extractor] Watching network traffic for 40s...")
        await asyncio.sleep(40)

        print(f"[Extractor] Found {len(extracted['all_m3u8'])} .m3u8 and {len(extracted['all_segments'])} segments")

        return extracted


# Example usage:
if __name__ == "__main__":
    test_url = "https://himovies.sx/watch-movie/john-wick-19789.5297287"

    async def test():
        data = await extract_m3u8_from_himovies(test_url)
        print("First M3U8:", data["first_m3u8"])
        print("All M3U8s:", data["all_m3u8"])  # print first 2 for brevity
        print("Segments:", data["all_segments"])  # print first 3 for brevity

    asyncio.run(test())


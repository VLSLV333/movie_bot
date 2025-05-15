import asyncio
from camoufox.async_api import AsyncCamoufox
from typing import Dict, List

async def extract_from_iframe_directly(url: str) -> Dict:
    extracted = {
        "all_m3u8": [],
        "all_segments": [],
        "first_m3u8": {},
    }

    async with AsyncCamoufox(window=(1280, 720), humanize=True, headless=False) as browser:
        page = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded")

        try:
            await page.wait_for_selector("iframe", timeout=10000)
            iframe_element = await page.query_selector("iframe")
            iframe_url = await iframe_element.get_attribute("src")
            print("[Extractor] Found iframe URL:", iframe_url)
        except Exception as e:
            print(f"[Extractor] Failed to find iframe: {e}")
            return extracted

        # Set fake referer header
        await page.set_extra_http_headers({"referer": url})

        # Set fake referer header
        # await page.set_extra_http_headers(FORWARD_HEADERS)

        # Navigate into iframe URL directly in same tab
        try:
            await page.goto(iframe_url, wait_until="domcontentloaded")
            print("[Extractor] Navigated directly into iframe URL")
        except Exception as e:
            print(f"[Extractor] Failed to navigate to iframe URL: {e}")
            return extracted

        # Simulate user interaction (optional)
        await asyncio.sleep(1)
        await page.mouse.click(640, 360)  # click center to trigger playback
        print("[Extractor] Clicked to start playback on iframe page")

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

        print("[Extractor] Watching network traffic for 30s on iframe page...")
        await asyncio.sleep(30)

        print(f"[Extractor] Found {len(extracted['all_m3u8'])} .m3u8 and {len(extracted['all_segments'])} segments")
        return extracted


# Example usage
if __name__ == "__main__":
    test_url = "https://himovies.sx/watch-movie/john-wick-19789.5297287"

    async def test():
        result = await extract_from_iframe_directly(test_url)
        print("First M3U8:", result["first_m3u8"])
        print("All M3U8s:", result["all_m3u8"])
        print("Segments:", result["all_segments"])

    asyncio.run(test())

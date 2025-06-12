import asyncio
import json
from camoufox.async_api import AsyncCamoufox

f2id_to_quality = {
    "3": "720p",
    "4": "1080p",
}

async def extract_to_download_from_hdrezka(url: str, selected_dub: str) -> dict:
    async with AsyncCamoufox(window=(1280, 720), humanize=True, headless=True) as browser:
        page = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(1)

        extracted = {"all_m3u8": []}

        li_items = await page.query_selector_all("#translators-list a")
        selected_element = None

        if not li_items:
            await extract_best_quality_variant(page, extracted)

        for li in li_items:
            html = await li.inner_html()
            text = (await li.text_content()).strip()
            if text == selected_dub:
                selected_element = li
                break

        if selected_element:
            await page.evaluate("""
                            (element) => element.click()
                        """, arg=selected_element)
            await asyncio.sleep(1)

        await extract_best_quality_variant(page, extracted)

        if not extracted["all_m3u8"]:
            return None

        return extracted["all_m3u8"][0]  # only best one extracted


async def extract_best_quality_variant(page, extracted):
    print("🔍 Extracting best quality variant (retry up to 5x for 1080p)...")
    attempts = 0
    max_attempts = 5

    while attempts < max_attempts:
        success = await try_click_and_capture_m3u8(page, extracted, "4", "1080p", attempts)
        if success:
            return
        else:
            # fallback to clicking 720p to trigger player change
            await try_click_and_capture_m3u8(page, extracted, "3", "720p", attempts)
        attempts += 1
        await asyncio.sleep(0.5)

    # If still no success after retries, try to get any of 720p or 1080p once more
    for f2id in ["4", "3"]:
        quality = f2id_to_quality.get(f2id)
        if await try_click_and_capture_m3u8(page, extracted, f2id, quality, attempts):
            return

async def try_click_and_capture_m3u8(page, extracted, f2id, quality_label, attempts):
    quality_event = asyncio.Event()
    options_btn = '//*[@id="oframecdnplayer"]/pjsdiv[15]/pjsdiv[3]'
    quality_selector_button = '//*[@id="cdnplayer_settings"]/pjsdiv/pjsdiv[1]'

    await page.evaluate("""
        (xpath) => {
            const el = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
            if (el) el.click();
        }
    """, arg=options_btn)
    await asyncio.sleep(0.3)

    await page.evaluate("""
        (xpath) => {
            const el = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
            if (el) el.click();
        }
    """, arg=quality_selector_button)
    await asyncio.sleep(0.3)

    el = await page.query_selector(f'[f2id="{f2id}"]')
    if not el:
        return False

    await page.evaluate("""
        (f2id) => {
            const el = document.querySelector(`[f2id="${f2id}"]`);
            if (el) el.click();
        }
    """, arg=f2id)
    await asyncio.sleep(0.3)

    async def handle_response(response):
        if response.status == 200 and ".m3u8" in response.url and "manifest" in response.url:
            headers = dict(response.request.headers)
            extracted["all_m3u8"].append({
                "quality": quality_label,
                "url": response.url,
                "headers": headers
            })
            print(f"✅ Found {quality_label}: {response.url}")
            quality_event.set()

    if f2id == '4' or attempts >= 5:
        page.on("response", handle_response)

    try:
        await asyncio.wait_for(quality_event.wait(), timeout=6)
        if f2id == '4' or attempts >= 5:
            page.remove_listener("response", handle_response)
        return True
    except asyncio.TimeoutError:
        if f2id == '4' or attempts >= 5:
            page.remove_listener("response", handle_response)
        return False

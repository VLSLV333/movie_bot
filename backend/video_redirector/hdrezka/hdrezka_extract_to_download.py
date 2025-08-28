import asyncio
import json
import re
import logging
from camoufox.async_api import AsyncCamoufox
from backend.video_redirector.exceptions import TrailerOnlyContentError

f2id_to_quality = {
    "3": "720p",
    "4": "1080p",
}

logger = logging.getLogger(__name__)

def normalize(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text).strip().lower()

async def extract_to_download_from_hdrezka(url: str, selected_dub: str, lang: str) -> dict:
    async with AsyncCamoufox(window=(1280, 720), humanize=True, headless=True) as browser:
        page = await browser.new_page()
        # Navigation logging for visibility
        page.on("framenavigated", lambda frame: logger.debug(f"Frame navigated: {frame.url}"))

        await page.goto(url, wait_until="domcontentloaded")
        # Early detection: trailer-only if YouTube embed present and no translators list
        try:
            trailer_iframe_srcs = await page.evaluate("""
                () => Array.from(document.querySelectorAll('iframe, embed'))
                         .map(n => (n.getAttribute('src')||'') + ' ' + (n.getAttribute('data-src')||''))
            """)
            trailer_iframe_srcs = trailer_iframe_srcs or []
            has_youtube = any(
                ('youtube.com/embed' in s) or ('youtu.be' in s) or ('youtube-nocookie.com' in s)
                for s in trailer_iframe_srcs
            )
            translators_count = await page.evaluate("""
                () => (document.querySelectorAll('#translators-list li, #translators-list a')||[]).length
            """)
            if has_youtube and (not translators_count or translators_count == 0):
                logger.info("⛔ Detected YouTube embed with no translators list — trailer-only page (download)")
                raise TrailerOnlyContentError("Trailer-only content: movie not found")
        except TrailerOnlyContentError:
            raise
        except Exception as e:
            logger.debug(f"Trailer-only detection (download) skipped due to error: {e}")
        # Slightly longer waits to ensure DOM readiness for translators/controls
        try:
            await page.wait_for_selector("#translators-list", timeout=3000)  # type: ignore
        except Exception:
            # Not fatal; continue with a small delay
            pass
        await asyncio.sleep(1)

        extracted = {"all_m3u8": []}

        li_items = await page.query_selector_all("#translators-list li")
        selected_element = None

        if not li_items:
            li_items = await page.query_selector_all("#translators-list a")

        # Filter li_items based on user language preference
        if li_items and lang:
            filtered_items = []
            for item in li_items:
                html_content = await item.inner_html() or ""
                text_content = await item.text_content() or ""
                
                # For Ukrainian users: keep Ukrainian, Original, or Оригинал
                if lang == "uk":
                    if any(keyword in html_content or keyword in text_content 
                           for keyword in ["Украинский", "Оригинал", "Original"]):
                        filtered_items.append(item)
                
                # For Russian users: filter out Ukrainian
                elif lang == "ru":
                    if "Украинский" not in html_content and "Украинский" not in text_content:
                        filtered_items.append(item)
                
                # For other languages: keep all items
                else:
                    filtered_items.append(item)
            
            li_items = filtered_items

        if not li_items:
            await extract_best_quality_variant(page, extracted)
            # Early return as soon as we have a playable master, to start merge sooner
            if extracted["all_m3u8"]:
                return extracted["all_m3u8"][0]

        normalized_selected = normalize(selected_dub)
        normalized_li_texts = [(li, normalize(await li.text_content() or "")) for li in li_items]

        for li, text in normalized_li_texts:
            if text == normalized_selected:
                selected_element = li
                break

        if not selected_element:
            for li, text in normalized_li_texts:
                if normalized_selected in text:
                    logger.info(f"⚠️ Fallback dub match triggered for: {normalized_selected}")
                    selected_element = li
                    break

        if selected_element:
            try:
                await page.evaluate(
                    """
                            (element) => element.click()
                        """,
                    arg=selected_element,
                )
            except Exception as e:
                # Safe single retry if navigation destroyed context
                if "Execution context was destroyed" in str(e):
                    await page.wait_for_load_state("domcontentloaded")
                    await asyncio.sleep(0.3)
                    await page.evaluate(
                        """
                            (element) => element.click()
                        """,
                        arg=selected_element,
                    )
            await asyncio.sleep(1)

        await extract_best_quality_variant(page, extracted)
        # Early return if we have already captured a master m3u8
        if extracted["all_m3u8"]:
            return extracted["all_m3u8"][0]

        if not extracted["all_m3u8"]:
            return {}  # Return empty dict instead of None

        return extracted["all_m3u8"][0]  # only best one extracted


async def extract_best_quality_variant(page, extracted):
    logger.debug("🔍 Extracting best quality variant (retry up to 5x for 1080p)...")
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

    try:
        # Click options with one safe retry on navigation
        for _ in range(2):
            try:
                await page.evaluate(
                    """
                        (xpath) => {
                            const el = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                            if (el) el.click();
                        }
                    """,
                    arg=options_btn,
                )
                break
            except Exception as e:
                if "Execution context was destroyed" in str(e):
                    logger.debug("🔁 Options click retried after navigation")
                    await page.wait_for_load_state("domcontentloaded")
                    await asyncio.sleep(0.3)
                    continue
                raise
        await asyncio.sleep(0.3)

        # Click quality selector with one safe retry
        for _ in range(2):
            try:
                await page.evaluate(
                    """
                        (xpath) => {
                            const el = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                            if (el) el.click();
                        }
                    """,
                    arg=quality_selector_button,
                )
                break
            except Exception as e:
                if "Execution context was destroyed" in str(e):
                    logger.debug("🔁 Quality selector click retried after navigation")
                    await page.wait_for_load_state("domcontentloaded")
                    await asyncio.sleep(0.3)
                    continue
                raise
        await asyncio.sleep(0.3)

        # Wait a bit longer for quality items to render
        try:
            await page.wait_for_selector('[f2id]', timeout=3000)  # type: ignore
        except Exception:
            pass

        el = await page.query_selector(f'[f2id="{f2id}"]')
        if not el:
            return False

        # Click specific quality with one safe retry
        for _ in range(2):
            try:
                await page.evaluate(
                    """
                        (f2id) => {
                            const el = document.querySelector(`[f2id="${f2id}"]`);
                            if (el) el.click();
                        }
                    """,
                    arg=f2id,
                )
                break
            except Exception as e:
                if "Execution context was destroyed" in str(e):
                    logger.debug("🔁 Quality item click retried after navigation")
                    await page.wait_for_load_state("domcontentloaded")
                    await asyncio.sleep(0.3)
                    continue
                raise

        await asyncio.sleep(0.3)

        # Define and attach response listener AFTER clicks (original behavior),
        # with a single safe retry if attachment races with navigation.
        async def handle_response(response):
            try:
                if response.status == 200 and ".m3u8" in response.url and "manifest" in response.url:
                    headers = dict(response.request.headers)
                    extracted["all_m3u8"].append({
                        "quality": quality_label,
                        "url": response.url,
                        "headers": headers,
                    })
                    logger.info(f"✅ Found {quality_label}: {response.url}")
                    quality_event.set()
            except Exception:
                # Be tolerant to transient issues during navigation
                pass

        listener_attached = False
        try:
            if f2id == '4' or attempts >= 5:
                try:
                    page.on("response", handle_response)
                    listener_attached = True
                except Exception as e:
                    if "Execution context was destroyed" in str(e) or "closed" in str(e).lower():
                        await page.wait_for_load_state("domcontentloaded")
                        await asyncio.sleep(0.2)
                        page.on("response", handle_response)
                        listener_attached = True
                    else:
                        raise

            await asyncio.wait_for(quality_event.wait(), timeout=8)
            return True
        finally:
            if listener_attached:
                try:
                    page.remove_listener("response", handle_response)
                except Exception:
                    pass
    except asyncio.TimeoutError:
        logger.debug(f"⚠️ Timeout waiting for .m3u8 after clicking {quality_label}")
        return False
    


async def extract_to_download_with_recovery(url: str, selected_dub: str, lang: str) -> dict:
    """Run extraction with recovery for transient navigation/context errors."""
    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            logger.info(f"Starting download extraction attempt {attempt + 1}/{max_attempts}")
            return await extract_to_download_from_hdrezka(url, selected_dub, lang)
        except TrailerOnlyContentError as te:
            # Non-retryable: surface immediately
            logger.error(f"Trailer-only content detected (download): {te}")
            raise
        except Exception as e:
            message = str(e)
            if (
                "Execution context was destroyed" in message
                or "Page closed" in message
                or "Page was closed" in message
            ):
                logger.debug(f"Transient error: {message}. Waiting 2s before retry...")
                await asyncio.sleep(2)
                continue
            # Non-transient or last attempt
            raise
    # Should not reach here
    raise Exception("All extraction attempts failed")

import asyncio
from camoufox.async_api import AsyncCamoufox
from typing import Dict
from backend.video_redirector.utils.redis_client import RedisClient
from urllib.parse import quote
import logging
from backend.video_redirector.exceptions import TrailerOnlyContentError

f2id_to_quality = {
    "1": "360p",
    "2": "480p",
    "3": "720p",
    "4": "1080p",
    "5": "1080pUltra"
}
logger = logging.getLogger(__name__)

async def extract_from_hdrezka(url: str, user_lang: str, task_id: str | None = None) -> Dict:
    final_result = {user_lang: {}}

    async with AsyncCamoufox(window=(1280, 720), humanize=True, headless=True) as browser:
        page = await browser.new_page()
        
        # Add navigation protection
        page.on("framenavigated", lambda frame: logger.info(f"Frame navigated: {frame.url}"))
        
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(0.5)

        # --- Early detection: Trailer-only (YouTube embed) pages ---
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
            # Also consider the UI: if no translators list and YouTube is present, it's likely trailer-only
            translators_count = await page.evaluate("""
                () => (document.querySelectorAll('#translators-list li, #translators-list a')||[]).length
            """)
            if has_youtube and (not translators_count or translators_count == 0):
                logger.info("⛔ Detected YouTube embed with no translators list — trailer-only page")
                raise TrailerOnlyContentError("Trailer-only content: movie not found")
        except TrailerOnlyContentError:
            raise
        except Exception as e:
            # Non-fatal detection failure; continue with normal flow
            logger.debug(f"Trailer-only detection skipped due to error: {e}")

        # --- Step 1: Find matching dubs ---
        dub_elements = await get_matching_dubs(page, user_lang)
        dub_names = [dub_name for dub_name, _ in dub_elements]

        for dub_name in dub_names:
            logger.info(f"\n🎙️ Extracting for dub: {dub_name}")

            dub_result = {"all_m3u8": [], "subtitles": []}

            # Add safety check for page state
            if page.is_closed():
                logger.error("Page was closed during extraction")
                raise Exception("Page closed during extraction - will retry")

            vtt_handler = await start_listening_for_vtt(page, dub_result, task_id)
            
            # Re-query the dub element by name each time with error handling
            li_element = await find_dub_element_by_name(page, dub_name, user_lang)
            if li_element:
                # Try primary click method with retry
                primary_click_success = False
                for attempt in range(3):
                    try:
                        await li_element.evaluate("(el) => el.click()")
                        await asyncio.sleep(1)
                        primary_click_success = True
                        break
                    except Exception as e:
                        logger.warning(f"⚠️ Primary dub click attempt {attempt + 1} failed for '{dub_name}': {e}")
                        if attempt < 2:
                            await asyncio.sleep(0.5)
                
                # If primary method failed, try alternative click method with retry
                if not primary_click_success:
                    alternative_click_success = False
                    for attempt in range(3):
                        try:
                            await page.evaluate("""
                                (dubName) => {
                                    const elements = document.querySelectorAll('#translators-list li, #translators-list a');
                                    for (let el of elements) {
                                        if (el.textContent.trim() === dubName) {
                                            el.click();
                                            return true;
                                        }
                                    }
                                    return false;
                                }
                            """, arg=dub_name)
                            await asyncio.sleep(1.5)
                            alternative_click_success = True
                            break
                        except Exception as e2:
                            logger.warning(f"⚠️ Alternative dub click attempt {attempt + 1} failed for '{dub_name}': {e2}")
                            if attempt < 2:
                                await asyncio.sleep(0.5)
                    
                    if not alternative_click_success:
                        logger.error(f"⚠️ All dub click attempts failed for '{dub_name}'")

            await extract_all_quality_variants(page, dub_result)
            # Remove the VTT listener before extracting subtitles
            page.remove_listener("response", vtt_handler)
            if task_id:
                await extract_subtitles_if_available(page, dub_result, task_id=task_id, dub_name=dub_name)

            final_result[user_lang][dub_name] = dub_result

        return final_result

async def extract_with_recovery(url: str, user_lang: str, task_id: str | None = None) -> Dict:
    """Extract with browser context recovery - 5 max attempts"""
    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            logger.info(f"Starting extraction attempt {attempt + 1}/{max_attempts}")
            return await extract_from_hdrezka(url, user_lang, task_id)
        except TrailerOnlyContentError as te:
            # Non-retryable: surface immediately
            logger.error(f"Trailer-only content detected: {te}")
            raise
        except Exception as e:
            logger.error(f"Extraction attempt {attempt + 1} failed: {e}")
            if attempt < max_attempts - 1:
                wait_time = 2 ** attempt  # Exponential backoff: 1, 2, 4, 8 seconds
                logger.info(f"Waiting {wait_time} seconds before retry...")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"All {max_attempts} extraction attempts failed")
                # Raise exception to maintain compatibility with existing logic
                raise Exception(f"All {max_attempts} extraction attempts failed")
    # This line should never be reached, but linter needs it
    raise Exception("Unexpected end of extraction attempts")

async def get_matching_dubs(page, user_lang: str):
    matching = []
    li_items = await page.query_selector_all("#translators-list li")

    if not li_items:
        li_items = await page.query_selector_all("#translators-list a")

    # ✅ Handle NO dubs present at all
    if not li_items:
        logger.info("⚠️ No dubs listed. Assuming single dub mode.")
        return [("🎧 Default Dub", None)]

    for li in li_items:
        html = await li.inner_html()
        text = await li.text_content()

        if user_lang == "uk" and ("Украинский" in html or "Оригинал" in html or "Original" in html):
            logger.info(li)
            matching.append((text.strip(), li))

        elif user_lang == "en" and ("Оригинал" in html or "Original" in html):
            return [(text.strip(), li)]  # EN returns only one

        elif user_lang == "ru":
            if "Украинский" in html:
                continue
            if "Оригинал" in html or "Original" in html:
                matching.append((text.strip(), li))
            if "HDrezka" in html or "Дубляж" in html:
                matching.append((text.strip(), li))
            elif any(x in html.lower() for x in ["лостфильм", "колдфильм", "tvshows"]):
                matching.append((text.strip(), li))

    # fallback: just first dub provided
    if not matching:
        for li in li_items:
            html = await li.inner_html()
            text = await li.text_content()
            return [(text.strip(), li)]

    # Additional logic for 'uk' users: if only 'Оригинал' or 'Original' is present, add fallbackAdd commentMore actions
    if user_lang == "uk" and len(matching) == 1:
        dub_name = matching[0][0].lower()
        if "оригинал" in dub_name or "original" in dub_name:
            # Add fallback: just first dub provided
            html = await li_items[0].inner_html()
            text = await li_items[0].text_content()
            matching.append((text.strip(), li_items[0]))

    return matching

async def select_preferred_dub(page, user_lang: str):
    li_items = await page.query_selector_all("#translators-list li")

    for li in li_items:
        html = await li.inner_html()
        if user_lang == "uk" and "Украинский" in html:
            await li.evaluate("(el) => el.click()")
            return
        elif user_lang == "en" and "Оригинал" in html:
            await li.evaluate("(el) => el.click()")
            return
        elif user_lang == "ru" and "Дубляж" in html:
            await li.evaluate("(el) => el.click()")
            return

    logger.info("⚠️ No matching dub found for user_lang. Using default active.")


async def start_listening_for_vtt(page, extracted: Dict, task_id):
    largest_vtt = {"size": 0, "url": None}
    
    async def handle_vtt_response(response):
        if not response.url.endswith(".vtt"):
            return
        content_length = response.headers.get("content-length")
        size = int(content_length) if content_length is not None else 0
        url = response.url
        if size > largest_vtt["size"]:
            largest_vtt["size"] = size
            largest_vtt["url"] = url
            proxy_url = f"/hd/subs/{task_id}.vtt"
            logger.info(f"[🎯] Found larger subtitle VTT (initial): {url} (size: {size})")

            # Save to Redis so fallback route can find it
            redis = RedisClient.get_client()
            await redis.set(f"subs:{task_id}:fallback", url, ex=86400)

            # Replace or add the subtitle in extracted["subtitles"]
            if extracted["subtitles"]:
                extracted["subtitles"][0]["url"] = proxy_url
                extracted["subtitles"][0]["lang"] = "Unknown"
            else:
                extracted["subtitles"].append({
                    "url": proxy_url,
                    "lang": "Unknown"
                })
        else:
            logger.info(f"[🎯] Skipped smaller subtitle VTT (size: {size})")

    page.on("response", handle_vtt_response)
    return handle_vtt_response


async def extract_subtitles_if_available(page, extracted: Dict, task_id: str,dub_name: str):
    # Step 1: Check if subtitles are even shown in UI
    has_subs = await page.evaluate("""
            () => {
                const el = document.querySelector("#cdnplayer_control_cc");
                return el && el.style.display === "block";
            }
        """)

    if not has_subs:
        logger.info("⛔ No subtitles available for selected dub")
        return

    logger.info("🟡 Subtitles detected")

    # Step 2: Click the subtitles menu (CC button)
    try:
        await page.evaluate("""
            (xpath) => {
                const el = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                if (el) el.click();
            }
        """, arg='//*[@id="cdnplayer_control_cc"]/pjsdiv[3]')
        logger.info("✅ Forced subtitle button click via JS")
    except Exception as e:
        logger.error(f"⚠️ Subtitle button failed to become interactable: {e}")
        return

    # Step 3: Setup shared subtitle event listener
    subtitle_state = {"current_lang": None}
    vtt_event = asyncio.Event()

    async def handle_vtt_response(response):
        if response.url.endswith(".vtt") and subtitle_state["current_lang"] and response.status == 200:
            real_url = response.url
            lang_code = subtitle_state["current_lang"]
            proxy_url = f"/hd/subs/{task_id}/{quote(dub_name)}/{quote(lang_code)}.vtt"

            # Save to Redis
            redis = RedisClient.get_client()
            await redis.set(f"subs:{task_id}:{quote(dub_name)}:{quote(lang_code)}", real_url, ex=86400)

            extracted["subtitles"].append({
                "url": proxy_url,
                "lang": lang_code
            })

            logger.info(f"[🎯] Captured subtitle {subtitle_state['current_lang']} → {response.url}")
            subtitle_state["current_lang"] = None
            vtt_event.set()

    page.on("response", handle_vtt_response)

    subtitle_items = await page.query_selector_all("[f2id]")

    index_of_already_catched_subs = None

    #Step 4: Check if any subtitle is already selected (highlighted with special SVG)
    for idx, item in enumerate(subtitle_items):
        index_of_already_catched_subs = idx
        highlight = await item.query_selector('pjsdiv svg')
        if highlight:
            lang = await page.evaluate('''
                        (el) => {
                            const labelDivs = el.querySelectorAll('pjsdiv');
                            for (let div of labelDivs) {
                                const style = getComputedStyle(div);
                                if (style.float === 'left') {
                                    return div.textContent.trim();
                                }
                            }
                            return el.textContent.trim();
                        }
                    ''', arg=item)
            logger.info(f"🟢 Already active subtitle detected: {lang}")
            if extracted["subtitles"]:
                extracted["subtitles"][0]["lang"] = lang
                extracted["subtitles"][0]["url"] = f"/hd/subs/{task_id}/{quote(dub_name)}/{quote(lang)}.vtt"
                redis = RedisClient.get_client()
                fallback_url = await redis.get(f"subs:{task_id}:fallback")
                if fallback_url:
                    await redis.set(f"subs:{task_id}:{quote(dub_name)}:{quote(lang)}", fallback_url, ex=86400)
                logger.info(f"resaved first captured vtt with new key in redis")
            break

    # Step 5: Iterate through subtitle options (skip first & last)
    for idx in range(1, len(subtitle_items) - 1):
        # if currently selected subs is first in list we need to close mini menu and skip this iteration
        if index_of_already_catched_subs == 1 and index_of_already_catched_subs == idx:
            await page.evaluate("""
                                    (xpath) => {
                                        const el = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                                        if (el) el.click();
                                    }
                                """, arg='//*[@id="cdnplayer_control_cc"]/pjsdiv[3]')
            await asyncio.sleep(1)
            continue

        # Reopen subtitle menu before each click, except first iteration when it is already opened
        if idx != 1:
            await page.evaluate("""
                (xpath) => {
                    const el = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                    if (el) el.click();
                }
            """, arg='//*[@id="cdnplayer_control_cc"]/pjsdiv[3]')
            await asyncio.sleep(1)

        subtitle_items = await page.query_selector_all("[f2id]")
        fresh_item = subtitle_items[idx]
        f2id_val = await fresh_item.get_attribute("f2id")

        # Extract language label safely
        lang = await fresh_item.text_content()
        subtitle_state["current_lang"] = lang
        vtt_event.clear()

        # Click subtitle
        await page.evaluate(
            """
            (f2id) => {
                const el = document.querySelector(`[f2id="${f2id}"]`);
                if (el) el.click();
            }
            """,
            arg=f2id_val
        )
        logger.info(f"🔍 Clicked subtitle option f2id={f2id_val} ({lang})")

        try:
            await asyncio.wait_for(vtt_event.wait(), timeout=10)
        except asyncio.TimeoutError:
            logger.info(f"⚠️ No .vtt received for subtitle: {lang}")

        await asyncio.sleep(0.3)


async def extract_all_quality_variants(page, extracted: Dict):
    logger.info("📥 Extracting all quality variants...")

    quality_button_xpath = '//*[@id="oframecdnplayer"]/pjsdiv[15]/pjsdiv[3]'
    f2id_list = ["1", "2", "3", "4", "5"]

    async def click_xpath(xpath: str):
        try:
            await page.evaluate("""
                (xpath) => {
                    const el = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                    if (el) el.click();
                }
            """, arg=xpath)
        except Exception as e:
            logger.warning(f"Failed to click xpath {xpath}: {e}")
            return False
        return True

    quality_state = {"current": None}
    quality_event = asyncio.Event()

    async def try_f2id(f2idx: str):
        quality_label = f2id_to_quality.get(f2idx)
        quality_state["current"] = quality_label
        quality_event.clear()

        # Add page state check
        if page.is_closed():
            logger.error("Page closed during quality extraction")
            return False

        # Click quality button with retry
        for attempt in range(3):
            if await click_xpath(quality_button_xpath):
                break
            await asyncio.sleep(0.5)
        else:
            logger.error(f"Failed to click quality button after 3 attempts")

        await asyncio.sleep(0.5)

        # Click settings button with retry
        for attempt in range(3):
            try:
                await page.evaluate("""() => {
                    const btn = document.querySelector('[fid="1"]');
                    if (btn) btn.click();
                }""")
                break
            except Exception as e:
                logger.warning(f"Settings button click attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(0.5)
        else:
            logger.error("Failed to click settings button")

        await asyncio.sleep(0.5)

        # Check if element exists with retry
        el = None
        for attempt in range(3):
            try:
                el = await page.query_selector(f'[f2id="{f2idx}"]')
                if el:
                    break
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.warning(f"Element query attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(0.3)
        
        if not el:
            logger.info(f"❌ Element for f2id={f2idx} not found after retries")
            return False

        # Click quality button with error handling
        for attempt in range(3):
            try:
                await page.evaluate("""(f2idx) => {
                    const el = document.querySelector(`[f2id="${f2idx}"]`);
                    if (el) el.click();
                }""", arg=f2idx)
                break
            except Exception as e:
                logger.warning(f"Quality button click attempt {attempt + 1} failed: {e}")
                if attempt < 2:
                    await asyncio.sleep(0.5)
                else:
                    logger.error(f"Failed to click quality f2id={f2idx} after 3 attempts")

        logger.info(f"[🔁] Clicked quality option f2id={f2idx} ({quality_label})")

        # Attach listener only AFTER click
        async def handle_response(response):
            url = response.url
            if (
                    response.status == 200
                    and ".m3u8" in url
                    and "manifest" in url
                    and quality_state["current"]
            ):
                headers = dict(response.request.headers)
                m3u8_data = {
                    "quality": quality_state["current"],
                    "url": url,
                    "headers": headers,
                    "referer": headers.get("referer")
                }
                if m3u8_data not in extracted["all_m3u8"]:
                    extracted["all_m3u8"].append(m3u8_data)
                    logger.info(f"[🎥] {quality_state['current']} → {url}")
                    quality_event.set()

        page.on("response", handle_response)

        try:
            await asyncio.wait_for(quality_event.wait(), timeout=5)
            page.remove_listener("response", handle_response)
            return True
        except asyncio.TimeoutError:
            logger.info(f"⚠️ Timeout waiting for .m3u8 after clicking {quality_label}")
            page.remove_listener("response", handle_response)
            return False

    MAX_RETRIES = 3
    retry_count = 0
    missing_set = set(f2id_list)

    while missing_set and retry_count < MAX_RETRIES:
        logger.info(f"🔁 Retry pass #{retry_count + 1} for missing qualities: {sorted(missing_set)}")
        current_missing = set()

        for f2id in sorted(missing_set):
            # Add page state check before each attempt
            if page.is_closed():
                logger.error("Page closed during retry loop")
                raise Exception("Page closed during extraction - will retry")

            # Reset state if only 1 retry left
            if len(missing_set) == 1:
                for alt in f2id_list:
                    if alt != f2id:
                        logger.info(f"🔄 Resetting player by clicking alt f2id={alt} before retrying f2id={f2id}")
                        await try_f2id(alt)  # Ignore result
                        break

            success = await try_f2id(f2id)
            if not success:
                current_missing.add(f2id)

        missing_set = current_missing
        retry_count += 1

    if missing_set:
        logger.info(f"❌ Failed to extract the following qualities after {MAX_RETRIES} retries: {sorted(missing_set)}")

    quality_state["current"] = None


async def find_dub_element_by_name(page, dub_name, lang):
    li_items = await page.query_selector_all("#translators-list li")
    if not li_items:
        li_items = await page.query_selector_all("#translators-list a")
    
    # First, try to find exact match with language filtering
    for li in li_items:
        text = await li.text_content()
        if text and text.strip() == dub_name:
            html_content = await li.inner_html() or ""
            text_content = await li.text_content() or ""

            # For Ukrainian users: prefer Ukrainian, Original, or Оригинал
            if lang == "uk":
                if any(keyword in html_content or keyword in text_content
                       for keyword in ["Украинский", "Оригинал", "Original"]):
                    return li
            # For Russian users: filter out Ukrainian
            elif lang == "ru":
                if "Украинский" not in html_content and "Украинский" not in text_content:
                    return li
            # For other languages: accept all items
            else:
                return li
    
    # If no exact match with language filtering, try to find any element with the same name
    for li in li_items:
        text = await li.text_content()
        if text and text.strip() == dub_name:
            return li
    return None

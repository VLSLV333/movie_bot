import asyncio
from camoufox.async_api import AsyncCamoufox
from typing import Dict, List
from backend.video_redirector.utils.redis_client import RedisClient
from urllib.parse import quote

f2id_to_quality = {
    "1": "360p",
    "2": "480p",
    "3": "720p",
    "4": "1080p",
    "5": "1080pUltra"
}

async def extract_from_hdrezka(url: str, user_lang: str = "ua", task_id: str = None) -> Dict:
    final_result = {user_lang: {}}

    async with AsyncCamoufox(window=(1280, 720), humanize=True, headless=True) as browser:
        page = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(0.5)

        # --- Step 1: Find matching dubs ---
        dub_elements = await get_matching_dubs(page, user_lang)

        for dub_name, li_element in dub_elements:
            print(f"\n🎙️ Extracting for dub: {dub_name}")
            if li_element:
                await li_element.click()
                await asyncio.sleep(1)

            dub_result = {"all_m3u8": [], "subtitles": []}

            await start_listening_for_vtt(page, dub_result,task_id)
            await extract_all_quality_variants(page, dub_result)
            await extract_subtitles_if_available(page, dub_result,task_id=task_id,dub_name=dub_name)

            final_result[user_lang][dub_name] = dub_result

        return final_result

async def get_matching_dubs(page, user_lang: str):
    matching = []
    li_items = await page.query_selector_all("#translators-list li")

    # ✅ Handle NO dubs present at all
    if not li_items:
        print("⚠️ No dubs listed. Assuming single dub mode.")
        return [("🎧 Default Dub (no selector)", None)]

    for li in li_items:
        html = await li.inner_html()
        text = await li.text_content()

        if user_lang == "ua" and "Украинский" in html:
            matching.append((text.strip(), li))

        elif user_lang == "en" and ("Оригинал" in html or "Original" in html):
            return [(text.strip(), li)]  # EN returns only one

        elif user_lang == "ru":
            if "Украинский" in html:
                continue
            if "HDrezka" in html or "Дубляж" in html:
                matching.append((text.strip(), li))
            elif any(x in html.lower() for x in ["лостфильм", "колдфильм", "tvshows"]):
                matching.append((text.strip(), li))

    # fallback: just first dub provided
    if not matching :
        for li in li_items:
            html = await li.inner_html()
            text = await li.text_content()
            return [(text.strip(), li)]

    return matching

async def select_preferred_dub(page, user_lang: str):
    li_items = await page.query_selector_all("#translators-list li")

    for li in li_items:
        html = await li.inner_html()
        if user_lang == "ua" and "Украинский" in html:
            await li.click()
            return
        elif user_lang == "en" and "Оригинал" in html:
            await li.click()
            return
        elif user_lang == "ru" and "Дубляж" in html:
            await li.click()
            return

    print("⚠️ No matching dub found for user_lang. Using default active.")


async def start_listening_for_vtt(page, extracted: Dict,task_id):
    vtt_captured = False
    async def handle_vtt_response(response):
        nonlocal vtt_captured
        if vtt_captured:
            return
        url = response.url
        if url.endswith(".vtt"):
            proxy_url = f"/hd/subs/{task_id}.vtt"
            print(f"[🎯] Found subtitle VTT (initial): {url}")

            # ✅ Save to Redis so fallback route can find it
            redis = RedisClient.get_client()
            await redis.set(f"subs:{task_id}:fallback", url, ex=3600)

            extracted["subtitles"].append({
                "url": proxy_url,
                "lang": "Unknown"
            })
            vtt_captured = True

    page.on("response", handle_vtt_response)


async def extract_subtitles_if_available(page, extracted: Dict, task_id: str,dub_name: str):
    # Step 1: Check if subtitles are even shown in UI
    has_subs = await page.evaluate("""
            () => {
                const el = document.querySelector("#cdnplayer_control_cc");
                return el && el.style.display === "block";
            }
        """)

    if not has_subs:
        print("⛔ No subtitles available for selected dub")
        return

    print("🟡 Subtitles detected")

    # Step 2: Click the subtitles menu (CC button)
    try:
        await page.evaluate("""
            (xpath) => {
                const el = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                if (el) el.click();
            }
        """, arg='//*[@id="cdnplayer_control_cc"]/pjsdiv[3]')
        print("✅ Forced subtitle button click via JS")
    except Exception as e:
        print(f"⚠️ Subtitle button failed to become interactable: {e}")
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
            await redis.set(f"subs:{task_id}:{quote(dub_name)}:{quote(lang_code)}", real_url, ex=3600)

            extracted["subtitles"].append({
                "url": proxy_url,
                "lang": lang_code
            })

            print(f"[🎯] Captured subtitle {subtitle_state['current_lang']} → {response.url}")
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
            print(f"🟢 Already active subtitle detected: {lang}")
            if extracted["subtitles"]:
                extracted["subtitles"][0]["lang"] = lang
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
        print(f"🔍 Clicked subtitle option f2id={f2id_val} ({lang})")

        try:
            await asyncio.wait_for(vtt_event.wait(), timeout=10)
        except asyncio.TimeoutError:
            print(f"⚠️ No .vtt received for subtitle: {lang}")

        await asyncio.sleep(0.3)


async def extract_all_quality_variants(page, extracted: Dict):
    print("📥 Extracting all quality variants...")

    quality_button_xpath = '//*[@id="oframecdnplayer"]/pjsdiv[15]/pjsdiv[3]'
    f2id_list = ["1", "2", "3", "4", "5"]

    async def click_xpath(xpath: str):
        await page.evaluate("""
            (xpath) => {
                const el = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                if (el) el.click();
            }
        """, arg=xpath)

    quality_state = {"current": None}
    quality_event = asyncio.Event()

    async def try_f2id(f2idx: str):
        quality_label = f2id_to_quality.get(f2idx)
        quality_state["current"] = quality_label
        quality_event.clear()

        await click_xpath(quality_button_xpath)
        await asyncio.sleep(0.3)

        await page.evaluate("""() => {
            const btn = document.querySelector('[fid="1"]');
            if (btn) btn.click();
        }""")
        await asyncio.sleep(0.3)

        el = await page.query_selector(f'[f2id="{f2idx}"]')
        if not el:
            print(f"❌ Element for f2id={f2idx} not found")
            return False

        # Click quality button first
        await page.evaluate("""(f2idx) => {
            const el = document.querySelector(`[f2id="${f2idx}"]`);
            if (el) el.click();
        }""", arg=f2idx)

        print(f"[🔁] Clicked quality option f2id={f2idx} ({quality_label})")

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
                    print(f"[🎥] {quality_state['current']} → {url}")
                    quality_event.set()

        page.on("response", handle_response)

        try:
            await asyncio.wait_for(quality_event.wait(), timeout=5)
            page.remove_listener("response", handle_response)
            return True
        except asyncio.TimeoutError:
            print(f"⚠️ Timeout waiting for .m3u8 after clicking {quality_label}")
            page.remove_listener("response", handle_response)
            return False

    MAX_RETRIES = 3
    retry_count = 0
    missing_set = set(f2id_list)

    while missing_set and retry_count < MAX_RETRIES:
        print(f"🔁 Retry pass #{retry_count + 1} for missing qualities: {sorted(missing_set)}")
        current_missing = set()

        for f2id in sorted(missing_set):
            # Reset state if only 1 retry left
            if len(missing_set) == 1:
                for alt in f2id_list:
                    if alt != f2id:
                        print(f"🔄 Resetting player by clicking alt f2id={alt} before retrying f2id={f2id}")
                        await try_f2id(alt)  # Ignore result
                        break

            success = await try_f2id(f2id)
            if not success:
                current_missing.add(f2id)

        missing_set = current_missing
        retry_count += 1

    if missing_set:
        print(f"❌ Failed to extract the following qualities after {MAX_RETRIES} retries: {sorted(missing_set)}")

    quality_state["current"] = None

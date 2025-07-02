import aiohttp
from bs4 import BeautifulSoup
import re
from typing import Dict, List, Optional, Union

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Referer": "https://hdrezka.ag/",
    "Origin": "https://hdrezka.ag",
    "Connection": "keep-alive",
}

async def scrape_dubs_for_movie(movie_url: str, lang: str) -> Dict[str, Union[List[str], bool, Optional[str]]]:
    """
    Extracts dub names based on user language rules.
    - html: raw HTML from the movie page
    - lang: 'uk', 'ru', or 'en'
    Returns: list of filtered dub names "['Украинский одноголосый', 'Украинский (Sweet)', 'Цікава Ідея', 'Sunnysiders', 'Колодій Трейлерів', 'Оригинал (+субтитры)']"
    """
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(movie_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
            html = await response.text()

    soup = BeautifulSoup(html , "html.parser")
    dub_elements = soup.select("#translators-list .b-translator__item")

    # Note: 'default_ru' is used when no dub list is found. It refers to the single default voiceover (typically RU).
    if not dub_elements:
        if lang in ("uk", "ru"):
            return {
                "dubs": ["default_ru"],
                "fallback": True,
                "message": "🥲 Only 1 dub found"
            }
        else:
            return {
                "dubs": [],
                "fallback": True,
                "message": "🥲 No available dubs found for this language."
            }

    dubs = []
    for el in dub_elements:
        dub_text = el.get_text()
        dub_html = str(el)

        is_ukrainian = "Украинский" in dub_html
        is_original = bool(re.search(r"Оригинал|Original", dub_html, re.IGNORECASE))

        if lang == "uk":
            if is_ukrainian or is_original:
                dubs.append(dub_text)
        elif lang == "ru":
            if not is_ukrainian or is_original:
                dubs.append(dub_text)
        elif lang == "en":
            if is_original:
                dubs.append(dub_text)

    # Remove duplicates
    dubs = list(dict.fromkeys(dubs))

    # Fallback: if lang=uk but no Ukrainian dubs found, include RU + Original + a flag
    if lang == "uk" and all(("Оригинал" in dub or "Original" in dub) for dub in dubs):
        fallback_dubs = []
        for el in dub_elements:
            dub_text = el.get_text(strip=True)
            fallback_dubs.append(dub_text)
        fallback_dubs = list(dict.fromkeys(fallback_dubs))
        return {
            "dubs": fallback_dubs,
            "fallback": True,
            "message": "🎙️ Sorry, no Ukrainian dubs available for this movie."
        }

    # Normal UK case
    return {
        "dubs": dubs,
        "fallback": False,
        "message": None
    }
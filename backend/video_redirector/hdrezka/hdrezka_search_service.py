from aiohttp import ClientSession
from parsel import Selector
from urllib.parse import quote

async def search_hdrezka(query: str) -> list[dict]:
    """
    Search HDRezka and return top 10 results with title, poster, and detail page url.
    """
    encoded_query = quote(query)
    url = f"https://hdrezka.ag/search/?do=search&subaction=search&q={encoded_query}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Origin": "https://hdrezka.ag",
        "Referer": "https://hdrezka.ag/",
        "Connection": "keep-alive"
    }

    async with ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            html = await resp.text()

    sel = Selector(text=html)

    results = []

    for item in sel.css("div.b-content__inline_item")[:10]:
        title = item.css("div.b-content__inline_item-link a::text").get(default='').strip()
        url = item.css("div.b-content__inline_item-link a::attr(href)").get(default='').strip()
        poster = item.css("div.b-content__inline_item-cover img::attr(src)").get(default='').strip()

        if title and url and poster:
            results.append({
                "title": title,
                "poster": poster,
                "url": url
            })

    return results

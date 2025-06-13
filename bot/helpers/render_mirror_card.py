import re
import json

from bot.utils.redis_client import RedisClient
from aiogram import types
from typing import Tuple, Optional, List
from bot.utils.logger import Logger

DEFAULT_POSTER_FILE_ID = "AgACAgIAAxkBAAICNGf7lNhs16ESonKa5G8X-Nl7LV7gAAJv8jEbd87hS9GxbYmnDY9ZAQADAgADeQADNgQ"
logger = Logger().get_logger()

def render_mirror_card(result: dict) -> Tuple[str, types.InlineKeyboardMarkup, Optional[str]]:
    """
    Renders a mirror movie result into a Telegram card.
    Expects structure: { "title": ..., "poster": ..., "url": ... }
    """
    title = result.get("title", "Awesome title 🫡").strip()
    poster = result.get("poster") or None
    stream_id = result.get("id") or result.get("url")

    if not poster or not isinstance(poster, str) or not poster.startswith("http"):
        logger.warning(f"[MirrorCard] Missing or invalid poster. Falling back to default.")
        poster = DEFAULT_POSTER_FILE_ID

    # Strip any <b> tags from the titlex
    clean_title = re.sub(r"</?b>", "", title)

    # Wrap clean title in bold
    text = f"<b>{clean_title}</b>"

    buttons = [
        [types.InlineKeyboardButton(text="▶️ Watch", callback_data=f"watch_mirror:{stream_id}")],
        [types.InlineKeyboardButton(text="💾 Download", callback_data=f"download_mirror:{stream_id}")]
    ]

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    return text, keyboard, poster

async def   render_mirror_card_batch(results: list[dict],tmdb_id) -> list[Tuple[str, types.InlineKeyboardMarkup, Optional[str]]]:
    redis = RedisClient.get_client()
    rendered = []

    for result in results:
        stream_id = result.get("id")
        stream_url = result.get("url")

        if stream_id and stream_url:
            try:
                await redis.set(f"mirror_url:{stream_id}", json.dumps({
                    "url": result["url"],
                    "tmdb_id": tmdb_id,  # <-- pass this in from higher context
                    "title": result.get("title", "Awesome title 🫡").strip()
                }), ex=3600) # 1 hour TTL
            except Exception as e:
                logger.warning(f"[MirrorCard] Failed to cache URL for {stream_id}: {e}")

        rendered.append(render_mirror_card(result))

    return rendered

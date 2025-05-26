from aiogram import types
from typing import Tuple, Optional

DEFAULT_POSTER_FILE_ID = "AgACAgIAAxkBAAICNGf7lNhs16ESonKa5G8X-Nl7LV7gAAJv8jEbd87hS9GxbYmnDY9ZAQADAgADeQADNgQ"

def render_mirror_card(result: dict) -> Tuple[str, types.InlineKeyboardMarkup, Optional[str]]:
    """
    Renders a mirror movie result into a Telegram card.
    Expects structure: { "title": ..., "poster": ..., "url": ... }
    """
    title = result.get("title", "Awesome title 🫡").strip()
    poster = result.get("poster") or None
    stream_url = result.get("url")

    if not poster or not isinstance(poster, str) or not poster.startswith("http"):
        poster = DEFAULT_POSTER_FILE_ID

    text = f"<b>{title}</b>"

    buttons = [
        [
            types.InlineKeyboardButton(text="▶️ Watch", callback_data=f"watch_mirror:{stream_url}"),
            types.InlineKeyboardButton(text="💾 Download", callback_data=f"download_mirror:{stream_url}")
        ]
    ]

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    return text, keyboard, poster

async def render_mirror_card_batch(results: list[dict]) -> list[Tuple[str, types.InlineKeyboardMarkup, Optional[str]]]:
    return [render_mirror_card(result) for result in results]

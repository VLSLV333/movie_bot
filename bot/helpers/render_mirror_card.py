import re
import json
from aiogram.utils.i18n import gettext
from bot.utils.redis_client import RedisClient
from aiogram import types
from typing import Tuple, Optional
from bot.utils.logger import Logger
from bot.locales.keys import (
    LANG_ENGLISH, LANG_UKRAINIAN, LANG_RUSSIAN,
    WATCH_MOVIE, DOWNLOAD_MOVIE, CHANGE_LANGUAGE_BTN, 
    WRONG_MOVIE_BTN, PREFERRED_LANGUAGE_TO_WATCH
)

DEFAULT_POSTER_FILE_ID = "AgACAgIAAxkBAAICNGf7lNhs16ESonKa5G8X-Nl7LV7gAAJv8jEbd87hS9GxbYmnDY9ZAQADAgADeQADNgQ"
logger = Logger().get_logger()

def get_language_display_name(lang_code: str) -> str:
    """
    Convert language code to user-friendly display name with flag.
    
    Args:
        lang_code: Language code (e.g., "uk", "en", "ru")

    Returns:
        User-friendly language name with flag (e.g., "🇺🇦 Ukrainian", "🇺🇸 English")
    """
    lang_keys = {
        "uk": LANG_UKRAINIAN,
        "en": LANG_ENGLISH, 
        "ru": LANG_RUSSIAN
    }
    
    if lang_code.lower() in lang_keys:
        return gettext(lang_keys[lang_code.lower()])
    
    # Fallback for unsupported languages
    fallback_names = {
        "es": "🇪🇸 Spanish",
        "fr": "🇫🇷 French",
        "de": "🇩🇪 German",
        "it": "🇮🇹 Italian",
        "pt": "🇧🇷 Portuguese",
        "pl": "🇵🇱 Polish",
        "tr": "🇹🇷 Turkish",
        "ar": "🇸🇦 Arabic",
        "hi": "🇮🇳 Hindi",
        "ja": "🇯🇵 Japanese",
        "ko": "🇰🇷 Korean",
        "zh": "🇨🇳 Chinese"
    }
    
    return fallback_names.get(lang_code.lower(), f"🌍 {lang_code.upper()}")

def get_mirror_language_selection_keyboard() -> types.InlineKeyboardMarkup:
    """
    Create keyboard for language selection in mirror context.
    Shows only the 3 main supported languages.
    """
    lang_keys = {
        "uk": LANG_UKRAINIAN,
        "en": LANG_ENGLISH, 
        "ru": LANG_RUSSIAN
    }
    
    keyboard = []
    
    # Add all three languages
    for lang_code, lang_key in lang_keys.items():
        keyboard.append([types.InlineKeyboardButton(
            text=gettext(lang_key), 
            callback_data=f"mirror_select_lang:{lang_code}"
        )])
    
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard)

async def store_message_id_in_redis(stream_id: str, message_id: int, user_id: int):
    """
    Store message ID in Redis for later retrieval when updating mirror cards.
    
    Args:
        stream_id: The stream ID from the mirror result
        message_id: The Telegram message ID
        user_id: The user ID for additional context
    """
    try:
        redis = RedisClient.get_client()
        key = f"mirror_msg_id:{stream_id}:{user_id}"
        await redis.set(key, str(message_id), ex=3600)  # 1 hour TTL
        logger.debug(f"[User {user_id}] Stored message ID {message_id} for stream {stream_id}")
    except Exception as e:
        logger.warning(f"[User {user_id}] Failed to store message ID in Redis: {e}")

async def get_message_id_from_redis(stream_id: str, user_id: int) -> Optional[int]:
    """
    Retrieve message ID from Redis for a given stream ID.
    
    Args:
        stream_id: The stream ID from the mirror result
        user_id: The user ID for additional context
        
    Returns:
        The message ID if found, None otherwise
    """
    try:
        redis = RedisClient.get_client()
        key = f"mirror_msg_id:{stream_id}:{user_id}"
        message_id_str = await redis.get(key)
        if message_id_str:
            return int(message_id_str)
    except Exception as e:
        logger.warning(f"[User {user_id}] Failed to get message ID from Redis: {e}")
    return None

def render_mirror_card(result: dict, user_lang: str, add_wrong_movie_btn: bool = False, tmdb_id: int = None) -> Tuple[str, types.InlineKeyboardMarkup, str, str]:
    """
    Renders a mirror movie result into a Telegram card.
    Expects structure: { "title": ..., "poster": ..., "url": ... }
    
    Args:
        result: Movie data dictionary
        user_lang: User's preferred language
        add_wrong_movie_btn: If True, add a 'Wrong movie' button
        tmdb_id: TMDB movie id (required if add_wrong_movie_btn is True)
    """
    title = result.get("title", "Awesome title 🫡").strip()
    poster = result.get("poster") or DEFAULT_POSTER_FILE_ID
    stream_id = result.get("id")

    # Strip any <b> tags from the title
    clean_title = re.sub(r"</?b>", "", title)

    # Get user-friendly language name with flag
    language_display = get_language_display_name(user_lang)

    # Wrap clean title in bold and add preferred dub info
    text = f"<b>{clean_title}</b>\n\n{gettext(PREFERRED_LANGUAGE_TO_WATCH)} {language_display}"

    buttons = [
        [types.InlineKeyboardButton(text=gettext(WATCH_MOVIE), callback_data=f"watch_mirror:{stream_id}")],
        [types.InlineKeyboardButton(text=gettext(DOWNLOAD_MOVIE), callback_data=f"download_mirror:{stream_id}")],
        [types.InlineKeyboardButton(text=gettext(CHANGE_LANGUAGE_BTN), callback_data=f"CLM:{stream_id}")]
    ]
    if add_wrong_movie_btn and tmdb_id is not None:
        buttons.append([types.InlineKeyboardButton(text=gettext(WRONG_MOVIE_BTN), callback_data=f"select_movie_card:{tmdb_id}:y")])

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    return text, keyboard, poster, stream_id

async def render_mirror_card_batch(results: list[dict], tmdb_id, user_lang: str, add_wrong_movie_btn: bool = False) -> list[Tuple[str, types.InlineKeyboardMarkup, str, str]]:
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
                    "title": result.get("title", "Awesome title 🫡").strip(),
                    "poster": result.get("poster")
                }), ex=3600) # 1 hour TTL
            except Exception as e:
                logger.warning(f"[MirrorCard] Failed to cache URL for {stream_id}: {e}")

        rendered.append(render_mirror_card(result, user_lang, add_wrong_movie_btn, tmdb_id))

    return rendered

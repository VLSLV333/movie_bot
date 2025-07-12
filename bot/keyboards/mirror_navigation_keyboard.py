from aiogram import types
from aiogram.utils.i18n import gettext
from bot.search.mirror_search_session import MirrorSearchSession
from typing import Tuple
from bot.utils.logger import Logger
from bot.utils.redis_client import RedisClient
from bot.locales.keys import MIRROR_SELECTION_HINT, MIRROR_SELECT_TITLE, PREVIOUS_BTN, NEXT_BTN
import json

logger = Logger().get_logger()

async def get_mirror_navigation_keyboard(session: MirrorSearchSession, position: str = "bottom",click_source: str | None = None) -> Tuple[str, types.InlineKeyboardMarkup]:
    """
    Create top/bottom navigation panel with message text and buttons.
    """
    redis = RedisClient.get_client()

    current = session.current_result_index
    total = len(session.mirrors_search_results.get(session.current_mirror_index, {}).get("results", []))

    # Extract movie title with proper error handling
    movie_title = "Movie"
    try:
        movie_id = session.movie_id
        movie_json = await redis.get(f"movie_info:{movie_id}")
        
        if movie_json:
            movie = json.loads(movie_json)
            movie_title = movie.get('title') or movie.get('original_title') or "Movie"
        else:
            logger.warning(f"Movie info not found in Redis for ID: {movie_id}")
    except (json.JSONDecodeError, TypeError, AttributeError) as e:
        logger.error(f"Error parsing movie info from Redis: {e}")
    except Exception as e:
        logger.error(f"Unexpected error while getting movie title: {e}")

    hint = gettext(MIRROR_SELECTION_HINT, movie_title=movie_title)

    text = gettext(MIRROR_SELECT_TITLE, movie_title=movie_title)
    if hint:
        text += f"\n\n{hint}"

    # ⬅ / ➡ buttons
    buttons = []
    show_previous = session.current_result_index > 0
    if show_previous:
        buttons.append(types.InlineKeyboardButton(text=gettext(PREVIOUS_BTN), callback_data="previous_mirror_result"))

    buttons.append(
        types.InlineKeyboardButton(
            text=gettext(NEXT_BTN),
            callback_data="next_mirror_result"
        )
    )

    logger.debug(
        f"[NavPanel] Mirror: {session.current_mirror_index}, Result: {current + 1}/{total}, Source: {click_source}, Position: {position}")
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[buttons])
    return text, keyboard

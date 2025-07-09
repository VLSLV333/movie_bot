from aiogram import types
from typing import Tuple, Optional
from aiogram_i18n import I18nContext
import json
from bot.utils.redis_client import RedisClient
from bot.utils.logger import Logger
from bot.locales.keys import (
    NO_TITLE_FALLBACK, DEFAULT_OVERVIEW_FALLBACK, GOOD_MOVIE_FALLBACK,
    IMDB_RATING_PREFIX, SELECT_BTN, WATCH_LATER_BTN,
    TRAILER_COMING_SOON, CAST_CREW_COMING_SOON, ADD_TO_FAVORITES,
    RATINGS_STORAGE_COMING_SOON, RELATED_MOVIES_COMING_SOON,
    COLLAPSE_CARD_BTN, EXPAND_CARD_BTN, CAN_NOT_FIND_BTN
)

logger = Logger().get_logger()

# ✅ Optional: default poster fallback image in TG memory now (replace with hosted later)
DEFAULT_POSTER_FILE_ID = "AgACAgIAAxkBAAICNGf7lNhs16ESonKa5G8X-Nl7LV7gAAJv8jEbd87hS9GxbYmnDY9ZAQADAgADeQADNgQ"

def truncate_text(text: str, max_length: int = 200) -> str:
    """
    Helper function to truncate long text safely.
    """
    if len(text) <= max_length:
        return text
    return text[:max_length].rstrip() + "..."

async def render_movie_card(movie: dict, i18n: I18nContext, is_expanded: bool = False) -> Tuple[str, types.InlineKeyboardMarkup, Optional[str]]:
    """
    Generate the movie card text, buttons, and poster URL.
    :param movie: Movie data dictionary from TMDB
    :param i18n: I18n context for translation
    :param is_expanded: If True, show expanded card with more options
    :return: (text, keyboard, poster_url)
    """

    # ✅ Basic movie data
    year = "(" + movie.get("release_date", "")[:4] + ")"
    if year == "()":
        year = ''

    title = movie.get("title") or i18n.get(NO_TITLE_FALLBACK)
    overview = movie.get("overview") or i18n.get(DEFAULT_OVERVIEW_FALLBACK)
    title = title.strip()
    overview = overview.strip()

    # Optional: check again if still empty after strip
    if not title:
        title = i18n.get(NO_TITLE_FALLBACK)
    if not overview:
        overview = i18n.get(GOOD_MOVIE_FALLBACK)

    # ✅ Validate poster_path
    poster_path = movie.get("poster_path")
    if not poster_path or not isinstance(poster_path, str) or not poster_path.startswith("/"):
        poster_url = DEFAULT_POSTER_FILE_ID
    else:
        poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}"

    # Get TMDB rating or fallback
    rating = movie.get("vote_average")
    rating_count = movie.get("vote_count")
    rating_text = f"\n{i18n.get(IMDB_RATING_PREFIX)}{rating:.1f}" if rating else ""

    # ✅ Prepare text caption
    text = f"<b>{title} {year}</b>{rating_text}\n\n"
    text += truncate_text(overview, max_length=300 if is_expanded else 100)

    # ✅ Prepare buttons
    buttons = []

    if is_expanded:
        # Expanded card: full options
        buttons.append([
            types.InlineKeyboardButton(text=i18n.get(SELECT_BTN), callback_data=f"select_movie_card:{movie['id']}"),
            types.InlineKeyboardButton(text=i18n.get(WATCH_LATER_BTN), callback_data=f"add_watchlist_card:{movie['id']}")
        ])
        buttons.append([
            types.InlineKeyboardButton(text=i18n.get(TRAILER_COMING_SOON), callback_data=f"watch_trailer_card:{movie['id']}"),
            types.InlineKeyboardButton(text=i18n.get(CAST_CREW_COMING_SOON), callback_data=f"movie_cast_card:{movie['id']}")
        ])
        buttons.append([
            #TODO: later we can add in Favorites btn like "share my Favorite movies"
            types.InlineKeyboardButton(text=i18n.get(ADD_TO_FAVORITES), callback_data=f"add_favorite_card:{movie['id']}"),
            types.InlineKeyboardButton(text=i18n.get(RATINGS_STORAGE_COMING_SOON), callback_data=f"rate_movie_card:{movie['id']}"),
        ])
        buttons.append([
            types.InlineKeyboardButton(text=i18n.get(RELATED_MOVIES_COMING_SOON), callback_data=f"related_movies_card:{movie['id']}"),
            types.InlineKeyboardButton(text=i18n.get(CAN_NOT_FIND_BTN), callback_data=f"can_not_watch:{movie['id']}")
        ])
        buttons.append([
            types.InlineKeyboardButton(text=i18n.get(COLLAPSE_CARD_BTN), callback_data=f"collapse_card:{movie['id']}")
        ])
    else:
        # Small card view: quick actions
        buttons.append([
            types.InlineKeyboardButton(text=i18n.get(SELECT_BTN), callback_data=f"select_movie_card:{movie['id']}"),
            types.InlineKeyboardButton(text=i18n.get(WATCH_LATER_BTN), callback_data=f"add_watchlist_card:{movie['id']}")
        ])
        buttons.append([
            types.InlineKeyboardButton(text=i18n.get(EXPAND_CARD_BTN), callback_data=f"expand_card:{movie['id']}")
        ])

    await save_movie_info_to_redis(movie)

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)

    return text, keyboard, poster_url

async def save_movie_info_to_redis(movie):
    redis = RedisClient.get_client()
    logger.info(f"movie {movie.get('original_title')} with id {movie['id']} saved to redis")
    await redis.set(f"movie_info:{movie['id']}", json.dumps(movie), ex=3600)
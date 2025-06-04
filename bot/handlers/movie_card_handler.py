from aiogram import Router, types, F
from bot.utils.session_manager import SessionManager
from bot.helpers.render_movie_card import render_movie_card
from bot.utils.logger import Logger
from bot.keyboards.search_type_keyboard import get_search_type_keyboard

logger = Logger().get_logger()
router = Router()


# Helper to fetch the movie dict from session
async def _get_movie_from_session(user_id: int, movie_id: int) -> dict | None:
    session = await SessionManager.get_user_session(user_id)
    if not session or not session.get("current_results"):
        logger.error("No session found in bot.handlers.movie_card_callbacks")
        return None
    logger.info("Got_movie_from_session in bot.handlers.movie_card_callbacks")
    return next((m for m in session["current_results"] if m["id"] == movie_id), None)

@router.callback_query(F.data.startswith("expand_card:"))
async def expand_card(query: types.CallbackQuery):
    _, mid = query.data.split(":", 1)
    movie_id = int(mid)
    movie = await _get_movie_from_session(query.from_user.id, movie_id)
    if not movie:
        keyboard = get_search_type_keyboard()
        await query.message.answer(
            "😅 I already forgot what we were searching! Pls start a new search 👇",
            reply_markup=keyboard
        )
        await query.answer()
        return

    text, keyboard, poster = await render_movie_card(movie, is_expanded=True)
    try:
        await query.bot.edit_message_media(
            chat_id=query.message.chat.id,
            message_id=query.message.message_id,
            media=types.InputMediaPhoto(media=poster, caption=text, parse_mode="HTML"),
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.error("Failed to expand card in bot.handlers.movie_card_callbacks:", e)
    await query.answer()

@router.callback_query(F.data.startswith("collapse_card:"))
async def collapse_card(query: types.CallbackQuery):
    _, mid = query.data.split(":", 1)
    movie_id = int(mid)
    movie = await _get_movie_from_session(query.from_user.id, movie_id)
    if not movie:
        keyboard = get_search_type_keyboard()
        await query.message.answer(
            "😅 I already forgot what we were searching! Pls start a new search 👇",
            reply_markup=keyboard
        )
        await query.answer()
        return

    text, keyboard, poster = await render_movie_card(movie, is_expanded=False)
    try:
        await query.bot.edit_message_media(
            chat_id=query.message.chat.id,
            message_id=query.message.message_id,
            media=types.InputMediaPhoto(media=poster, caption=text, parse_mode="HTML"),
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.error("Failed to collapse card in bot.handlers.movie_card_callbacks:", e)
    await query.answer()

# 5) Download Movie stub
@router.callback_query(F.data.startswith("download_movie_card:"))
async def download_movie(query: types.CallbackQuery):
    _, mid = query.data.split(":", 1)
    movie_id = int(mid)
    # TODO: look up real download…
    await query.answer(f"⬇️ Download link for {movie_id}: <link>", show_alert=True)

# 6) Find by Actor/Director stub
@router.callback_query(F.data.startswith("movie_cast_card:"))
async def find_people(query: types.CallbackQuery):
    _, mid = query.data.split(":", 1)
    movie_id = int(mid)
    # TODO: look up real cast/crew
    await query.answer("🕵️ Real cast/crew coming soon!", show_alert=True)

@router.callback_query(F.data.startswith("watch_trailer_card:"))
async def find_people(query: types.CallbackQuery):
    _, mid = query.data.split(":", 1)
    movie_id = int(mid)
    # TODO: look up real trailer…
    await query.answer(f"⬇️ Trailer for {movie_id}", show_alert=True)

# 7) Related Movies stub
@router.callback_query(F.data.startswith("related_movies_card:"))
async def related_movies(query: types.CallbackQuery):
    _, mid = query.data.split(":", 1)
    movie_id = int(mid)
    # TODO: provide related movies
    await query.answer("🎬 Related movies feature coming soon!", show_alert=True)

# 8) Add to Favorites stub
@router.callback_query(F.data.startswith("add_favorite_card:"))
async def add_favorite(query: types.CallbackQuery):
    _, mid = query.data.split(":", 1)
    movie_id = int(mid)
    # TODO: integrate user favorites storage
    await query.answer("⭐️ favorites storage coming soon!", show_alert=True)

# 9) Add to Watchlist stub
@router.callback_query(F.data.startswith("add_watchlist_card:"))
async def add_watchlist(query: types.CallbackQuery):
    _, mid = query.data.split(":", 1)
    movie_id = int(mid)
    # TODO: integrate user watchlist storage
    await query.answer("🕰️ watchlist storage coming soon!", show_alert=True)

# 10) Add to User movie rating
@router.callback_query(F.data.startswith("rate_movie_card:"))
async def add_watchlist(query: types.CallbackQuery):
    _, mid = query.data.split(":", 1)
    movie_id = int(mid)
    # TODO: integrate user ratings storage
    await query.answer("👍️ ratings storage coming soon!", show_alert=True)

from aiogram import Router, types, F
from aiogram.utils.i18n import gettext
from bot.locales.keys import SESSION_EXPIRED_RESTART_SEARCH, CAST_CREW_COMING_SOON, TRAILER_COMING_SOON, \
    RELATED_MOVIES_COMING_SOON, FAVORITES_STORAGE_COMING_SOON, WATCHLIST_STORAGE_COMING_SOON, \
    RATINGS_STORAGE_COMING_SOON, YES_BTN, NO_BTN, CONFIRM_REPORT_MOVIE_NOT_FOUND, REPORT_THANKS_MESSAGE
from bot.utils.session_manager import SessionManager
from bot.helpers.render_movie_card import render_movie_card
from bot.utils.logger import Logger
from bot.keyboards.search_type_keyboard import get_search_type_keyboard
from bot.utils.notify_admin import notify_admin

logger = Logger().get_logger()
router = Router()

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
            gettext(SESSION_EXPIRED_RESTART_SEARCH),
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
            reply_markup=keyboard)
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
            gettext(SESSION_EXPIRED_RESTART_SEARCH),
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
            reply_markup=keyboard)
    except Exception as e:
        logger.error("Failed to collapse card in bot.handlers.movie_card_callbacks:", e)
    await query.answer()

# 6) Find by Actor/Director stub
@router.callback_query(F.data.startswith("movie_cast_card:"))
async def find_people(query: types.CallbackQuery):
    _, mid = query.data.split(":", 1)
    movie_id = int(mid)
    # TODO: look up real cast/crew
    await query.answer(gettext(CAST_CREW_COMING_SOON), show_alert=True)

@router.callback_query(F.data.startswith("watch_trailer_card:"))
async def find_trailer(query: types.CallbackQuery):
    _, mid = query.data.split(":", 1)
    movie_id = int(mid)
    # TODO: look up real trailer…
    await query.answer(gettext(TRAILER_COMING_SOON), show_alert=True)

# 7) Related Movies stub
@router.callback_query(F.data.startswith("related_movies_card:"))
async def related_movies(query: types.CallbackQuery):
    _, mid = query.data.split(":", 1)
    movie_id = int(mid)
    # TODO: provide related movies
    await query.answer(gettext(RELATED_MOVIES_COMING_SOON), show_alert=True)

# 8) Add to Favorites stub
@router.callback_query(F.data.startswith("add_favorite_card:"))
async def add_favorite(query: types.CallbackQuery):
    _, mid = query.data.split(":", 1)
    movie_id = int(mid)
    # TODO: integrate user favorites storage
    await query.answer(gettext(FAVORITES_STORAGE_COMING_SOON), show_alert=True)

# 9) Add to Watchlist stub
@router.callback_query(F.data.startswith("add_watchlist_card:"))
async def add_watchlist(query: types.CallbackQuery):
    _, mid = query.data.split(":", 1)
    movie_id = int(mid)
    # TODO: integrate user watchlist storage
    await query.answer(gettext(WATCHLIST_STORAGE_COMING_SOON), show_alert=True)

# 10) Add to User movie rating
@router.callback_query(F.data.startswith("rate_movie_card:"))
async def add_watchlist(query: types.CallbackQuery):
    _, mid = query.data.split(":", 1)
    movie_id = int(mid)
    # TODO: integrate user ratings storage
    await query.answer(gettext(RATINGS_STORAGE_COMING_SOON), show_alert=True)

# Handler for 'Can not watch' button
@router.callback_query(F.data.startswith("can_not_watch:"))
async def can_not_watch_handler(query: types.CallbackQuery):
    _, mid = query.data.split(":", 1)
    movie_id = int(mid)
    # Send confirmation message with Yes/No buttons
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text=gettext(YES_BTN), callback_data=f"report_yes:{movie_id}"),
            types.InlineKeyboardButton(text=gettext(NO_BTN), callback_data=f"report_no:{movie_id}")
        ]
    ])
    msg = await query.message.answer(
        gettext(CONFIRM_REPORT_MOVIE_NOT_FOUND),
        reply_markup=kb
    )
    await query.answer()

# Handler for 'No' button (delete confirmation message)
@router.callback_query(F.data.startswith("report_no:"))
async def report_no_handler(query: types.CallbackQuery):
    if query.message:
        await query.message.delete()
    await query.answer()

# Handler for 'Yes' button (notify admin and thank user)
@router.callback_query(F.data.startswith("report_yes:"))
async def report_yes_handler(query: types.CallbackQuery):
    _, mid = query.data.split(":", 1)
    movie_id = int(mid)
    user = query.from_user
    user_id = user.id
    username = user.username or "-"
    first_name = user.first_name or "-"
    last_name = user.last_name or "-"

    # Get movie info and session
    movie = await _get_movie_from_session(user_id, movie_id)
    session = await SessionManager.get_user_session(user_id)
    initial_query = session.get("original_query") if session else None

    # Prepare admin message
    if movie:
        title = movie.get("title", "-")
        release_date = movie.get("release_date", "-")
    else:
        title = release_date = "-"
    admin_msg = (
        f"🚨 User reported 'Can not watch'\n"
        f"User ID: {user_id}\n"
        f"Username: @{username}\n"
        f"Name: {first_name} {last_name}\n"
        f"Initial query: {initial_query}\n"
        f"TMDB movie id: {movie_id}\n"
        f"Title: {title}\n"
        f"Release date: {release_date}"
    )
    await notify_admin(admin_msg)

    # Edit confirmation message
    if query.message:
        await query.message.edit_text(
            gettext(REPORT_THANKS_MESSAGE)
        )
    await query.answer()

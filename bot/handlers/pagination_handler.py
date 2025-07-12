import asyncio
from weakref import WeakValueDictionary
from aiogram import Router, types, F
from aiogram.utils.i18n import gettext
from aiogram.exceptions import TelegramBadRequest
from bot.services.tmdb_service import TMDBService
from bot.utils.logger import Logger
from bot.locales.keys import (
    WAIT_CARDS_UPDATING, SESSION_EXPIRED_RESTART_SEARCH, NO_MORE_MATCHES_START_NEW_SEARCH
)
from bot.utils.session_manager import SessionManager
from bot.helpers.render_movie_card import render_movie_card
from bot.helpers.render_navigation_panel import render_navigation_panel
from bot.helpers.back_to_main_menu_btn import add_back_to_main_menu_button
from bot.keyboards.search_type_keyboard import get_search_type_keyboard
from bot.search.user_search_context import UserSearchContext

logger = Logger().get_logger()
tmdb_service = TMDBService()
router = Router()

author_locks: WeakValueDictionary[int, asyncio.Lock] = WeakValueDictionary()

def get_user_lock(user_id: int) -> asyncio.Lock:
    """
    Retrieve or create a per-user lock. Locks are stored in a WeakValueDictionary,
    so they will be removed automatically when no longer in use.
    """
    lock = author_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        author_locks[user_id] = lock
    return lock

def detect_click_source(session_data: dict, clicked_message_id: int) -> str:
    if clicked_message_id == session_data.get("top_pagination_message_id"):
        logger.info("Detected click source: TOP panel")
        return "top"
    elif clicked_message_id == session_data.get("pagination_message_id"):
        logger.info("Detected click source: BOTTOM panel")
        return "bottom"
    logger.info("Detected click source: UNKNOWN")
    return "unknown"

async def safely_delete_navigation(query: types.CallbackQuery, pagination_message_id: int) -> bool:
    """
       Safely delete the bottom navigation panel in case user deleted one of cards.
       This way we resend new 5 cards and new navigation at very bottom
       Returns True if deleted successfully, False otherwise.
       """
    try:
        await query.bot.delete_message(
            chat_id=query.message.chat.id,
            message_id=pagination_message_id
        )
        logger.info(f"[User {query.from_user.id}]. Automatically deleted old bottom pagination panel, because user previously deleted movie card.")
        return True
    except TelegramBadRequest as ex:
        logger.warning(f"[User {query.from_user.id}] Could not delete bottom panel: {ex}")
        return False

async def handle_pagination(query: types.CallbackQuery, direction: str):
    # 1) grab the per‑user lock
    user_id = query.from_user.id
    lock = get_user_lock(user_id)

    # 2) if it's already locked, just ignore the extra tap
    if lock.locked():
        return await query.answer(gettext(WAIT_CARDS_UPDATING), show_alert=False)

    # 3) only one runner at a time
    async with lock:
        session = await SessionManager.get_user_session(user_id)
        navigation_deleted = False

        if not session:
            logger.warning(f"[User {user_id}] No session found while paginating.")
            try:
                await SessionManager.clear_state(user_id)
            except Exception as e:
                logger.error(f"Redis error while clearing state : {e}")

            keyboard = get_search_type_keyboard()

            await query.message.answer(
                gettext(SESSION_EXPIRED_RESTART_SEARCH),
                reply_markup=keyboard
            )
            await query.answer()
            return

        click_source = detect_click_source(session, query.message.message_id)
        context = UserSearchContext.from_dict(session)

        message_ids = session.get("current_cards_message_ids", [])
        # updated_message_ids = message_ids.copy()
        pagination_message_id = session.get("pagination_message_id")
        top_pagination_message_id = session.get("top_pagination_message_id")

        movies = await (context.get_next_movies(tmdb_service) if direction == "next" else context.get_previous_movies(tmdb_service))

        if not movies:
            keyboard = get_search_type_keyboard()
            await query.message.answer(gettext(NO_MORE_MATCHES_START_NEW_SEARCH), reply_markup=keyboard)

            try:
                await SessionManager.clear_user_session(user_id)
                await SessionManager.clear_state(user_id)
            except Exception as e:
                logger.error(f"Redis error while clearing session and state: {e}")

            await query.answer()
            return

        #Delete bottom nav because we resend it always
        if pagination_message_id:
            await query.bot.delete_message(chat_id=query.message.chat.id, message_id=pagination_message_id)

        # --- Robust movie card update logic for dynamic batch sizes ---
        # If fewer movies than message_ids, delete extra cards and use placeholders
        num_movies = len(movies)
        num_message_ids = len(message_ids)
        PLACEHOLDER_IDS = ['001', '002', '003', '004', '005']
        updated_message_ids = message_ids.copy()
        
        # If we have more message_ids than movies, delete the extras and set placeholders
        if num_message_ids > num_movies:
            for idx in range(num_movies, num_message_ids):
                msg_id_to_delete = message_ids[idx]
                logger.info(f"[Pagination] Deleting extra card with message_id: {msg_id_to_delete}")
                try:
                    await query.bot.delete_message(chat_id=query.message.chat.id, message_id=msg_id_to_delete)
                except Exception as e:
                    logger.error(f"[User {user_id}] Failed to delete extra movie card: {e}")
                # Set placeholder for this slot
                updated_message_ids[idx] = PLACEHOLDER_IDS[idx]
            logger.info(f"[Pagination] updated_message_ids after deletion/placeholders: {updated_message_ids}")
        
        # If we have fewer message_ids than movies, pad with placeholders
        if num_message_ids < num_movies:
            logger.info(f"[Pagination] Padding updated_message_ids with placeholders: {PLACEHOLDER_IDS[num_message_ids:num_movies]}")
            updated_message_ids += PLACEHOLDER_IDS[num_message_ids:num_movies]
            logger.info(f"[Pagination] updated_message_ids after padding: {updated_message_ids}")
        
        # Now, update or send cards as needed
        for i, (movie, message_id) in enumerate(zip(movies, updated_message_ids)):
            text, keyboard, poster_url = await render_movie_card(movie, is_expanded=False)
            if str(message_id) in PLACEHOLDER_IDS:
                try:
                    sent = await query.message.answer_photo(photo=poster_url, caption=text, reply_markup=keyboard, parse_mode="HTML")
                    updated_message_ids[i] = sent.message_id
                except Exception as ex:
                    logger.error(f"[User {user_id}] Failed to resend movie card: {ex}")
                continue  # Skip to next card
            try:
                await query.bot.edit_message_media(
                    chat_id=query.message.chat.id,
                    message_id=message_id,
                    media=types.InputMediaPhoto(media=poster_url, caption=text, parse_mode="HTML"),
                    reply_markup=keyboard
                )
            except TelegramBadRequest as e:
                logger.warning(f"[Pagination] Failed to edit card {i} with message_id: {message_id}, error: {e}")
                if "message to edit not found" in str(e):
                    # Send new card and update message_id
                    try:
                        sent = await query.message.answer_photo(photo=poster_url, caption=text, reply_markup=keyboard, parse_mode="HTML")
                        updated_message_ids[i] = sent.message_id
                    except Exception as ex:
                        logger.error(f"[User {user_id}] Failed to resend movie card: {ex}")
                elif "message is not modified" in str(e):
                    logger.info(f"Card {message_id} unchanged; skipping edit")
                elif "canceled by new editMessageMedia request" in str(e):
                    logger.info("Previous edit canceled by newer one; skipping")
                else:
                    logger.error(f"[User {user_id}] Failed to edit movie card : {e}")
        # After all, trim updated_message_ids to match movies
        updated_message_ids = updated_message_ids[:num_movies]

        # Try to update top pagination
        try:
            if top_pagination_message_id:
                nav_text_top, nav_keyboard_top = render_navigation_panel(context, position="top", click_source=click_source)
                nav_keyboard_top = add_back_to_main_menu_button(nav_keyboard_top)
                await query.bot.edit_message_text(
                    chat_id=query.message.chat.id,
                    message_id=top_pagination_message_id,
                    text=nav_text_top,
                    reply_markup=nav_keyboard_top
                )
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                logger.info("Top panel unchanged; skipping edit")
            elif "canceled by new editMessageMedia request" in str(e):
                logger.info("Previous edit canceled by newer one; skipping")
            else:
                top_pagination_message_id = None # Top navigation panel was probably deleted by user, set ID to None to skip future updates in current session
                logger.error(
                f"[User {query.from_user.id}] probably deleted top pagination panel: {e}"
                )

        # Try to update bottom pagination
        try:
            nav_text, nav_keyboard = render_navigation_panel(context, position="bottom", click_source=click_source)
            nav_keyboard = add_back_to_main_menu_button(nav_keyboard)
            panel = await query.message.answer(nav_text, reply_markup=nav_keyboard)
            pagination_message_id = panel.message_id
        except TelegramBadRequest as e:
            if "message to edit not found" in str(e):
                logger.warning(
                    f"[User {query.from_user.id}] Bot navigation {pagination_message_id} not found .")
            else:
                logger.error(
                    f"[User {query.from_user.id}] Error sending pagination panel: {e}")

        try:
            await SessionManager.save_context(
                query.from_user.id,
                context,
                updated_message_ids,
                pagination_message_id,
                top_pagination_message_id
            )
        except Exception as e:
            logger.error(f"Redis error while saving session  : {e}")

        await query.answer()

@router.callback_query(F.data == "show_more_results")
async def show_more_results(query: types.CallbackQuery):
    await handle_pagination(query, direction="next")

@router.callback_query(F.data == "show_previous_results")
async def show_previous_results(query: types.CallbackQuery):
    await handle_pagination(query, direction="previous")
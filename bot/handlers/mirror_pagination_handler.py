from aiogram import Router, types, F
from aiogram.exceptions import TelegramBadRequest

from bot.utils.session_manager import SessionManager
from bot.search.mirror_search_session import MirrorSearchSession
from bot.keyboards.mirror_navigation_keyboard import get_mirror_navigation_keyboard
from bot.helpers.render_mirror_card import render_mirror_card_batch
from bot.utils.logger import Logger

router = Router()
logger = Logger().get_logger()

BATCH_SIZE = 5

def detect_click_source(session_data: dict, clicked_message_id: int) -> str:
    if clicked_message_id == session_data.get("top_nav_message_id"):
        return "top"
    elif clicked_message_id == session_data.get("bottom_nav_message_id"):
        return "bottom"
    return "unknown"

async def safely_delete_navigation(query: types.CallbackQuery, nav_message_id: int) -> bool:
    try:
        await query.bot.delete_message(
            chat_id=query.message.chat.id,
            message_id=nav_message_id
        )
        return True
    except TelegramBadRequest as ex:
        logger.warning(f"[User {query.from_user.id}] Could not delete bottom nav panel: {ex}")
        return False

async def update_mirror_results_ui(query: types.CallbackQuery, session: MirrorSearchSession, click_source: str):
    user_id = query.from_user.id
    mirror_data = session.mirrors_search_results.get(session.current_mirror_index, {})
    results = mirror_data.get("results", [])

    start = session.current_result_index
    end = min(start + BATCH_SIZE, len(results))
    current_batch = results[start:end]

    # 1. Update top panel
    top_text, top_keyboard = get_mirror_navigation_keyboard(session, position="top", click_source=click_source)
    try:
        await query.bot.edit_message_text(
            chat_id=query.message.chat.id,
            message_id=session.top_nav_message_id,
            text=top_text,
            reply_markup=top_keyboard
        )
    except TelegramBadRequest as e:
        if "message to edit not found" in str(e):
            session.top_nav_message_id = None
            logger.warning(f"[User {user_id}] Top nav panel deleted by user")
        else:
            logger.warning(f"[User {user_id}] Could not update top nav panel: {e}")

    # 2. Update movie cards
    logger.debug(
        f"[User {user_id}] Retrieved {len(results)} total results from mirror index {session.current_mirror_index}")
    logger.debug(
        f"[User {user_id}] Current pagination index: {session.current_result_index} → showing results {start}:{end}")
    logger.debug(f"[User {user_id}] Titles in current batch: {[r.get('title') for r in current_batch]}")

    cards = await render_mirror_card_batch(current_batch)
    updated_ids = []
    navigation_deleted = False

    for i, (text, kb, poster) in enumerate(cards):
        try:
            message_id = session.card_message_ids[i]
            if poster:
                await query.bot.edit_message_media(
                    chat_id=query.message.chat.id,
                    message_id=message_id,
                    media=types.InputMediaPhoto(media=poster, caption=text, parse_mode="HTML"),
                    reply_markup=kb
                )
            else:
                await query.bot.edit_message_caption(
                    chat_id=query.message.chat.id,
                    message_id=message_id,
                    caption=text,
                    reply_markup=kb,
                    parse_mode="HTML"
                )
            updated_ids.append(message_id)
        except TelegramBadRequest as e:
            if "message to edit not found" in str(e):
                logger.warning(f"[User {user_id}] Mirror card {i} was deleted. Resending...")
                if not navigation_deleted:
                    navigation_deleted = await safely_delete_navigation(query, session.bottom_nav_message_id)
                try:
                    if poster:
                        msg = await query.message.answer_photo(photo=poster, caption=text, reply_markup=kb, parse_mode="HTML")
                    else:
                        msg = await query.message.answer(text=text, reply_markup=kb, parse_mode="HTML")
                    updated_ids.append(msg.message_id)
                except Exception as ex:
                    logger.error(f"[User {user_id}] Failed to resend movie card: {ex}")
            else:
                logger.error(f"[User {user_id}] Failed to update card {i}: {e}")

    # 3. Update bottom panel
    bottom_text, bottom_keyboard = get_mirror_navigation_keyboard(session, position="bottom", click_source=click_source)
    if navigation_deleted:
        try:
            panel = await query.message.answer(bottom_text, reply_markup=bottom_keyboard)
            session.bottom_nav_message_id = panel.message_id
        except Exception as e:
            logger.error(f"[User {user_id}] Failed to resend bottom nav panel: {e}")
    else:
        try:
            await query.bot.edit_message_text(
                chat_id=query.message.chat.id,
                message_id=session.bottom_nav_message_id,
                text=bottom_text,
                reply_markup=bottom_keyboard
            )
        except TelegramBadRequest as e:
            if "message to edit not found" in str(e):
                logger.warning(f"[User {user_id}] Bottom nav panel deleted by user")
                session.bottom_nav_message_id = None
            else:
                logger.warning(f"[User {user_id}] Could not update bottom nav panel: {e}")

    logger.debug(f"[User {user_id}] Showing results {start} to {end} (mirror {session.current_mirror_index})")

    # Save session
    session.card_message_ids = updated_ids
    await SessionManager.update_data(user_id, {"mirror_session": session.to_dict()})
    logger.info(
        f"[User {user_id}] Saved pagination session: top_panel={session.top_nav_message_id}, bottom_panel={session.bottom_nav_message_id}, cards={session.card_message_ids}")

@router.callback_query(F.data == "next_mirror_result")
async def next_mirror_result(query: types.CallbackQuery):
    user_id = query.from_user.id
    session_data = await SessionManager.get_data(user_id)
    if not session_data:
        #TODO: ADD "ADD "😅 I already forgot what we were searching! Pls start a new search 👇" + keyboard"
        await query.answer("Session expired", show_alert=True)
        return

    logger.info(f"[User {user_id}] Triggered pagination:  'next' ")

    session = MirrorSearchSession.from_dict(session_data.get("mirror_session"))
    session.current_result_index += BATCH_SIZE
    click_source = detect_click_source(session.__dict__, query.message.message_id)

    await update_mirror_results_ui(query, session, click_source)
    await query.answer()


@router.callback_query(F.data == "previous_mirror_result")
async def previous_mirror_result(query: types.CallbackQuery):
    user_id = query.from_user.id
    session_data = await SessionManager.get_data(user_id)
    if not session_data:
        #TODO: ADD "ADD "😅 I already forgot what we were searching! Pls start a new search 👇" + keyboard"
        await query.answer("Session expired", show_alert=True)
        return

    logger.info(f"[User {user_id}] Triggered pagination: 'previous'")

    session = MirrorSearchSession.from_dict(session_data.get("mirror_session"))
    session.current_result_index = max(0, session.current_result_index - BATCH_SIZE)
    click_source = detect_click_source(session.__dict__, query.message.message_id)

    await update_mirror_results_ui(query, session, click_source)
    await query.answer()

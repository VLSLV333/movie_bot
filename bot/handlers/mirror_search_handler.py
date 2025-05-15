from aiogram import Router, types, F
from bot.search.mirror_search_session import MirrorSearchSession
from bot.utils.session_manager import SessionManager
from bot.keyboards.mirror_search_keyboard import get_mirror_search_keyboard, get_mirror_navigation_keyboard
from bot.helpers.back_to_main_menu_btn import get_back_to_main_menu_keyboard
from bot.utils.logger import Logger
from aiogram.exceptions import TelegramBadRequest
from bot.handlers.mirror_extraction_handler import confirm_final_movie

router = Router()
logger = Logger().get_logger()

# Helper to load mirror search session from Redis
async def load_mirror_session(user_id: int) -> MirrorSearchSession | None:
    session_data = await SessionManager.get_data(user_id)
    if session_data and session_data.get("mirror_search_session"):
        return MirrorSearchSession.from_dict(session_data["mirror_search_session"])
    return None

# Helper to save mirror search session back to Redis
async def save_mirror_session(user_id: int, session: MirrorSearchSession):
    await SessionManager.update_data(user_id, {"mirror_search_session": session.to_dict()})

# Show 5 movie cards + top & bottom navigation
async def show_mirror_batch(callback_query: types.CallbackQuery, session: MirrorSearchSession):
    try:
        mirror = session.mirrors[session.current_mirror_index]
        results = mirror.get("results", [])

        if session.current_result_index >= len(results):
            session.current_mirror_index += 1
            session.current_result_index = 0
            if session.current_mirror_index >= len(session.mirrors):
                #TODO:add button here for user not to get stuck and continue flow
                #TODO: add ping logic for admin to receive message containing relevant info that some search was not successfull
                #TODO: to improve search
                await callback_query.message.answer(
                    "😔 Sorry, we couldn't find your movie. We'll improve soon!",
                    reply_markup=get_back_to_main_menu_keyboard()
                )
                logger.warning(f"[User {session.user_id}] No matches found after all mirrors. Should ping admin!")
                await SessionManager.clear_data(session.user_id)
                return
            else:
                await save_mirror_session(session.user_id, session)
                await show_mirror_batch(callback_query, session)
                return

        # Slice next 5 results
        start = session.current_result_index
        end = min(start + 5, len(results))
        batch = results[start:end]

        navigation_deleted = False

        # --- Edit Top Navigation ---
        try:
            if session.top_nav_message_id:
                await callback_query.bot.edit_message_text(
                    chat_id=callback_query.message.chat.id,
                    message_id=session.top_nav_message_id,
                    text=f"📌 Please scroll down and choose your movie {start}-{end}:\n\n Or press 'Next 5' for other movies",
                    reply_markup=get_mirror_navigation_keyboard(session)
                )
        except TelegramBadRequest as e:
            logger.warning(f"Failed to edit top nav: {e}")
            if "message to edit not found" in e:
                logger.warning(f"Removed top nav id")
                #User probably deleted top navigation
                session.top_nav_message_id = None

            # top_nav = await callback_query.message.answer(
            #     "📌 Please choose your movie:",
            #     reply_markup=get_mirror_navigation_keyboard(session)
            # )
            # session.top_nav_message_id = top_nav.message_id


        # --- Edit Movie Cards ---
        for relative_idx, movie in enumerate(batch):
            absolute_idx = start + relative_idx
            text = (
                f"🎬 <b>{movie['title']}</b>\n"
                f"🌐 Language: {movie['language']}\n"
            )
            keyboard = get_mirror_search_keyboard(absolute_idx)

            try:
                existing_message_id = session.card_message_ids[relative_idx]
                await callback_query.bot.edit_message_media(
                    chat_id=callback_query.message.chat.id,
                    message_id=existing_message_id,
                    media=types.InputMediaPhoto(
                        media=movie['poster'],
                        caption=text,
                        parse_mode="HTML"
                    ),
                    reply_markup=keyboard
                )
            except (IndexError, TelegramBadRequest) as e:
                logger.warning(f"Failed to edit movie card or missing: {e}")

                if not navigation_deleted:
                    #delete bot navigation to resend it very last after resend movie cards
                    try:
                        if session.bottom_nav_message_id:
                            await callback_query.bot.delete_message(
                                chat_id=callback_query.message.chat.id,
                                message_id=session.bottom_nav_message_id
                            )
                    except TelegramBadRequest:
                        pass
                    navigation_deleted = True

                sent = await callback_query.message.answer_photo(
                    photo=movie['poster'],
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )

                try:
                    session.card_message_ids[relative_idx] = sent.message_id
                except IndexError:
                    session.card_message_ids.append(sent.message_id)

        session.card_message_ids = session.card_message_ids[:len(batch)]
        session.current_result_index += len(batch)

        # --- Edit Bottom Navigation ---
        try:
            if session.bottom_nav_message_id:
                await callback_query.bot.edit_message_text(
                    chat_id=callback_query.message.chat.id,
                    message_id=session.bottom_nav_message_id,
                    text=f"📌 Please scroll up and choose your movie {start}-{end}:\n\n Or press 'Next 5' for other movies",
                    reply_markup=get_mirror_navigation_keyboard(session)
                )
        except TelegramBadRequest as e:
            logger.warning(f"Failed to edit bottom nav: {e}")
            bottom_nav = await callback_query.message.answer(
                f"📌 Please scroll up and choose your movie {start}-{end}:\n\n Or press 'Next 5' for other movies",
                reply_markup=get_mirror_navigation_keyboard(session)
            )
            session.bottom_nav_message_id = bottom_nav.message_id

        await save_mirror_session(session.user_id, session)

    except Exception as e:
        logger.error(f"[User {session.user_id}] Failed to show mirror results: {e}")

@router.callback_query(F.data.startswith("confirm_mirror_movie:"))
async def confirm_mirror_movie(query: types.CallbackQuery):
    session = await load_mirror_session(query.from_user.id)
    if not session:
        # TODO: Add back to main menu btn
        await query.answer("Session expired! Please search again.", show_alert=True)
        return

    try:
        _, idx_str = query.data.split(":", 1)
        idx = int(idx_str)

        # TODO: if we take session.mirrors[session.current_mirror_index] isn't it gonna always be a batch with indexes 0-4?
        # TODO: so we don't need  absolute_idx = start + relative_idx but we need relative_idx?
        mirror = session.mirrors[session.current_mirror_index]
        movie = mirror.get("results", [])[idx]

        session.confirmed_movie = movie

        logger.info(f"User {query.from_user.id} confirmed movie: {movie.title}")
        await save_mirror_session(query.from_user.id, session)

        await query.message.answer("🎯 Final touch! Preparing your video...")
        await query.answer()

        await confirm_final_movie(query)

    except Exception as e:
        # TODO: Add back to main menu btn
        logger.error(f"Failed to confirm mirror movie: {e}")
        await query.answer("Something went wrong.", show_alert=True)


@router.callback_query(F.data == "wrong_language")
async def wrong_language(query: types.CallbackQuery):
    # TODO: First we show inline btns with default languages that our bot is already supports (UA-ENG) right now and last btn "another option"
    # TODO: if user clicks "another option" we listen to his input and ping admin with message abput user ID and language that he requested
    # TODO: if user chooses one of languages on btns we handle it as his preffered language
    await query.message.answer("🌍 Please tell me your preferred language (example: English, Ukrainian, etc.)")
    await SessionManager.set_state(query.from_user.id, "waiting_for_language_input")
    await query.answer()

@router.callback_query(F.data == "next_mirror_result")
async def next_mirror_result(query: types.CallbackQuery):
    session = await load_mirror_session(query.from_user.id)
    if not session:
        # TODO: Add back to main menu btn
        await query.answer("Session expired! Please search again.", show_alert=True)
        return

    await show_mirror_batch(query, session)
    await query.answer()

@router.callback_query(F.data == "previous_mirror_result")
async def previous_mirror_result(query: types.CallbackQuery):
    session = await load_mirror_session(query.from_user.id)
    if not session:
        # TODO: Add back to main menu btn
        await query.answer("Session expired! Please search again.", show_alert=True)
        return

    if session.current_result_index == 0 and session.current_mirror_index > 0:
        # Move to previous mirror
        session.current_mirror_index -= 1
        prev_mirror = session.mirrors[session.current_mirror_index]
        session.current_result_index = max(0, len(prev_mirror.get('results', [])) - 5)
    else:
        # Normal paging inside same mirror
        session.current_result_index = max(0, session.current_result_index - 10)


    await show_mirror_batch(query, session)
    await query.answer()

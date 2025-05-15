from aiogram import Router, types, F
from bot.handlers.main_menu_btns_handler import get_main_menu_keyboard
from bot.utils.session_manager import SessionManager
from bot.utils.logger import Logger
from bot.keyboards.search_type_keyboard import get_search_type_keyboard
from bot.keyboards.select_movie_genre_keyboard import get_movie_genre_keyboard
from bot.keyboards.select_year_range_keyboard import get_year_range_keyboard

router = Router()
logger = Logger().get_logger()


@router.callback_query(F.data.startswith("back:"))
async def handle_back_btn(query: types.CallbackQuery):
    """
       Handles the logic of going back by deleting current message and showing destination view.
       Clears session state if needed.
       :param query: Telegram CallbackQuery object
       """
    _, destination = query.data.split(":")
    user_id = query.from_user.id

    if destination == "main":
        logger.info(f"[User {user_id}] Navigated back to main menu via Back button.")
        await SessionManager.clear_state(user_id)
        await query.message.edit_text(
            "🏠 You're back at the main menu!",
            reply_markup=get_main_menu_keyboard()
        )
    elif destination == "search":
        logger.info(f"[User {user_id}] Navigated back to search type menu via Back button.")
        await SessionManager.clear_state(user_id)
        await query.message.edit_text(
            "🎯 How would you like to search for a movie?",
            reply_markup=get_search_type_keyboard()
        )
    elif destination == "select_genre":
        logger.info(f"[User {user_id}] Navigated back to select_genre via Back button.")

        session = await SessionManager.get_data(user_id)
        selected_genres = session.get("selected_genres", [])

        keyboard = get_movie_genre_keyboard(selected_genres)

        await SessionManager.clear_state(user_id)
        await query.message.edit_text(
            "🎭 Choose one or more genres below\n\nWhen you're ready, press '✅ Confirm':",
            reply_markup=keyboard
        )
    elif destination == "year_range":
        logger.info(f"[User {user_id}] Navigated back to year range selection menu via Back button.")

        await SessionManager.clear_state(user_id)
        keyboard = get_year_range_keyboard()
        await query.message.edit_text("📅 Now choose a year range:", reply_markup=keyboard)

        # Future destinations can go here

    await query.answer()

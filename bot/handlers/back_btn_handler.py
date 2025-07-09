from aiogram import Router, types, F
from aiogram_i18n import I18nContext
from bot.handlers.main_menu_btns_handler import get_main_menu_keyboard
from bot.locales.keys import BACK_TO_MAIN_MENU, SEARCH_TYPE_QUESTION, GENRE_SELECTION_PROMPT, \
    YEAR_RANGE_SELECTION_PROMPT
from bot.utils.session_manager import SessionManager
from bot.utils.logger import Logger
from bot.keyboards.search_type_keyboard import get_search_type_keyboard
from bot.keyboards.select_movie_genre_keyboard import get_movie_genre_keyboard
from bot.keyboards.select_year_range_keyboard import get_year_range_keyboard

router = Router()
logger = Logger().get_logger()


@router.callback_query(F.data.startswith("back:"))
async def handle_back_btn(query: types.CallbackQuery, i18n: I18nContext):
    """
       Handles the logic of going back by deleting current message and showing destination view.
       Clears session state if needed.
       :param i18n: I18nContext for i18n
       :param query: Telegram CallbackQuery object
       """
    _, destination = query.data.split(":")
    user_id = query.from_user.id

    if destination == "main":
        logger.info(f"[User {user_id}] Navigated back to main menu via Back button.")
        await SessionManager.clear_state(user_id)
        await query.message.edit_text(
            i18n.get(BACK_TO_MAIN_MENU),
            reply_markup=get_main_menu_keyboard(i18n=i18n)
        )
    elif destination == "search":
        logger.info(f"[User {user_id}] Navigated back to search type menu via Back button.")
        await SessionManager.clear_state(user_id)
        await query.message.edit_text(
            i18n.get(SEARCH_TYPE_QUESTION),
            reply_markup=get_search_type_keyboard(i18n=i18n)
        )
    elif destination == "select_genre":
        logger.info(f"[User {user_id}] Navigated back to select_genre via Back button.")

        session = await SessionManager.get_data(user_id)
        selected_genres = session.get("selected_genres", [])

        keyboard = get_movie_genre_keyboard(selected_genres, i18n=i18n)

        await SessionManager.clear_state(user_id)
        await query.message.edit_text(
            i18n.get(GENRE_SELECTION_PROMPT),
            reply_markup=keyboard
        )
    elif destination == "year_range":
        logger.info(f"[User {user_id}] Navigated back to year range selection menu via Back button.")

        await SessionManager.clear_state(user_id)
        keyboard = get_year_range_keyboard(i18n=i18n)
        await query.message.edit_text(i18n.get(YEAR_RANGE_SELECTION_PROMPT), reply_markup=keyboard)

    await query.answer()

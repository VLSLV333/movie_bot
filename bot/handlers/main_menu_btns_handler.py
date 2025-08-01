from aiogram import Router, types, F
from aiogram.utils.i18n import gettext
from bot.locales.keys import FIND_MOVIE_BTN, RECOMMEND_BTN, DOWNLOAD_BTN, WATCH_HISTORY_BTN, FAVORITES_BTN, OPTIONS_BTN, \
    SEARCH_TYPE_QUESTION, RECOMMENDATIONS_COMING_SOON, WATCH_HISTORY_COMING_SOON, FAVORITES_COMING_SOON, \
    BACK_TO_MAIN_MENU
from bot.utils.logger import Logger
from bot.utils.session_manager import SessionManager
from bot.utils.message_utils import smart_edit_or_send
from bot.keyboards.search_type_keyboard import get_search_type_keyboard

router = Router()
logger = Logger().get_logger()


# --- Main Menu Keyboard Generator ---
def get_main_menu_keyboard() -> types.InlineKeyboardMarkup:
    keyboard = [
        [
            types.InlineKeyboardButton(text=gettext(FIND_MOVIE_BTN), callback_data="search_movie"),
        ],
        [
            types.InlineKeyboardButton(text=gettext(RECOMMEND_BTN), callback_data="suggest_movie"),
            types.InlineKeyboardButton(text=gettext(DOWNLOAD_BTN), callback_data="download_movie")
        ],
        [
            types.InlineKeyboardButton(text=gettext(WATCH_HISTORY_BTN), callback_data="watch_history"),
            types.InlineKeyboardButton(text=gettext(FAVORITES_BTN), callback_data="favorites"),
        ],
        [
            types.InlineKeyboardButton(text=gettext(OPTIONS_BTN), callback_data="options"),
        ]
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard)


# --- Search Movie Logic (reusable for both command and callback) ---
async def handle_search_movie_request(message_or_query):
    """Common logic for handling search movie requests from both commands and callbacks"""
    keyboard = get_search_type_keyboard()
    
    await smart_edit_or_send(
        message=message_or_query,
        text=gettext(SEARCH_TYPE_QUESTION),
        reply_markup=keyboard
    )


@router.message(F.text == "/search_movie")
async def search_movie_command_handler(message: types.Message):
    """Handle /search_movie command"""
    await handle_search_movie_request(message)


@router.callback_query(F.data == "search_movie")
async def search_movie_handler(query: types.CallbackQuery):
    """Handle search_movie button callback"""
    await handle_search_movie_request(query)
    await query.answer()


@router.callback_query(F.data == "suggest_movie")
async def suggest_movie_handler(query: types.CallbackQuery):
    logger.info(f"[User {query.from_user.id}] Clicked 'Recommend Me' button")
    await query.answer(gettext(RECOMMENDATIONS_COMING_SOON), show_alert=True)



@router.callback_query(F.data == "watch_history")
async def watch_history_handler(query: types.CallbackQuery):
    logger.info(f"[User {query.from_user.id}] Clicked 'Watch History' button")
    await query.answer(gettext(WATCH_HISTORY_COMING_SOON), show_alert=True)


@router.callback_query(F.data == "favorites")
async def favorites_handler(query: types.CallbackQuery):
    logger.info(f"[User {query.from_user.id}] Clicked 'Favorites' button")
    await query.answer(gettext(FAVORITES_COMING_SOON), show_alert=True)


@router.callback_query(F.data.startswith("back_to_main"))
async def back_to_main_menu_handler(query: types.CallbackQuery):
    logger.debug(f"[User {query.from_user.id}] Clicked 'Back to Main Menu'")

    await SessionManager.clear_state(query.from_user.id)
    logger.debug(f"[User {query.from_user.id}] session state was cleared in bot.handlers.main_menu_btns back_to_main_menu_handler")

    keyboard = get_main_menu_keyboard()

    await query.message.answer(
        gettext(BACK_TO_MAIN_MENU),
        reply_markup=keyboard
    )

    await query.answer()
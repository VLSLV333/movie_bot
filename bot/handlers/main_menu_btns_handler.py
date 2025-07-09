from aiogram import Router, types, F
from aiogram_i18n import I18nContext
from bot.locales.keys import FIND_MOVIE_BTN, RECOMMEND_BTN, DOWNLOAD_BTN, WATCH_HISTORY_BTN, FAVORITES_BTN, OPTIONS_BTN, \
    SEARCH_TYPE_QUESTION, RECOMMENDATIONS_COMING_SOON, WATCH_HISTORY_COMING_SOON, FAVORITES_COMING_SOON, \
    OPTIONS_COMING_SOON, DOWNLOAD_COMING_SOON, BACK_TO_MAIN_MENU
from bot.utils.logger import Logger
from bot.utils.session_manager import SessionManager
from bot.utils.message_utils import smart_edit_or_send
from bot.keyboards.search_type_keyboard import get_search_type_keyboard

router = Router()
logger = Logger().get_logger()


# --- Main Menu Keyboard Generator ---
def get_main_menu_keyboard(i18n: I18nContext) -> types.InlineKeyboardMarkup:
    keyboard = [
        [
            types.InlineKeyboardButton(text=i18n.get(FIND_MOVIE_BTN), callback_data="search_movie"),
        ],
        [
            types.InlineKeyboardButton(text=i18n.get(RECOMMEND_BTN), callback_data="suggest_movie"),
            types.InlineKeyboardButton(text=i18n.get(DOWNLOAD_BTN), callback_data="download_movie")
        ],
        [
            types.InlineKeyboardButton(text=i18n.get(WATCH_HISTORY_BTN), callback_data="watch_history"),
            types.InlineKeyboardButton(text=i18n.get(FAVORITES_BTN), callback_data="favorites"),
        ],
        [
            types.InlineKeyboardButton(text=i18n.get(OPTIONS_BTN), callback_data="options"),
        ]
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard)


@router.callback_query(F.data == "search_movie")
async def search_movie_handler(query: types.CallbackQuery, i18n: I18nContext):
    logger.info(f"[User {query.from_user.id}] Clicked 'Search Movie' button")

    keyboard = get_search_type_keyboard(i18n)
    
    await smart_edit_or_send(
        message=query,
        text=i18n.get(SEARCH_TYPE_QUESTION),
        reply_markup=keyboard
    )
    await query.answer()

@router.callback_query(F.data == "suggest_movie")
async def suggest_movie_handler(query: types.CallbackQuery, i18n: I18nContext):
    logger.info(f"[User {query.from_user.id}] Clicked 'Recommend Me' button")
    await query.answer(i18n.get(RECOMMENDATIONS_COMING_SOON), show_alert=True)



@router.callback_query(F.data == "watch_history")
async def watch_history_handler(query: types.CallbackQuery, i18n: I18nContext):
    logger.info(f"[User {query.from_user.id}] Clicked 'Watch History' button")
    await query.answer(i18n.get(WATCH_HISTORY_COMING_SOON), show_alert=True)


@router.callback_query(F.data == "favorites")
async def favorites_handler(query: types.CallbackQuery, i18n: I18nContext):
    logger.info(f"[User {query.from_user.id}] Clicked 'Favorites' button")
    await query.answer(i18n.get(FAVORITES_COMING_SOON), show_alert=True)


@router.callback_query(F.data == "options")
async def options_handler(query: types.CallbackQuery, i18n: I18nContext):
    logger.info(f"[User {query.from_user.id}] Clicked 'Options' button")
    await query.answer(i18n.get(OPTIONS_COMING_SOON), show_alert=True)

@router.callback_query(F.data == "download_movie")
async def download_movie_handler(query: types.CallbackQuery, i18n: I18nContext):
    logger.info(f"[User {query.from_user.id}] Clicked 'Download Movie' button")
    await query.answer(i18n.get(DOWNLOAD_COMING_SOON), show_alert=True)


# handler for back_to_main_menu_btn
@router.callback_query(F.data.startswith("back_to_main"))
async def back_to_main_menu_handler(query: types.CallbackQuery, i18n: I18nContext):
    logger.info(f"[User {query.from_user.id}] Clicked 'Back to Main Menu'")

    await SessionManager.clear_state(query.from_user.id)
    logger.info(f"[User {query.from_user.id}] session state was cleared in bot.handlers.main_menu_btns back_to_main_menu_handler")

    keyboard = get_main_menu_keyboard(i18n)

    await query.message.answer(
        i18n.get(BACK_TO_MAIN_MENU),
        reply_markup=keyboard
    )

    await query.answer()
from aiogram import Router, types, F
from aiogram.filters import CommandStart
from bot.utils.logger import Logger
from bot.utils.session_manager import SessionManager
from bot.keyboards.search_type_keyboard import get_search_type_keyboard

router = Router()
logger = Logger().get_logger()


# --- Main Menu Keyboard Generator ---
def get_main_menu_keyboard() -> types.InlineKeyboardMarkup:
    keyboard = [
        [
            types.InlineKeyboardButton(text="🎬 Find a movie", callback_data="search_movie"),
        ],
        [
            types.InlineKeyboardButton(text="💯 We recommend", callback_data="suggest_movie"),
            types.InlineKeyboardButton(text="📥 Download a movie", callback_data="download_movie")
        ],
        [
            types.InlineKeyboardButton(text="🧩 Watch History", callback_data="watch_history"),
            types.InlineKeyboardButton(text="⭐ Favorites", callback_data="favorites"),
        ],
        [
            types.InlineKeyboardButton(text="⚙️ Options", callback_data="options"),
            # types.InlineKeyboardButton(text="🚫 Ban List", callback_data="ban_list")
        ]
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard)


# --- Start Command Handler ---
@router.message(CommandStart())
async def start_handler(message: types.Message):
    logger.info(f"[User {message.from_user.id}] Triggered /start")

    keyboard = get_main_menu_keyboard()

    await message.answer(
        "👋 Welcome! I'm your Movie Assistant.\n\n"
        "Use the menu below to explore:",
        reply_markup=keyboard
    )


# --- Callback Queries for Main Menu (placeholders) ---

@router.callback_query(F.data == "search_movie")
async def search_movie_handler(query: types.CallbackQuery):
    logger.info(f"[User {query.from_user.id}] Clicked 'Search Movie' button")

    keyboard = get_search_type_keyboard()
    await query.message.edit_text(
        "🎯 How would you like to search for a movie?",
        reply_markup=keyboard
    )
    await query.answer()

@router.callback_query(F.data == "suggest_movie")
async def suggest_movie_handler(query: types.CallbackQuery):
    logger.info(f"[User {query.from_user.id}] Clicked 'Recommend Me' button")
    await query.answer("💯 Smart suggestions coming soon!", show_alert=True)


@router.callback_query(F.data == "watch_history")
async def watch_history_handler(query: types.CallbackQuery):
    logger.info(f"[User {query.from_user.id}] Clicked 'Watch History' button")
    await query.answer("🧩 Your watch history will be here soon!", show_alert=True)


@router.callback_query(F.data == "favorites")
async def favorites_handler(query: types.CallbackQuery):
    logger.info(f"[User {query.from_user.id}] Clicked 'Favorites' button")
    await query.answer("⭐ Your favorite movies will be stored here!", show_alert=True)


@router.callback_query(F.data == "options")
async def options_handler(query: types.CallbackQuery):
    logger.info(f"[User {query.from_user.id}] Clicked 'Options' button")
    await query.answer("⚙️ Options menu coming soon!", show_alert=True)
#
# @router.callback_query(F.data == "ban_list")
# async def ban_list_handler(query: types.CallbackQuery):
#     logger.info(f"[User {query.from_user.id}] Clicked 'Ban List' button")
#     await query.answer("🚫 Ban List coming soon!", show_alert=True)

@router.callback_query(F.data == "download_movie")
async def download_movie_handler(query: types.CallbackQuery):
    logger.info(f"[User {query.from_user.id}] Clicked 'Download Movie' button")
    await query.answer("📥 Download Movie coming soon!", show_alert=True)


# handler for back_to_main_menu_btn
@router.callback_query(F.data.startswith("back_to_main"))
async def back_to_main_menu_handler(query: types.CallbackQuery):
    logger.info(f"[User {query.from_user.id}] Clicked 'Back to Main Menu'")

    await SessionManager.clear_state(query.from_user.id)
    logger.info(f"[User {query.from_user.id}] session state was cleared in bot.handlers.main_menu_btns back_to_main_menu_handler")

    keyboard = get_main_menu_keyboard()

    await query.message.answer(
        "🏠 You're back at the main menu!",
        reply_markup=keyboard
    )

    await query.answer()
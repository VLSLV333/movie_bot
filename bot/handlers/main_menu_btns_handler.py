from aiogram import Router, types, F
from aiogram.filters import CommandStart
from bot.utils.logger import Logger
from aiogram.types import ForceReply, InlineKeyboardMarkup, InlineKeyboardButton
from bot.helpers.back_button import add_back_button
from bot.utils.session_manager import SessionManager
from bot.keyboards.search_type_keyboard import get_search_type_keyboard
from bot.utils.poll_from_hdrezka_extractor import poll_task_until_ready

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

#TODO:ADD THIS TEMPORARY FOR TESTING BOT BTN FOR MOVIE EXTRACTION
EXTRACT_API_URL = "https://moviebot.click/hd/extract"
MOVIE_URL = "https://hdrezka.ag/films/fiction/58225-bednye-neschastnye-2023.html"
USER_LANG = "ua"
import asyncio
from aiohttp import ClientSession
from urllib.parse import quote


@router.callback_query(F.data == "suggest_movie")
async def suggest_movie_handler(query: types.CallbackQuery):
    logger.info(f"[User {query.from_user.id}] Clicked 'Recommend Me' button")
    # await query.answer("💯 Smart suggestions coming soon!", show_alert=True)
    #TODO: WE WILL MAKE GIFS/PICTURES FOR USER TO SEE WE ARE PREPARING
    loading_gif_msg = await query.message.answer_animation(
        animation="https://media.giphy.com/media/hvRJCLFzcasrR4ia7z/giphy.gif",
        caption="🎬 Preparing your movie... Hang tight!"
    )
    await query.answer("🔍 Getting your movie ready...", show_alert=True)

    # 1. Trigger extraction
    async with ClientSession() as session:
        async with session.post(EXTRACT_API_URL, json={"url": MOVIE_URL, "lang": USER_LANG}) as resp:
            data = await resp.json()
            task_id = data.get("task_id")

    # 2. get config with .m3u8 and .vtt files for movie user selected
    config = await poll_task_until_ready(
    user_id=query.from_user.id,
    task_id=task_id,
    status_url="https://moviebot.click/hd/status",
    loading_gif_msg=loading_gif_msg,
    query=query
    )
    if not config:
#TODO: USER MUST NOT STUCK IN THIS SITUATION! SHOULD WE REPRAPER MOVIE? OR GO TO MAIN MENU OR TELL USER WE ARE NOT AVAILABLE NOW?
        await query.message.edit_text(
            "😕 Sorry, we couldn't extract the movie right now.\nTry again pls.",
            reply_markup=get_main_menu_keyboard())
        return

    # 3. Pick first dub that is not "одноголосый"
    selected_dub = None
    lang = list(config.keys())[0]
    for dub in config[lang].keys():
        if "одноголосый" not in dub.lower():
            selected_dub = dub
            break
    if not selected_dub:
        selected_dub = list(config[lang].keys())[0]

    watch_url = f"https://moviebot.click/hd/watch/{task_id}?lang={lang}&dub={quote(selected_dub)}"
    kb = [[types.InlineKeyboardButton(text="▶️ Watch", url=watch_url)]]
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)

    await loading_gif_msg.delete()
    await query.message.answer("🎬 Your movie is ready:", reply_markup=markup)


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
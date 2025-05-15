from aiogram import Router, types, F
import aiohttp
from bot.search.mirror_search_session import MirrorSearchSession
from bot.utils.session_manager import SessionManager
from bot.handlers.mirror_search_handler import show_mirror_batch, save_mirror_session
from bot.helpers.back_to_main_menu_btn import get_back_to_main_menu_keyboard
from bot.utils.logger import Logger

router = Router()
logger = Logger().get_logger()

# Your backend URL
BACKEND_BASE_URL = "http://your-backend-host.com"  # replace later with ENV

# ADMIN_ID to ping
ADMIN_CHAT_ID = 123456789  # replace with your real TG user ID

async def ping_admin_about_failure(bot, user_id: int, session: MirrorSearchSession, mirror_name: str):
    """
    Notify admin if extraction fails.
    """
    try:
        text = (
            f"⚠️ Extraction failed\n\n"
            f"User ID: {user_id}\n"
            f"Original Query: {session.original_query}\n"
            f"Movie ID: {session.movie_id}\n"
            f"Mirror: {mirror_name}"
        )
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=text)
    except Exception as e:
        logger.error(f"Failed to ping admin: {e}")

@router.callback_query(F.data == "confirm_final_movie")
async def confirm_final_movie(query: types.CallbackQuery):
    user_id = query.from_user.id

    session = await SessionManager.get_data(user_id)
    if not session or not session.get("mirror_search_session"):
        logger.warning("No session was found in final confirm!")
        await query.message.answer("😔 Your session expired. Please search again.", reply_markup=get_back_to_main_menu_keyboard())
        await query.answer()
        return

    mirror_session = MirrorSearchSession.from_dict(session["mirror_search_session"])

    if not mirror_session.confirmed_movie:
        logger.warning("No mirror_session was found in final confirm!")
        await query.message.answer("😔 Something went wrong. Please try again.", reply_markup=get_back_to_main_menu_keyboard())
        await query.answer()
        return

    movie_url = mirror_session.confirmed_movie.get("url")

    if not movie_url:
        logger.warning("No movie_url was found in final confirm!")
        await query.message.answer("😔 Movie link is missing. Please try again.", reply_markup=get_back_to_main_menu_keyboard())
        await query.answer()
        return

    #TODO: add image with bot almost done searching
    await query.message.answer("🛠 Final touch! Preparing your movie...")

    try:
        async with aiohttp.ClientSession() as session_client:
            async with session_client.post(f"{BACKEND_BASE_URL}/api/extract/{mirror_session.movie_id}", json={"url": movie_url}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == "ok":
                        # Extraction successful!
                        #TODO: create real link for user to watch
                        watch_url = f"https://yourfrontend.com/watch/{mirror_session.movie_id}"  # update later if needed
                        watch_btn = types.InlineKeyboardMarkup(
                            inline_keyboard=[
                                [types.InlineKeyboardButton(text="🎬 Start Watching", url=watch_url)]
                            ]
                        )
                        await query.message.answer("🎉 Movie is ready!", reply_markup=watch_btn)
                        await query.answer()
                        return

    except Exception as e:
        logger.error(f"Extraction request failed: {e}")

    # If we reach here → Extraction failed
    await query.message.answer("😔 This mirror was broken. Searching again...")

    # 1. Ping Admin
    mirror_name = mirror_session.mirrors[mirror_session.current_mirror_index]["mirror"]
    await ping_admin_about_failure(bot=query.bot, user_id=user_id, session=mirror_session, mirror_name=mirror_name)

    # 2. remove broken mirror
    try:
        broken_mirror = mirror_session.mirrors.pop(mirror_session.current_mirror_index)
        logger.warning(f"Removed broken mirror: {broken_mirror.get('mirror')}")
    except IndexError:
        logger.error("Tried to remove mirror but index was out of range.")

    mirror_session.current_result_index = 0
    mirror_session.confirmed_movie = None

    await save_mirror_session(user_id, mirror_session)

    # 3. Retry search
    await show_mirror_batch(query, mirror_session)
    await query.answer()

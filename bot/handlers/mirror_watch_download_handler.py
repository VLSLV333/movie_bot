from aiogram import Router, types, F
from aiohttp import ClientSession
from urllib.parse import quote
from bot.utils.logger import Logger
from bot.utils.poll_from_hdrezka_extractor import poll_task_until_ready
from bot.handlers.main_menu_btns_handler import get_main_menu_keyboard
from bot.utils.redis_client import RedisClient

router = Router()
logger = Logger().get_logger()

EXTRACT_API_URL = "https://moviebot.click/hd/extract"
STATUS_API_URL = "https://moviebot.click/hd/status"
USER_LANG = "ua"  # TODO: Replace with dynamic language from session/user db

# Handler for "▶️ Watch"
@router.callback_query(F.data.startswith("watch_mirror:"))
async def watch_mirror_handler(query: types.CallbackQuery):
    user_id = query.from_user.id
    stream_id = query.data.split("watch_mirror:")[1]

    redis = RedisClient.get_client()
    movie_url = await redis.get(f"mirror_url:{stream_id}")

    if not movie_url:
        await query.answer("⚠️ Movie link expired. Try searching again.", show_alert=True)
        await query.message.answer("❌ This movie link is no longer valid. Please re-search from the main menu.",
                                   reply_markup=get_main_menu_keyboard())
        return

    logger.info(f"[User {user_id}] Requested ▶️ Watch for: {movie_url}")

    #TODO: WE WILL MAKE BOT PERSON GIFS/PICTURES FOR USER TO SEE WE ARE PREPARING
    loading_gif_msg = await query.message.answer_animation(
        animation="https://media.giphy.com/media/hvRJCLFzcasrR4ia7z/giphy.gif",
        caption="🎬 Preparing your movie... Hang tight!"
    )
    await query.answer("🔍 Extracting movie link...", show_alert=True)

    async with ClientSession() as session:
        async with session.post(EXTRACT_API_URL, json={"url": movie_url, "lang": USER_LANG}) as resp:
            data = await resp.json()
            task_id = data.get("task_id")

    config = await poll_task_until_ready(
        user_id=user_id,
        task_id=task_id,
        status_url=STATUS_API_URL,
        loading_gif_msg=loading_gif_msg,
        query=query
    )
    if not config:
        await query.message.answer(
            "😕 Sorry, we couldn't extract the movie right now.\nTry again pls.",
            reply_markup=get_main_menu_keyboard()
        )
        return

    # Choose best dub
    selected_dub = None
    lang = list(config.keys())[0]
    for dub in config[lang]:
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

@router.callback_query(F.data.startswith("download_mirror:"))
async def download_mirror_handler(query: types.CallbackQuery):
    # TODO: identical logic to watch, but sends download link instead of watch
    await query.answer("💾 Download support coming soon!", show_alert=True)

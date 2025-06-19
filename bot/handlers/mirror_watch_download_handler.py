import time
import os
import hmac
import hashlib
import json
from aiogram import Router, types, F
from aiohttp import ClientSession
from urllib.parse import quote
from bot.utils.logger import Logger
from bot.utils.poll_from_hdrezka_to_watch import poll_watch_until_ready
from bot.utils.poll_from_hdrezka_to_download import poll_download_until_ready
from bot.handlers.main_menu_btns_handler import get_main_menu_keyboard
from bot.utils.redis_client import RedisClient
from hashlib import md5
from bot.utils.signed_token_manager import SignedTokenManager
from bot.utils.translate_dub_to_ua import translate_dub_to_ua

router = Router()
logger = Logger().get_logger()

EXTRACT_API_URL = "https://moviebot.click/hd/extract"
STATUS_API_URL = "https://moviebot.click/hd/status/watch"
SCRAP_ALL_DUBS = "https://moviebot.click/hd/alldubs"

ALL_DUBS_FOR_TMDB_ID = "https://moviebot.click/all_db_dubs"

USER_LANG = "ua"  # TODO: Replace with dynamic language from session/user db

def generate_token(tmdb_id: int, lang: str, dub: str) -> str:
    base = f"{tmdb_id}:{lang}:{dub}"
    return md5(base.encode()).hexdigest()[:12]

@router.callback_query(F.data.startswith("watch_mirror:"))
async def watch_mirror_handler(query: types.CallbackQuery):
    if query is None or query.data is None:
        logger.error("CallbackQuery or its data is None in watch_mirror_handler")
        return
    user_id = query.from_user.id
    stream_id = query.data.split("watch_mirror:")[1]

    redis = RedisClient.get_client()
    movie_data_raw = await redis.get(f"mirror_url:{stream_id}")

    if not movie_data_raw:
        if query.message is not None:
            await query.answer("⚠️ Movie link expired. Try searching again.", show_alert=True)
            await query.message.answer("❌ This movie link is no longer valid. Please re-search from the main menu.",
                                       reply_markup=get_main_menu_keyboard())
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text="❌ This movie link is no longer valid. Please re-search from the main menu.",
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                logger.error("query or query.bot is None, cannot send message to user.")
        return

    try:
        movie_data = json.loads(movie_data_raw)
        movie_url = movie_data.get("url")
    except Exception as e:
        logger.error(f"[User {user_id}] Failed to parse cached mirror data: {e}")
        if query.message is not None:
            await query.message.answer("⚠️ We lost movie somewhere along the way!:(. Please re-search from the main menu.",
                                       reply_markup=get_main_menu_keyboard())
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text="⚠️ We lost movie somewhere along the way!:(. Please re-search from the main menu.",
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                logger.error("query or query.bot is None, cannot send message to user.")
        return

    logger.info(f"[User {user_id}] Requested ▶️ Watch for: {movie_url}")

    #TODO: WE WILL MAKE BOT PERSON GIFS/PICTURES FOR USER TO SEE WE ARE PREPARING
    if query.message is not None:
        loading_gif_msg = await query.message.answer_animation(
            animation="https://media.giphy.com/media/hvRJCLFzcasrR4ia7z/giphy.gif",
            caption="🎬 Preparing your movie... Hang tight!"
        )
    else:
        if query is not None and getattr(query, 'bot', None) is not None:
            loading_gif_msg = await query.bot.send_animation(  # type: ignore
                chat_id=query.from_user.id,
                animation="https://media.giphy.com/media/hvRJCLFzcasrR4ia7z/giphy.gif",
                caption="🎬 Preparing your movie... Hang tight!"
            )
        else:
            logger.error("query or query.bot is None, cannot send animation to user.")
    await query.answer("🔍 Extracting movie link...", show_alert=True)

    async with ClientSession() as session:
        async with session.post(EXTRACT_API_URL, json={"url": movie_url, "lang": USER_LANG}) as resp:
            data = await resp.json()
            task_id = data.get("task_id")

    config = await poll_watch_until_ready(
        user_id=user_id,
        task_id=task_id,
        status_url=STATUS_API_URL,
        loading_gif_msg=loading_gif_msg,
        query=query
    )
    if not config:
        try:
            await loading_gif_msg.delete()
        except Exception as e:
            logger.error(f"Error while deleting gif: {e}")
        if query.message is not None:
            await query.message.answer(
                "😕 Sorry, we couldn't extract the movie right now.\nTry again pls.",
                reply_markup=get_main_menu_keyboard()
            )
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text="😕 Sorry, we couldn't extract the movie right now.\nTry again pls.",
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                logger.error("query or query.bot is None, cannot send message to user.")
        return

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

    try:
        await loading_gif_msg.delete()
    except Exception as e:
        logger.error(f"Error while deleting gif: {e}")

    if query.message is not None:
        await query.message.answer("🎬 Your content is ready:", reply_markup=markup)
    else:
        if query is not None and getattr(query, 'bot', None) is not None:
            await query.bot.send_message(  # type: ignore
                chat_id=query.from_user.id,
                text="🎬 Your content is ready:",
                reply_markup=markup
            )
        else:
            logger.error("query or query.bot is None, cannot send message to user.")

@router.callback_query(F.data.startswith("download_mirror:"))
async def download_mirror_handler(query: types.CallbackQuery):
    if query is None or query.data is None:
        logger.error("CallbackQuery or its data is None in download_mirror_handler")
        return
    user_id = query.from_user.id
    stream_id = query.data.split("download_mirror:")[1]

    redis = RedisClient.get_client()
    movie_data_raw = await redis.get(f"mirror_url:{stream_id}")

    if not movie_data_raw:
        if query.message is not None:
            await query.message.answer("❌ This movie link is no longer valid. Please re-search from the main menu.",
                                       reply_markup=get_main_menu_keyboard())
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text="❌ This movie link is no longer valid. Please re-search from the main menu.",
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                logger.error("query or query.bot is None, cannot send message to user.")
        return

    try:
        movie_data = json.loads(movie_data_raw)
        movie_url = movie_data.get("url")
        tmdb_id = movie_data.get("tmdb_id")
    except Exception as e:
        logger.error(f"[User {user_id}] Failed to parse cached mirror data: {e}")
        if query.message is not None:
            await query.message.answer("⚠️ We lost movie somewhere along the way!:(. Please re-search from the main menu.",
                                       reply_markup=get_main_menu_keyboard())
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text="⚠️ We lost movie somewhere along the way!:(. Please re-search from the main menu.",
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                logger.error("query or query.bot is None, cannot send message to user.")
        return

    logger.info(f"[User {user_id}] Requested 💾 Download for TMDB_ID={tmdb_id}, stream={movie_url}")

    # Step 1: Check existing downloads
    async with ClientSession() as session:
        async with session.get(ALL_DUBS_FOR_TMDB_ID, params={"tmdb_id": tmdb_id, "lang": USER_LANG}) as resp:
            list_of_available_dubs_for_tmdb_id_and_lang = await resp.json()

            await redis.set(f"ready_to_download_dubs_list:{stream_id}", json.dumps({
                "dubs_list": list_of_available_dubs_for_tmdb_id_and_lang,
                "lang": USER_LANG,
            }), ex=3600)

    if list_of_available_dubs_for_tmdb_id_and_lang:
        # Offer quick watch for first found dub
        kb = []

        for file in list_of_available_dubs_for_tmdb_id_and_lang:
            dub = file['dub']
            token = generate_token(tmdb_id, USER_LANG, dub)
            logger.info(f"Generated token {token} for TMDB_ID={tmdb_id}, dub={dub}, lang={USER_LANG}")

            await redis.set(f"downloaded_dub_info:{token}", json.dumps({
                "tmdb_id": tmdb_id,
                "lang": USER_LANG,
                "dub": dub,
                "tg_user_id": user_id
            }), ex=3600)

            emoji = "🇺🇦" if USER_LANG == 'ua' else "🎙"
            display_dub = translate_dub_to_ua(dub) if USER_LANG == 'ua' else dub
            kb.append([
                types.InlineKeyboardButton(
                    text=f"{emoji} {display_dub} dub",
                    callback_data=f"watch_downloaded:{token}"
                )
            ])

        kb.append([
            types.InlineKeyboardButton(
                text="📥 Download with another dub",
                callback_data=f"fetch_dubs:{stream_id}"
            )
        ])

        markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
        if query.message is not None:
            await query.message.answer("🎉 We already have this movie! Choose an option:", reply_markup=markup)
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text="🎉 We already have this movie! Choose an option:",
                    reply_markup=markup
                )
            else:
                logger.error("query or query.bot is None, cannot send message to user.")
        await query.answer()
        return

    if not list_of_available_dubs_for_tmdb_id_and_lang:
        movie_data = json.loads(movie_data_raw)
        logger.info(f"[User {user_id}] No existing dubs found. Triggering dub selection flow.")
        markup = types.InlineKeyboardMarkup(inline_keyboard=[[
            types.InlineKeyboardButton(
                text="📥 Choose dub to download",
                callback_data=f"fetch_dubs:{stream_id}"
            )
        ]])
        if query.message is not None:
            await query.message.answer(f"{movie_data['title']} was never downloaded before! Be the first:", reply_markup=markup)
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text=f"{movie_data['title']} was never downloaded before! Be the first:",
                    reply_markup=markup
                )
            else:
                logger.error("query or query.bot is None, cannot send message to user.")
        await query.answer()
        return


@router.callback_query(F.data.startswith("fetch_dubs:"))
async def fetch_dubs_handler(query: types.CallbackQuery):
    if query is None or query.data is None:
        logger.error("CallbackQuery or its data is None in fetch_dubs_handler")
        return
    loading_msg = await query.message.answer_animation(  # type: ignore
        animation="https://media.giphy.com/media/hvRJCLFzcasrR4ia7z/giphy.gif",
        caption="🔍 Checking downloaded versions & dubs..."
    )

    user_id = query.from_user.id
    stream_id = query.data.split("fetch_dubs:")[1]

    redis = RedisClient.get_client()
    movie_data_raw = await redis.get(f"mirror_url:{stream_id}")
    download_task = await redis.get(f"ready_to_download_dubs_list:{stream_id}")

    if not movie_data_raw or not download_task:
        if query.message is not None:
            await query.message.answer("❌ This movie link is no longer valid. Please re-search from the main menu.",
                                       reply_markup=get_main_menu_keyboard())
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text="❌ This movie link is no longer valid. Please re-search from the main menu.",
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                logger.error("query or query.bot is None, cannot send message to user.")
        return

    try:
        movie_data = json.loads(movie_data_raw)
        movie_url = movie_data.get("url")
        tmdb_id = movie_data.get("tmdb_id")
        download_task_data = json.loads(download_task)
        ready_dubs_list = download_task_data['dubs_list']
        download_task_lang = download_task_data['lang']

    except Exception as e:
        logger.error(f"[User {user_id}] Failed to parse cached  mirror data: {e}")
        await loading_msg.delete()
        if query.message is not None:
            await query.message.answer("⚠️ We lost movie somewhere along the way!:(. Please re-search from the main menu.",
                                       reply_markup=get_main_menu_keyboard())
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text="⚠️ We lost movie somewhere along the way!:(. Please re-search from the main menu.",
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                logger.error("query or query.bot is None, cannot send message to user.")
        return

    try:
        async with ClientSession() as session:
            async with session.post(SCRAP_ALL_DUBS, json={"url": movie_url, "lang": download_task_lang}) as resp:
                dubs_scrapper_result = await resp.json()
    except Exception as e:
        logger.error(f"[User {user_id}] Failed to get dubs: {e}")
        await loading_msg.delete()
        if query.message is not None:
            await query.message.answer("⚠️ Try searching movie from beginning pls, or watch online. We will fix this!",
                                       reply_markup=get_main_menu_keyboard())
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text="⚠️ Try searching movie from beginning pls, or watch online. We will fix this!",
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                logger.error("query or query.bot is None, cannot send message to user.")
        return

    if not dubs_scrapper_result['dubs']:
        await loading_msg.delete()
        if query.message is not None:
            await query.message.answer("⚠️ No dubs available in your language for this movie, we are sorry:( Will try to find this movie in your language and upload!", reply_markup=get_main_menu_keyboard())
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text="⚠️ No dubs available in your language for this movie, we are sorry:( Will try to find this movie in your language and upload!",
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                logger.error("query or query.bot is None, cannot send message to user.")
        return

    if dubs_scrapper_result['message']:
        if query.message is not None:
            await query.message.answer(dubs_scrapper_result['message'])
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text=dubs_scrapper_result['message']
                )
            else:
                logger.error("query or query.bot is None, cannot send message to user.")


    if dubs_scrapper_result['dubs'] == ['default_ru']:
        token = generate_token(tmdb_id, USER_LANG, 'default_ru')
        logger.info(f"Generated token {token} for TMDB_ID={tmdb_id}, dub=default_ru, lang={download_task_lang}")
        await redis.set(f"selected_dub_info:{token}", json.dumps({
            "tmdb_id": tmdb_id,
            "lang": download_task_lang,
            "dub": 'default_ru',
            "movie_url": movie_url
        }), ex=3600)

        kb = [[types.InlineKeyboardButton(
            text="📥 Download default dub",
            callback_data=f"select_dub:{token}"
        )]]
        await loading_msg.delete()
        await query.message.answer("🎙 This movie has only one default dub:",
                                   reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))
        return

    already_downloaded_dubs = {file['dub'] for file in ready_dubs_list}
    available_dubs_can_be_downloaded = [dub for dub in dubs_scrapper_result['dubs'] if dub not in already_downloaded_dubs]

    kb = []

    if ready_dubs_list:
        kb.append([types.InlineKeyboardButton(text="📁 Already available dubs:", callback_data="noop")])
        for dub_dict in ready_dubs_list:
            dub = dub_dict['dub']
            token = generate_token(tmdb_id, USER_LANG, dub)
            logger.info(f"Generated token {token} for TMDB_ID={tmdb_id}, dub={dub}, lang={download_task_lang}")

            await redis.set(f"downloaded_dub_info:{token}", json.dumps({
                "tmdb_id": tmdb_id,
                "lang": download_task_lang,
                "dub": dub,
                "tg_user_id": user_id
            }), ex=3600)

            emoji = "🇺🇦" if USER_LANG == 'ua' else "🎙"
            display_dub = translate_dub_to_ua(dub) if USER_LANG == 'ua' else dub
            kb.append([
                types.InlineKeyboardButton(
                    text=f"{emoji} {display_dub} dub",
                    callback_data=f"watch_downloaded:{token}"
                )
            ])

    if available_dubs_can_be_downloaded:
        kb.append([types.InlineKeyboardButton(text="📥 Available to download:", callback_data="noop")])
        for dub in available_dubs_can_be_downloaded:
            emoji = "🇺🇦" if USER_LANG == 'ua' else "🎙"
            text = emoji +  f" {translate_dub_to_ua(dub)}" if USER_LANG == 'ua' else f" {dub}"
            token = generate_token(tmdb_id, USER_LANG, dub)
            logger.info(f"Generated token {token} for TMDB_ID={tmdb_id}, dub={dub}, lang={download_task_lang}")
            await redis.set(f"selected_dub_info:{token}", json.dumps({
                "tmdb_id": tmdb_id,
                "lang": download_task_lang,
                "dub": dub,
                "movie_url": movie_url
            }), ex=3600)

            kb.append([types.InlineKeyboardButton(text=text, callback_data=f"select_dub:{token}")])

    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    await loading_msg.delete()
    await query.message.answer("🎙 Choose a dub to download (or fast watch one we already have in Delivery Bot):",
                               reply_markup=markup)  # type: ignore
    await query.answer()  # type: ignore

@router.callback_query(F.data.startswith("watch_downloaded:"))
async def watch_downloaded_handler(query: types.CallbackQuery):
    user_id = query.from_user.id
    token = query.data.split("watch_downloaded:")[1]  # type: ignore

    signed = f"{token}:{hmac.new(os.getenv('BACKEND_DOWNLOAD_SECRET').encode(), token.encode(), hashlib.sha256).hexdigest()[:10]}"  # type: ignore
    delivery_bot_link = f"https://t.me/deliv3ry_bot?start=2:{signed}"

    await query.message.answer(
        "🎬 Your content is ready to watch!",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text="▶️ Get movie from Delivery Bot", url=delivery_bot_link)]
            ]
        )
    )  # type: ignore
    await query.answer()  # type: ignore

@router.callback_query(F.data.startswith("select_dub:"))
async def select_dub_handler(query: types.CallbackQuery):
    if query is None or query.data is None:
        logger.error("CallbackQuery or its data is None in select_dub_handler")
        return
    await query.answer()
    user_id = query.from_user.id
    token = query.data.split("select_dub:")[1]
    redis = RedisClient.get_client()

    selected_data_json = await redis.get(f"selected_dub_info:{token}")

    if not selected_data_json:
        if query.message is not None:
            await query.message.answer("❌ This dub selection expired. Please start again from the begining:)", reply_markup=get_main_menu_keyboard())
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text="❌ This dub selection expired. Please start again from the begining:)",
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                logger.error("query or query.bot is None, cannot send message to user.")
        return

    try:
        selected_data = json.loads(selected_data_json)
        tmdb_id = selected_data["tmdb_id"]
        lang = selected_data["lang"]
        dub = selected_data["dub"]
        movie_url = selected_data["movie_url"]
    except Exception as e:
        logger.error(f"[User {user_id}] Failed to parse selected dub token: {e}")
        if query.message is not None:
            await query.message.answer("⚠️ Could not process dub info, sorry:( Please start again from the begining", reply_markup=get_main_menu_keyboard())
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text="⚠️ Could not process dub info, sorry:( Please start again from the begining",
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                logger.error("query or query.bot is None, cannot send message to user.")
        return

    # Create secure download token
    payload = {
        "tmdb_id": tmdb_id,
        "lang": lang,
        "dub": dub,
        "exp": int(time.time()) + 600,
        "tg_user_id": user_id,
        "movie_url": movie_url
    }

    data_b64, sig = SignedTokenManager.generate_token(payload)
    download_url = f"https://moviebot.click/hd/download?data={data_b64}&sig={sig}"

    # Notify user we're starting
    if query.message is not None:
        loading_msg = await query.message.answer_animation(
            animation="https://media.giphy.com/media/hvRJCLFzcasrR4ia7z/giphy.gif",
            caption="⏳ I have added you to queue for download...\nThis may take 5–10 minutes when it is yours turn..."
        )
    else:
        if query is not None and getattr(query, 'bot', None) is not None:
            loading_msg = await query.bot.send_animation(
                chat_id=query.from_user.id,
                animation="https://media.giphy.com/media/hvRJCLFzcasrR4ia7z/giphy.gif",
                caption="⏳ I have added you to queue for download...\nThis may take 5–10 minutes when it is yours turn..."
            )  # type: ignore
        else:
            logger.error("query or query.bot is None, cannot send animation to user.")

    try:
        async with ClientSession() as session:
            async with session.get(download_url) as resp:
                if resp.status != 200:
                    await loading_msg.delete()
                    if query.message is not None:
                        await query.message.answer(
                            "❌ Failed to trigger download, sorry:( Please start again from the begining",
                            reply_markup=get_main_menu_keyboard())
                    else:
                        if query is not None and getattr(query, 'bot', None) is not None:
                            await query.bot.send_message(  # type: ignore
                                chat_id=query.from_user.id,
                                text="❌ Failed to trigger download, sorry:( Please start again from the begining",
                                reply_markup=get_main_menu_keyboard()
                            )
                        else:
                            logger.error("query or query.bot is None, cannot send message to user.")
                    return

                backend_response = await resp.json()
                task_id = backend_response.get("task_id")
                if not task_id:
                    await loading_msg.delete()
                    if query.message is not None:
                        await query.message.answer(
                            "❌ Failed to trigger download, sorry:( Please start again from the begining",
                            reply_markup=get_main_menu_keyboard())
                    else:
                        if query is not None and getattr(query, 'bot', None) is not None:
                            await query.bot.send_message(  # type: ignore
                                chat_id=query.from_user.id,
                                text="❌ Failed to trigger download, sorry:( Please start again from the begining",
                                reply_markup=get_main_menu_keyboard()
                            )
                        else:
                            logger.error("query or query.bot is None, cannot send message to user.")
                    return

        result = await poll_download_until_ready(
            user_id=user_id,
            task_id=task_id,
            status_url="https://moviebot.click/hd/status/download",
            loading_msg=loading_msg,
            query=query,
            bot=query.bot
        )

        if result:
            signed_task_id = f"{task_id}:{hmac.new(os.getenv('BACKEND_DOWNLOAD_SECRET').encode(), task_id.encode(), hashlib.sha256).hexdigest()[:10]}"  # type: ignore
            delivery_bot_link = f"https://t.me/deliv3ry_bot?start=1:{signed_task_id}"
            if query.message is not None:
                await query.message.answer(
                    "🎬 Your content is ready!\n\n📦 To receive it, start delivery bot👇",
                    reply_markup=types.InlineKeyboardMarkup(
                        inline_keyboard=[
                            [types.InlineKeyboardButton(text="🎁 Open Delivery Bot", url=delivery_bot_link)]
                        ]
                    )
                )
            else:
                if query is not None and getattr(query, 'bot', None) is not None:
                    await query.bot.send_message(  # type: ignore
                        chat_id=query.from_user.id,
                        text="🎬 Your content is ready!\n\n📦 To receive it, start delivery bot👇",
                        reply_markup=types.InlineKeyboardMarkup(
                            inline_keyboard=[
                                [types.InlineKeyboardButton(text="🎁 Open Delivery Bot", url=delivery_bot_link)]
                            ]
                        )
                    )
                else:
                    logger.error("query or query.bot is None, cannot send message to user.")

    except Exception as e:
        logger.error(f"[User {user_id}] Failed during download flow: {e}")
        try:
            await loading_msg.delete()
        except Exception as e:
            logger.error(f"[User {user_id}] Failed to delete loading message at the end of download flow: {e}")
        if query.message is not None:
            await query.message.answer("⚠️ Unexpected error during download. Try again later.",
                                       reply_markup=get_main_menu_keyboard())
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text="⚠️ Unexpected error during download. Try again later.",
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                logger.error("query or query.bot is None, cannot send message to user.")

@router.callback_query(F.data == "noop")
async def noop_handler(query: types.CallbackQuery):
    await query.answer()
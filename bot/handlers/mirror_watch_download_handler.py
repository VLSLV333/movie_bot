import time
import os
import hmac
import hashlib
import json
from aiogram import Router, types, F
from aiogram.utils.i18n import gettext
from aiohttp import ClientSession
from urllib.parse import quote
from bot.utils.logger import Logger
from bot.locales.keys import (
    MOVIE_LINK_NO_LONGER_VALID, LOST_MOVIE_DATA_RESEARCH,
    PREPARING_MOVIE_DUBS_WATCH, SORRY_COULDNT_EXTRACT_MOVIE_TRY_AGAIN,
    START_WATCHING_BTN, MOVIE_READY_TO_WATCH, TEXT_DUBS_READY_TO_DOWNLOAD,
    DOWNLOAD_ANOTHER_DUB, ALREADY_HAVE_MOVIE, CHECKING_DOWNLOADED_VERSIONS_DUBS,
    CHOOSE_DUB_TO_DOWNLOAD, MOVIE_NEVER_DOWNLOADED_BEFORE, TRY_SEARCHING_FROM_BEGINNING,
    NO_DUBS_AVAILABLE_IN_LANGUAGE, DOWNLOAD_DEFAULT_DUB, MOVIE_HAS_ONLY_DEFAULT_DUB,
    ALREADY_AVAILABLE_DUBS, AVAILABLE_TO_DOWNLOAD, CHOOSE_DUB_TO_DOWNLOAD_OR_WATCH,
    MOVIE_READY_TO_WATCH_DELIVERY, GET_MOVIE_FROM_DELIVERY_BOT, MOVIE_READY_START_DELIVERY_BOT,
    OPEN_DELIVERY_BOT, DUB_SELECTION_EXPIRED, COULD_NOT_PROCESS_DUB_INFO,
    ADDED_TO_DOWNLOAD_QUEUE, FAILED_TO_TRIGGER_DOWNLOAD, UNEXPECTED_ERROR_DURING_DOWNLOAD, DOWNLOAD_LIMIT,
    DUPLICATE_DOWNLOAD, ONLY_ONE_DUB, NO_DUBS_FOR_LANG, NO_UA_DUBS
)
from bot.utils.poll_from_hdrezka_to_watch import poll_watch_until_ready
from bot.utils.poll_from_hdrezka_to_download import poll_download_until_ready
from bot.handlers.main_menu_btns_handler import get_main_menu_keyboard
from bot.utils.redis_client import RedisClient
from hashlib import md5
from bot.utils.signed_token_manager import SignedTokenManager
from bot.utils.translate_dub_to_ua import translate_dub_to_ua
from bot.utils.user_service import UserService

router = Router()
logger = Logger().get_logger()

EXTRACT_API_URL = "https://moviebot.click/hd/extract"
STATUS_API_URL = "https://moviebot.click/hd/status/watch"
SCRAP_ALL_DUBS = "https://moviebot.click/hd/alldubs"

ALL_DUBS_FOR_TMDB_ID = "https://moviebot.click/all_db_dubs"

def generate_token(tmdb_id: int, lang: str, dub: str) -> str:
    base = f"{tmdb_id}:{lang}:{dub}"
    return md5(base.encode()).hexdigest()[:12]

@router.callback_query(F.data.startswith("watch_mirror:"))
async def watch_mirror_handler(query: types.CallbackQuery):
    if query is None or query.data is None:
        logger.error("CallbackQuery or its data is None in watch_mirror_handler")
        return
    user_id = query.from_user.id
    await query.answer()
    
    # Get user's preferred language
    user_lang = await UserService.get_user_movies_language(user_id)
    
    stream_id = query.data.split("watch_mirror:")[1]

    redis = RedisClient.get_client()
    movie_data_raw = await redis.get(f"mirror_url:{stream_id}")

    if not movie_data_raw:
        if query.message is not None:
            await query.message.answer(gettext(MOVIE_LINK_NO_LONGER_VALID),
                                       reply_markup=get_main_menu_keyboard())
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text=gettext(MOVIE_LINK_NO_LONGER_VALID),
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                logger.error("query or query.bot is None, cannot send message to user.")
        return

    try:
        movie_data = json.loads(movie_data_raw)
        movie_url = movie_data.get("url")
        movie_title = movie_data.get("title")
    except Exception as e:
        logger.error(f"[User {user_id}] Failed to parse cached mirror data: {e}")
        if query.message is not None:
            await query.message.answer(gettext(LOST_MOVIE_DATA_RESEARCH),
                                       reply_markup=get_main_menu_keyboard())
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text=gettext(LOST_MOVIE_DATA_RESEARCH),
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
            caption=gettext(PREPARING_MOVIE_DUBS_WATCH)
        )
    else:
        if query is not None and getattr(query, 'bot', None) is not None:
            loading_gif_msg = await query.bot.send_animation(  # type: ignore
                chat_id=query.from_user.id,
                animation="https://media.giphy.com/media/hvRJCLFzcasrR4ia7z/giphy.gif",
                caption=gettext(PREPARING_MOVIE_DUBS_WATCH)
            )
        else:
            logger.error("query or query.bot is None, cannot send animation to user.")

    async with ClientSession() as session:
        async with session.post(EXTRACT_API_URL, json={"url": movie_url, "lang": user_lang}) as resp:
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
        # user interaction handled by poll_watch_until_ready
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
    kb = [[types.InlineKeyboardButton(text=gettext(START_WATCHING_BTN), url=watch_url)]]
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)

    try:
        await loading_gif_msg.delete()
    except Exception as e:
        logger.error(f"Error while deleting gif: {e}")

    if query.message is not None:
        await query.message.answer(gettext(MOVIE_READY_TO_WATCH).format(movie_title=movie_title), reply_markup=markup)
    else:
        if query is not None and getattr(query, 'bot', None) is not None:
            await query.bot.send_message(  # type: ignore
                chat_id=query.from_user.id,
                text=gettext(MOVIE_READY_TO_WATCH).format(movie_title=movie_title),
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
    await query.answer()
    
    # Get user's preferred language
    user_lang = await UserService.get_user_movies_language(user_id)
    
    stream_id = query.data.split("download_mirror:")[1]

    redis = RedisClient.get_client()
    movie_data_raw = await redis.get(f"mirror_url:{stream_id}")

    if not movie_data_raw:
        if query.message is not None:
            await query.message.answer(gettext(MOVIE_LINK_NO_LONGER_VALID),
                                       reply_markup=get_main_menu_keyboard())
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text=gettext(MOVIE_LINK_NO_LONGER_VALID),
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                logger.error("query or query.bot is None, cannot send message to user.")
        return

    try:
        movie_data = json.loads(movie_data_raw)
        movie_url = movie_data.get("url")
        tmdb_id = movie_data.get("tmdb_id")
        movie_title = movie_data.get("title")
        movie_poster = movie_data.get("poster")
    except Exception as e:
        logger.error(f"[User {user_id}] Failed to parse cached mirror data: {e}")
        if query.message is not None:
            await query.message.answer(gettext(LOST_MOVIE_DATA_RESEARCH),
                                       reply_markup=get_main_menu_keyboard())
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text=gettext(LOST_MOVIE_DATA_RESEARCH),
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                logger.error("query or query.bot is None, cannot send message to user.")
        return

    logger.info(f"[User {user_id}] Requested 💾 Download for TMDB_ID={tmdb_id}, stream={movie_url}")

    # Step 1: Check existing downloads
    async with ClientSession() as session:
        async with session.get(ALL_DUBS_FOR_TMDB_ID, params={"tmdb_id": tmdb_id, "lang": user_lang}) as resp:
            list_of_available_dubs_for_tmdb_id_and_lang = await resp.json()

            await redis.set(f"ready_to_download_dubs_list:{stream_id}", json.dumps({
                "dubs_list": list_of_available_dubs_for_tmdb_id_and_lang,
                "lang": user_lang,
            }), ex=3600)

    if list_of_available_dubs_for_tmdb_id_and_lang:
        # Offer quick watch for first found dub
        kb = []

        for file in list_of_available_dubs_for_tmdb_id_and_lang:

            dub = file['dub']
            token = generate_token(tmdb_id, user_lang, dub)
            logger.info(f"Generated token {token} for TMDB_ID={tmdb_id}, dub={dub}, lang={user_lang}")

            await redis.set(f"downloaded_dub_info:{token}", json.dumps({
                "tmdb_id": tmdb_id,
                "lang": user_lang,
                "dub": dub,
                "tg_user_id": user_id,
                "movie_title": movie_title,
                "movie_poster": movie_poster,
                "movie_url": movie_url
            }), ex=3600)

            emoji = "🇺🇦" if user_lang == 'uk' else "🎙"
            display_dub = translate_dub_to_ua(dub) if user_lang == 'uk' else dub
            kb.append([
                types.InlineKeyboardButton(
                    text=gettext(TEXT_DUBS_READY_TO_DOWNLOAD).format(emoji=emoji, display_dub=display_dub),
                    callback_data=f"watch_downloaded:{token}"
                )
            ])

        kb.append([
            types.InlineKeyboardButton(
                text=gettext(DOWNLOAD_ANOTHER_DUB),
                callback_data=f"fetch_dubs:{stream_id}"
            )
        ])

        markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
        if query.message is not None:
            await query.message.answer(gettext(ALREADY_HAVE_MOVIE), reply_markup=markup)
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text=gettext(ALREADY_HAVE_MOVIE),
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
                text=gettext(CHOOSE_DUB_TO_DOWNLOAD),
                callback_data=f"fetch_dubs:{stream_id}"
            )
        ]])
        if query.message is not None:
            await query.message.answer(gettext(MOVIE_NEVER_DOWNLOADED_BEFORE).format(title=movie_data['title']), reply_markup=markup)
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text=gettext(MOVIE_NEVER_DOWNLOADED_BEFORE).format(title=movie_data['title']),
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
        caption=gettext(CHECKING_DOWNLOADED_VERSIONS_DUBS)
    )

    user_id = query.from_user.id
    
    # Get user's preferred language
    user_lang = await UserService.get_user_movies_language(user_id)
    
    stream_id = query.data.split("fetch_dubs:")[1]

    redis = RedisClient.get_client()
    movie_data_raw = await redis.get(f"mirror_url:{stream_id}")
    download_task = await redis.get(f"ready_to_download_dubs_list:{stream_id}")

    if not movie_data_raw or not download_task:
        if query.message is not None:
            await query.message.answer(gettext(MOVIE_LINK_NO_LONGER_VALID),
                                       reply_markup=get_main_menu_keyboard())
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text=gettext(MOVIE_LINK_NO_LONGER_VALID),
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                logger.error("query or query.bot is None, cannot send message to user.")
        return

    try:
        movie_data = json.loads(movie_data_raw)
        movie_url = movie_data.get("url")
        tmdb_id = movie_data.get("tmdb_id")
        movie_title = movie_data.get("title")
        movie_poster = movie_data.get("poster")
        download_task_data = json.loads(download_task)
        ready_dubs_list = download_task_data['dubs_list']
        download_task_lang = download_task_data['lang']

    except Exception as e:
        logger.error(f"[User {user_id}] Failed to parse cached  mirror data: {e}")
        await loading_msg.delete()
        if query.message is not None:
            await query.message.answer(gettext(LOST_MOVIE_DATA_RESEARCH),
                                       reply_markup=get_main_menu_keyboard())
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text=gettext(LOST_MOVIE_DATA_RESEARCH),
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
            await query.message.answer(gettext(TRY_SEARCHING_FROM_BEGINNING),
                                       reply_markup=get_main_menu_keyboard())
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text=gettext(TRY_SEARCHING_FROM_BEGINNING),
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                logger.error("query or query.bot is None, cannot send message to user.")
        return

    if not dubs_scrapper_result['dubs']:
        await loading_msg.delete()
        if query.message is not None:
            await query.message.answer(gettext(NO_DUBS_AVAILABLE_IN_LANGUAGE), reply_markup=get_main_menu_keyboard())
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text=gettext(NO_DUBS_AVAILABLE_IN_LANGUAGE),
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                logger.error("query or query.bot is None, cannot send message to user.")
        return

    if dubs_scrapper_result['message']:
        if dubs_scrapper_result['message'] == "🥲 Only 1 dub found":
            text_to_show = gettext(ONLY_ONE_DUB)
        elif dubs_scrapper_result['message'] == "🥲 No available dubs found for this language.":
            text_to_show = gettext(NO_DUBS_FOR_LANG)
        elif dubs_scrapper_result['message'] == "️🎙️ Sorry, no Ukrainian dubs available for this movie.":
            text_to_show = gettext(NO_UA_DUBS)
        await query.answer()
        if query.message is not None:
            await query.message.answer(text_to_show)
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text=text_to_show
                )
            else:
                logger.error("query or query.bot is None, cannot send message to user.")


    if dubs_scrapper_result['dubs'] == ['default_ru']:
        token = generate_token(tmdb_id, user_lang, 'default_ru')
        logger.info(f"Generated token {token} for TMDB_ID={tmdb_id}, dub=default_ru, lang={download_task_lang}")
        await redis.set(f"selected_dub_info:{token}", json.dumps({
            "tmdb_id": tmdb_id,
            "lang": "ru",
            "dub": 'default_ru',
            "movie_url": movie_url,
            "movie_title": movie_title,
            "movie_poster": movie_poster
        }), ex=3600)

        kb = [[types.InlineKeyboardButton(
            text=gettext(DOWNLOAD_DEFAULT_DUB),
            callback_data=f"select_dub:{token}"
        )]]
        await loading_msg.delete()
        await query.message.answer(gettext(MOVIE_HAS_ONLY_DEFAULT_DUB),
                                   reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))
        return

    already_downloaded_dubs = {file['dub'] for file in ready_dubs_list}
    available_dubs_can_be_downloaded = [dub for dub in dubs_scrapper_result['dubs'] if dub not in already_downloaded_dubs]

    kb = []

    if ready_dubs_list:
        kb.append([types.InlineKeyboardButton(text=gettext(ALREADY_AVAILABLE_DUBS), callback_data="noop")])
        for dub_dict in ready_dubs_list:
            dub = dub_dict['dub']
            token = generate_token(tmdb_id, user_lang, dub)
            logger.info(f"Generated token {token} for TMDB_ID={tmdb_id}, dub={dub}, lang={download_task_lang}")

            await redis.set(f"downloaded_dub_info:{token}", json.dumps({
                "tmdb_id": tmdb_id,
                "lang": download_task_lang,
                "dub": dub,
                "tg_user_id": user_id,
                "movie_title": movie_title,
                "movie_poster": movie_poster,
                "movie_url": movie_url
            }), ex=3600)

            emoji = "🇺🇦" if (user_lang == 'uk' and 'no Ukrainian dubs' not in dubs_scrapper_result.get('message','')) else "🎙"
            display_dub = translate_dub_to_ua(dub) if user_lang == 'uk' else dub
            kb.append([
                types.InlineKeyboardButton(
                    text=f"{emoji} {display_dub} dub",
                    callback_data=f"watch_downloaded:{token}"
                )
            ])

    if available_dubs_can_be_downloaded:
        kb.append([types.InlineKeyboardButton(text=gettext(AVAILABLE_TO_DOWNLOAD), callback_data="noop")])
        for dub in available_dubs_can_be_downloaded:
            emoji = "🇺🇦" if (user_lang == 'uk' and 'no Ukrainian dubs' not in dubs_scrapper_result.get('message','')) else "🎙"
            text = emoji +  f" {translate_dub_to_ua(dub)}" if user_lang == 'uk' else f" {dub}"
            token = generate_token(tmdb_id, user_lang, dub)
            logger.info(f"Generated token {token} for TMDB_ID={tmdb_id}, dub={dub}, lang={download_task_lang}")
            await redis.set(f"selected_dub_info:{token}", json.dumps({
                "tmdb_id": tmdb_id,
                "lang": download_task_lang,
                "dub": dub,
                "movie_url": movie_url,
                "movie_title": movie_title,
                "movie_poster": movie_poster
            }), ex=3600)

            kb.append([types.InlineKeyboardButton(text=text, callback_data=f"select_dub:{token}")])

    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    await loading_msg.delete()
    await query.message.answer(gettext(CHOOSE_DUB_TO_DOWNLOAD_OR_WATCH),
                               reply_markup=markup)  # type: ignore
    await query.answer()  # type: ignore

@router.callback_query(F.data.startswith("watch_downloaded:"))
async def watch_downloaded_handler(query: types.CallbackQuery):
    user_id = query.from_user.id
    token = query.data.split("watch_downloaded:")[1]  # type: ignore

    # Delete the original message with dub selection options
    try:
        if query.message is not None:
            await query.message.delete()
    except Exception as e:
        logger.error(f"[User {user_id}] Failed to delete original message: {e}")
        # Continue with the flow even if deletion fails

    redis = RedisClient.get_client()
    selected_data_json = await redis.get(f"downloaded_dub_info:{token}")
    if selected_data_json:
        selected_data = json.loads(selected_data_json)
        movie_title = selected_data.get("movie_title")
    else:
        movie_title = "movie"  # fallback

    signed = f"{token}_{hmac.new(os.getenv('BACKEND_DOWNLOAD_SECRET').encode(), token.encode(), hashlib.sha256).hexdigest()[:10]}"  # type: ignore
    delivery_bot_link = f"https://t.me/deliv3ry_bot?start=2_{signed}"

    if query is not None and getattr(query, 'bot', None) is not None:
        await query.bot.send_message(
            chat_id=user_id,
            text=gettext(MOVIE_READY_TO_WATCH_DELIVERY).format(movie_title=movie_title),
            reply_markup=types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [types.InlineKeyboardButton(text=gettext(GET_MOVIE_FROM_DELIVERY_BOT), url=delivery_bot_link)]
                ]
            )
        )
    else:
        logger.error("query or query.bot is None, cannot send message to user.")
    
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
            await query.message.answer(gettext(DUB_SELECTION_EXPIRED), reply_markup=get_main_menu_keyboard())
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text=gettext(DUB_SELECTION_EXPIRED),
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
        movie_title = selected_data.get("movie_title")
        movie_poster = selected_data.get("movie_poster")
    except Exception as e:
        logger.error(f"[User {user_id}] Failed to parse selected dub token: {e}")
        if query.message is not None:
            await query.message.answer(gettext(COULD_NOT_PROCESS_DUB_INFO), reply_markup=get_main_menu_keyboard())
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text=gettext(COULD_NOT_PROCESS_DUB_INFO),
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
        "movie_url": movie_url,
        "movie_title": movie_title,
        "movie_poster": movie_poster
    }

    data_b64, sig = SignedTokenManager.generate_token(payload)
    download_url = f"https://moviebot.click/hd/download?data={data_b64}&sig={sig}"

    # Notify user we're starting
    if query.message is not None:
        loading_msg = await query.message.answer_animation(
            animation="https://media.giphy.com/media/hvRJCLFzcasrR4ia7z/giphy.gif",
            caption=gettext(ADDED_TO_DOWNLOAD_QUEUE)
        )
    else:
        if query is not None and getattr(query, 'bot', None) is not None:
            loading_msg = await query.bot.send_animation(
                chat_id=query.from_user.id,
                animation="https://media.giphy.com/media/hvRJCLFzcasrR4ia7z/giphy.gif",
                caption=gettext(ADDED_TO_DOWNLOAD_QUEUE)
            )  # type: ignore
        else:
            logger.error("query or query.bot is None, cannot send animation to user.")

    try:
        async with ClientSession() as session:
            async with session.get(download_url) as resp:
                if resp.status == 429:
                    backend_response = await resp.json()
                    if loading_msg:
                        await loading_msg.delete()
                    #TODO: when premium users functionality is ready - we need to suggest here user to become premium and download more at once
                    if backend_response.get('status') == "limit_reached":
                        error_msg = gettext(DOWNLOAD_LIMIT).format(user_limit=backend_response.get('user_limit'))
                    if query.message is not None:
                        await query.message.answer(error_msg)
                    else:
                        if query is not None and getattr(query, 'bot', None) is not None:
                            await query.bot.send_message(  # type: ignore
                                chat_id=query.from_user.id,
                                text=error_msg
                            )
                        else:
                            logger.error("query or query.bot is None, cannot send message to user.")
                    return
                if resp.status == 409:
                    backend_response = await resp.json()
                    if loading_msg:
                        await loading_msg.delete()
                    if backend_response.get('status') == "duplicate_download":
                        error_msg = gettext(DUPLICATE_DOWNLOAD)
                    if query.message is not None:
                        await query.message.answer(error_msg)
                    else:
                        if query is not None and getattr(query, 'bot', None) is not None:
                            await query.bot.send_message(  # type: ignore
                                chat_id=query.from_user.id,
                                text=error_msg
                            )
                        else:
                            logger.error("query or query.bot is None, cannot send message to user.")
                    return
                if resp.status != 200:
                    if loading_msg:
                        await loading_msg.delete()
                    if query.message is not None:
                        await query.message.answer(
                            gettext(FAILED_TO_TRIGGER_DOWNLOAD),
                            reply_markup=get_main_menu_keyboard())
                    else:
                        if query is not None and getattr(query, 'bot', None) is not None:
                            await query.bot.send_message(  # type: ignore
                                chat_id=query.from_user.id,
                                text=gettext(FAILED_TO_TRIGGER_DOWNLOAD),
                                reply_markup=get_main_menu_keyboard()
                            )
                        else:
                            logger.error("query or query.bot is None, cannot send message to user.")
                    return

                backend_response = await resp.json()
                task_id = backend_response.get("task_id")
                if not task_id:
                    if loading_msg:
                        await loading_msg.delete()
                    if query.message is not None:
                        await query.message.answer(
                            gettext(FAILED_TO_TRIGGER_DOWNLOAD),
                            reply_markup=get_main_menu_keyboard())
                    else:
                        if query is not None and getattr(query, 'bot', None) is not None:
                            await query.bot.send_message(  # type: ignore
                                chat_id=query.from_user.id,
                                text=gettext(FAILED_TO_TRIGGER_DOWNLOAD),
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
            signed_task_id = f"{task_id}_{hmac.new(os.getenv('BACKEND_DOWNLOAD_SECRET').encode(), task_id.encode(), hashlib.sha256).hexdigest()[:10]}"  # type: ignore
            delivery_bot_link = f"https://t.me/deliv3ry_bot?start=1_{signed_task_id}"
            if query.message is not None:
                await query.message.answer(
                    gettext(MOVIE_READY_START_DELIVERY_BOT).format(movie_title=movie_title),
                    reply_markup=types.InlineKeyboardMarkup(
                        inline_keyboard=[
                            [types.InlineKeyboardButton(text=gettext(OPEN_DELIVERY_BOT), url=delivery_bot_link)]
                        ]
                    )
                )
            else:
                if query is not None and getattr(query, 'bot', None) is not None:
                    await query.bot.send_message(  # type: ignore
                        chat_id=query.from_user.id,
                        text=gettext(MOVIE_READY_START_DELIVERY_BOT).format(movie_title=movie_title),
                        reply_markup=types.InlineKeyboardMarkup(
                            inline_keyboard=[
                                [types.InlineKeyboardButton(text=gettext(OPEN_DELIVERY_BOT), url=delivery_bot_link)]
                            ]
                        )
                    )
                else:
                    logger.error("query or query.bot is None, cannot send message to user.")

    except Exception as e:
        logger.error(f"[User {user_id}] Failed during download flow: {e}")
        try:
            if loading_msg:
                await loading_msg.delete()
        except Exception as e:
            logger.error(f"[User {user_id}] Failed to delete loading message at the end of download flow: {e}")
        if query.message is not None:
            await query.message.answer(gettext(UNEXPECTED_ERROR_DURING_DOWNLOAD),
                                       reply_markup=get_main_menu_keyboard())
        else:
            if query is not None and getattr(query, 'bot', None) is not None:
                await query.bot.send_message(  # type: ignore
                    chat_id=query.from_user.id,
                    text=gettext(UNEXPECTED_ERROR_DURING_DOWNLOAD),
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                logger.error("query or query.bot is None, cannot send message to user.")

@router.callback_query(F.data == "noop")
async def noop_handler(query: types.CallbackQuery):
    await query.answer()
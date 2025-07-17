import re
import json
import hashlib
import time
import os
import hmac
from aiogram import Router, types, F
from aiogram.filters import Filter
from aiogram.utils.i18n import gettext
from aiohttp import ClientSession
from bot.utils.signed_token_manager import SignedTokenManager
from bot.locales.keys import (
    DOWNLOAD_SOURCE_SELECTION,
    DOWNLOAD_SEND_LINK_PROMPT, DOWNLOAD_INVALID_LINK, DOWNLOAD_INVALID_YOUTUBE_LINK, DOWNLOAD_LINK_PROCESSING,
    SOMETHING_WENT_WRONG_TRY_MAIN_MENU,
    CHOOSE_DUB_TO_DOWNLOAD, ONLY_ONE_DUB,
    NO_UA_DUBS, DOWNLOAD_DEFAULT_DUB, MOVIE_HAS_ONLY_DEFAULT_DUB,
    AVAILABLE_TO_DOWNLOAD, NO_DUBS_AVAILABLE_IN_LANGUAGE, DOWNLOAD_YOUTUBE_SEND_LINK_PROMPT,
    ADDED_TO_DOWNLOAD_QUEUE, FAILED_TO_TRIGGER_DOWNLOAD, UNEXPECTED_ERROR_DURING_DOWNLOAD,
    DOWNLOAD_LIMIT, DUPLICATE_DOWNLOAD, MOVIE_READY_START_DELIVERY_BOT, OPEN_DELIVERY_BOT,
    DOWNLOAD_QUEUE_POSITION, DOWNLOAD_EXTRACTING_DATA, DOWNLOAD_UPLOADING_TO_TELEGRAM,
    DOWNLOAD_FAILED_START_AGAIN, DOWNLOAD_PROCESSING_STATUS, DOWNLOAD_TIMEOUT_TRY_LATER
)
from bot.utils.logger import Logger
from bot.utils.session_manager import SessionManager
from bot.utils.user_service import UserService
from bot.utils.translate_dub_to_ua import translate_dub_to_ua
from bot.utils.redis_client import RedisClient
from bot.handlers.main_menu_btns_handler import get_main_menu_keyboard
from bot.utils.message_utils import smart_edit_or_send
from bot.helpers.back_button import add_back_button
from bot.keyboards.download_source_keyboard import get_download_source_keyboard
import asyncio

router = Router()
logger = Logger().get_logger()

# API endpoints
SCRAP_ALL_DUBS = "https://moviebot.click/hd/alldubs"

# HDRezka URL pattern (improved to support more domains and formats)
HDREZKA_URL_PATTERN = r'https?://(?:www\.)?(?:hd)?rezka(?:-ua)?\.(?:ag|co|me|org|net|com)/.*'

# YouTube URL pattern
YOUTUBE_URL_PATTERN = r'https?://(?:www\.)?(?:youtube\.com|youtu\.be|m\.youtube\.com)/(?:watch\?v=|embed/|v/|shorts/)?([a-zA-Z0-9_-]{11})(?:[^\s]*)?'

# State filter for HDRezka link input
class HDRezkaLinkInputStateFilter(Filter):
    async def __call__(self, message: types.Message) -> bool:
        if message.from_user is None:
            return False
        state = await SessionManager.get_state(message.from_user.id)
        return state == "direct_download:waiting_for_hdrezka_link"

# State filter for YouTube link input
class YouTubeLinkInputStateFilter(Filter):
    async def __call__(self, message: types.Message) -> bool:
        if message.from_user is None:
            return False
        state = await SessionManager.get_state(message.from_user.id)
        return state == "direct_download:waiting_for_youtube_link"

def generate_token(tmdb_id: int, lang: str, dub: str) -> str:
    """Generate token for dub selection (same as in mirror_watch_download_handler)"""
    base = f"{tmdb_id}:{lang}:{dub}"
    return hashlib.md5(base.encode()).hexdigest()[:12]

async def poll_youtube_download_until_ready(user_id: int, task_id: str, status_url: str, loading_msg: types.Message, bot):
    """Simplified polling function for YouTube downloads that doesn't require a query object"""
    max_attempts = 120  # 60 minutes if 30s interval
    interval = 30
    last_status = None
    last_animation_msg = loading_msg
    last_text_msg = None
    last_text = None

    async with ClientSession() as session:
        for attempt in range(max_attempts):
            try:
                async with session.get(f"{status_url}/{task_id}") as resp:
                    if resp.status != 200:
                        logger.warning(f"[User {user_id}] Polling failed (status {resp.status}) on attempt {attempt}")
                        await asyncio.sleep(interval)
                        continue

                    data = await resp.json()
                    status = data.get("status")
                    new_text = None
                    animation_url = None

                    # Determine which animation/caption to use
                    if status == "queued":
                        animation_url = "https://media.giphy.com/media/F99PZtJC8Hxm0/giphy.gif"
                        position = data.get("queue_position") or '...'
                        new_text = gettext(DOWNLOAD_QUEUE_POSITION).format(position=position)
                    elif status == "downloading":
                        animation_url = "https://media.giphy.com/media/3oEjI6SIIHBdRxXI40/giphy.gif"
                        new_text = gettext(DOWNLOAD_EXTRACTING_DATA)
                    elif status == "uploading":
                        animation_url = "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif"
                        new_text = gettext(DOWNLOAD_UPLOADING_TO_TELEGRAM)
                    elif status == "done":
                        result = data.get("result")
                        if result:
                            try:
                                await last_animation_msg.delete()
                            except Exception as err:
                                logger.error(f"[User {user_id}] Could not delete last animation message: {err}")
                            if last_text_msg:
                                try:
                                    await last_text_msg.delete()
                                except Exception as err:
                                    logger.error(f"[User {user_id}] Could not delete last text message: {err}")
                            return result  # contains {file_id, bot_token}
                        else:
                            logger.warning(f"[User {user_id}] status=done but no result found.")
                            break
                    elif status == "error":
                        error_text = data.get("error", "Unknown error")
                        try:
                            await last_animation_msg.delete()
                        except Exception as err:
                            logger.error(f"[User {user_id}] Could not delete last animation message: {err}")
                        if last_text_msg:
                            try:
                                await last_text_msg.delete()
                            except Exception as err:
                                logger.error(f"[User {user_id}] Could not delete last text message: {err}")

                        logger.error(f"[User {user_id}].❌ Download failed: {error_text}")
                        await bot.send_message(
                            chat_id=user_id,
                            text=gettext(DOWNLOAD_FAILED_START_AGAIN),
                            reply_markup=get_main_menu_keyboard()
                        )
                        return None
                    else:
                        animation_url = "https://media.giphy.com/media/hvRJCLFzcasrR4ia7z/giphy.gif"
                        new_text = gettext(DOWNLOAD_PROCESSING_STATUS).format(status=status)

                    # If status changed, delete old animation and send new one, and update text message
                    if status != last_status:
                        try:
                            await last_animation_msg.delete()
                        except Exception as err:
                            logger.error(f"[User {user_id}] Could not delete last animation message: {err}")
                        
                        last_animation_msg = await bot.send_animation(
                            chat_id=user_id,
                            animation=animation_url,
                            caption=None
                        )
                        
                        # Delete previous text message if exists
                        if last_text_msg:
                            try:
                                await last_text_msg.delete()
                            except Exception as err:
                                logger.error(f"[User {user_id}] Could not delete last text message: {err}")
                        
                        # Send new text message
                        last_text_msg = await bot.send_message(
                            chat_id=user_id,
                            text=new_text
                        )
                        
                        last_status = status
                        last_text = new_text

            except Exception as e:
                error_str = str(e)
                if "message is not modified" in error_str:
                    logger.error(f"[User {user_id}] tried to edit text while polling but it was not modified")
                    pass
                else:
                    logger.error(f"[User {user_id}] Exception during polling: {e}")

            await asyncio.sleep(interval)

    # Timed out
    try:
        await last_animation_msg.delete()
    except Exception as e:
        logger.warning(f"[User {user_id}] Could not delete loading message: {e}")
    try:
        await bot.send_message(
            chat_id=user_id,
            text=gettext(DOWNLOAD_TIMEOUT_TRY_LATER),
            reply_markup=get_main_menu_keyboard()
        )
    except Exception as e:
        logger.error(f"[User {user_id}] Could not send timeout message: {e}")
    return None

@router.callback_query(F.data == "download_movie")
async def direct_download_handler(query: types.CallbackQuery):
    """Handle main menu download button click"""
    logger.info(f"[User {query.from_user.id}] Clicked 'Download Movie' button")
    
    keyboard = get_download_source_keyboard()
    
    await smart_edit_or_send(
        message=query,
        text=gettext(DOWNLOAD_SOURCE_SELECTION),
        reply_markup=keyboard
    )
    await query.answer()

@router.callback_query(F.data.startswith("direct_download_source:"))
async def download_source_selection_handler(query: types.CallbackQuery):
    """Handle download source selection"""
    if query.data is None:
        await query.answer(
            gettext(SOMETHING_WENT_WRONG_TRY_MAIN_MENU),
            reply_markup=get_main_menu_keyboard()
        )
        return
    user_id = query.from_user.id
    source = query.data.split(":")[1]
    
    logger.info(f"[User {user_id}] Selected download source: {source}")
    
    if source == "youtube":
        await SessionManager.set_state(user_id, "direct_download:waiting_for_youtube_link")
        
        keyboard = add_back_button(types.InlineKeyboardMarkup(inline_keyboard=[]), source="download_source")
        
        await smart_edit_or_send(
            message=query,
            text=gettext(DOWNLOAD_YOUTUBE_SEND_LINK_PROMPT),
            reply_markup=keyboard
        )
        await query.answer()
        return
    
    if source == "hdrezka":
        await SessionManager.set_state(user_id, "direct_download:waiting_for_hdrezka_link")
        
        keyboard = add_back_button(types.InlineKeyboardMarkup(inline_keyboard=[]), source="download_source")
        
        await smart_edit_or_send(
            message=query,
            text=gettext(DOWNLOAD_SEND_LINK_PROMPT),
            reply_markup=keyboard
        )
        await query.answer()
        return

    logger.error(f"[User {user_id}] Invalid source: {source}")
    await smart_edit_or_send(
            message=query,
            text=gettext(SOMETHING_WENT_WRONG_TRY_MAIN_MENU),
            reply_markup=get_main_menu_keyboard()
        )

@router.message(F.text, HDRezkaLinkInputStateFilter())
async def handle_hdrezka_link_input(message: types.Message):
    """Handle HDRezka link input from user"""
    if message.from_user is None or message.text is None:
        await message.answer(
            gettext(SOMETHING_WENT_WRONG_TRY_MAIN_MENU),
            reply_markup=get_main_menu_keyboard()
        )
        return
    user_id = message.from_user.id
    link = message.text.strip()
    
    # Validate HDRezka URL
    if not re.match(HDREZKA_URL_PATTERN, link):
        await message.answer(
            gettext(DOWNLOAD_INVALID_LINK),
            reply_markup=get_download_source_keyboard()
        )
        await SessionManager.clear_state(user_id)
        return
    
    logger.info(f"[User {user_id}] Received HDRezka link: {link}")
    
    # Clear state
    await SessionManager.clear_state(user_id)
    
    # Get user's preferred language
    user_lang = await UserService.get_user_movies_language(user_id)
    
    # Show processing message
    processing_msg = await message.answer(gettext(DOWNLOAD_LINK_PROCESSING))
    
    try:
        # Step 1: Get available dubs for this URL
        async with ClientSession() as session:
            async with session.post(SCRAP_ALL_DUBS, json={"url": link, "lang": user_lang}) as resp:
                if resp.status != 200:
                    logger.error(f"[User {user_id}] API returned status {resp.status}")
                    await processing_msg.delete()
                    await message.answer(
                        gettext(SOMETHING_WENT_WRONG_TRY_MAIN_MENU),
                        reply_markup=get_main_menu_keyboard()
                    )
                    return
                
                dubs_result = await resp.json()
                logger.info(f"[User {user_id}] API response: {dubs_result}")
        
        await processing_msg.delete()
        
        if not dubs_result.get('dubs'):
            logger.info(f"[User {user_id}] No dubs found in response: {dubs_result}")
            await message.answer(
                gettext(NO_DUBS_AVAILABLE_IN_LANGUAGE),
                reply_markup=get_main_menu_keyboard()
            )
            return
        
        # Step 2: Handle special messages from API
        if dubs_result.get('message'):
            if dubs_result['message'] == "🥲 Only 1 dub found":
                text_to_show = gettext(ONLY_ONE_DUB)
            elif dubs_result['message'] == "🥲 No available dubs found for this language.":
                text_to_show = gettext(NO_DUBS_AVAILABLE_IN_LANGUAGE)
            elif "Sorry, no Ukrainian dubs available for this movie" in dubs_result['message']:
                text_to_show = gettext(NO_UA_DUBS)
            else:
                text_to_show = dubs_result['message']
            
            await message.answer(text_to_show)

        # Step 3: Create mock tmdb_id for direct downloads
        mock_tmdb_id = int(hashlib.md5(link.encode()).hexdigest()[:8], 16)
        
        # Step 4: Handle default RU case
        if dubs_result['dubs'] == ['default_ru']:
            token = generate_token(mock_tmdb_id, user_lang, 'default_ru')
            
            # Store data that select_dub_handler expects
            selected_dub_data = {
                "tmdb_id": mock_tmdb_id,
                "lang": "ru",
                "dub": 'default_ru',
                "movie_url": link,
                "movie_title": "Movie",
                "movie_poster": None
            }
            
            redis = RedisClient.get_client()
            await redis.set(f"selected_dub_info:{token}", json.dumps(selected_dub_data), ex=3600)
            
            # Show single dub option
            kb = [[types.InlineKeyboardButton(
                text=gettext(DOWNLOAD_DEFAULT_DUB),
                callback_data=f"select_dub:{token}"
            )]]
            
            markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
            await message.answer(gettext(MOVIE_HAS_ONLY_DEFAULT_DUB), reply_markup=markup)
            return
        
        # Step 5: Handle multiple dubs
        redis = RedisClient.get_client()
        kb = []
        kb.append([types.InlineKeyboardButton(text=gettext(AVAILABLE_TO_DOWNLOAD), callback_data="noop")])
        
        for dub in dubs_result['dubs']:
            token = generate_token(mock_tmdb_id, user_lang, dub)
            
            # Store data that select_dub_handler expects
            selected_dub_data = {
                "tmdb_id": mock_tmdb_id,
                "lang": user_lang,
                "dub": dub,
                "movie_url": link,
                "movie_title": "Movie",
                "movie_poster": None
            }
            
            await redis.set(f"selected_dub_info:{token}", json.dumps(selected_dub_data), ex=3600)
            
            # Create button with translated dub name
            emoji = "🇺🇦" if (user_lang == 'uk' and 'no Ukrainian dubs' not in dubs_result.get('message','')) else "🎙"
            display_dub = translate_dub_to_ua(dub) if user_lang == 'uk' else dub
            text = f"{emoji} {display_dub}"
            
            kb.append([types.InlineKeyboardButton(text=text, callback_data=f"select_dub:{token}")])
        
        markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
        await message.answer(gettext(CHOOSE_DUB_TO_DOWNLOAD), reply_markup=markup)
        
    except Exception as e:
        logger.error(f"[User {user_id}] Error processing HDRezka link: {e}")
        try:
            await processing_msg.delete()
        except:
            pass
        
        await message.answer(
            gettext(SOMETHING_WENT_WRONG_TRY_MAIN_MENU),
            reply_markup=get_main_menu_keyboard()
        )

@router.message(F.text, YouTubeLinkInputStateFilter())
async def handle_youtube_link_input(message: types.Message):
    """Handle YouTube link input from user"""
    if message.from_user is None or message.text is None:
        await message.answer(
            gettext(SOMETHING_WENT_WRONG_TRY_MAIN_MENU),
            reply_markup=get_main_menu_keyboard()
        )
        return
    user_id = message.from_user.id
    link = message.text.strip()
    
    # Validate YouTube URL
    if not re.match(YOUTUBE_URL_PATTERN, link):
        await message.answer(
            gettext(DOWNLOAD_INVALID_YOUTUBE_LINK),
            reply_markup=get_download_source_keyboard()
        )
        await SessionManager.clear_state(user_id)
        return
    
    logger.info(f"[User {user_id}] Received YouTube link: {link}")
    
    # Clear state
    await SessionManager.clear_state(user_id)
    
    # Get user's preferred language
    user_lang = await UserService.get_user_movies_language(user_id)
    
    # Show processing message
    processing_msg = await message.answer(gettext(DOWNLOAD_LINK_PROCESSING))
    
    try:
        # Create mock tmdb_id for YouTube downloads (using video ID from URL)
        video_id_match = re.search(r'([a-zA-Z0-9_-]{11})', link)
        if video_id_match:
            video_id = video_id_match.group(1)
            mock_tmdb_id = int(hashlib.md5(video_id.encode()).hexdigest()[:8], 16)
        else:
            mock_tmdb_id = int(hashlib.md5(link.encode()).hexdigest()[:8], 16)
        
        # For YouTube, we don't need to fetch dubs - it's just one video
        # Create payload for YouTube download
        payload = {
            "tmdb_id": mock_tmdb_id,
            "lang": user_lang,
            "dub": "youtube",  # Use "youtube" as dub identifier
            "exp": int(time.time()) + 600,
            "tg_user_id": user_id,
            "video_url": link,  # YouTube uses video_url instead of movie_url
            "video_title": "YouTube Video",
            "video_poster": None
        }

        data_b64, sig = SignedTokenManager.generate_token(payload)
        download_url = f"https://moviebot.click/youtube/download?data={data_b64}&sig={sig}"

        await processing_msg.delete()

        # Notify user we're starting
        loading_msg = await message.answer_animation(
            animation="https://media.giphy.com/media/hvRJCLFzcasrR4ia7z/giphy.gif",
            caption=gettext(ADDED_TO_DOWNLOAD_QUEUE)
        )

        # Call YouTube download endpoint
        async with ClientSession() as session:
            async with session.get(download_url) as resp:
                if resp.status == 429:
                    backend_response = await resp.json()
                    if loading_msg:
                        await loading_msg.delete()
                    if backend_response.get('status') == "limit_reached":
                        error_msg = gettext(DOWNLOAD_LIMIT).format(user_limit=backend_response.get('user_limit'))
                    await message.answer(error_msg)
                    return
                if resp.status == 409:
                    backend_response = await resp.json()
                    if loading_msg:
                        await loading_msg.delete()
                    if backend_response.get('status') == "duplicate_download":
                        error_msg = gettext(DUPLICATE_DOWNLOAD)
                    await message.answer(error_msg)
                    return
                if resp.status != 200:
                    if loading_msg:
                        await loading_msg.delete()
                    await message.answer(
                        gettext(FAILED_TO_TRIGGER_DOWNLOAD),
                        reply_markup=get_main_menu_keyboard()
                    )
                    return

                backend_response = await resp.json()
                task_id = backend_response.get("task_id")
                if not task_id:
                    if loading_msg:
                        await loading_msg.delete()
                    await message.answer(
                        gettext(FAILED_TO_TRIGGER_DOWNLOAD),
                        reply_markup=get_main_menu_keyboard()
                    )
                    return

        # Poll for download completion using a simplified polling mechanism for YouTube
        result = await poll_youtube_download_until_ready(
            user_id=user_id,
            task_id=task_id,
            status_url="https://moviebot.click/hd/status/download",  # Same status endpoint
            loading_msg=loading_msg,
            bot=message.bot
        )

        if result and task_id is not None:
            task_id_str = str(task_id)
            backend_secret = os.getenv('BACKEND_DOWNLOAD_SECRET')
            if backend_secret is None:
                logger.error("BACKEND_DOWNLOAD_SECRET environment variable is not set")
                await message.answer(
                    gettext(UNEXPECTED_ERROR_DURING_DOWNLOAD),
                    reply_markup=get_main_menu_keyboard()
                )
                return
            signed_task_id = f"{task_id_str}_{hmac.new(backend_secret.encode(), task_id_str.encode(), hashlib.sha256).hexdigest()[:10]}"
            delivery_bot_link = f"https://t.me/deliv3ry_bot?start=1_{signed_task_id}"
            await message.answer(
                gettext(MOVIE_READY_START_DELIVERY_BOT).format(movie_title=payload["video_title"]),
                reply_markup=types.InlineKeyboardMarkup(
                    inline_keyboard=[
                        [types.InlineKeyboardButton(text=gettext(OPEN_DELIVERY_BOT), url=delivery_bot_link)]
                    ]
                )
            )
        
    except Exception as e:
        logger.error(f"[User {user_id}] Error processing YouTube link: {e}")
        try:
            await processing_msg.delete()
        except:
            pass
        
        await message.answer(
            gettext(UNEXPECTED_ERROR_DURING_DOWNLOAD),
            reply_markup=get_main_menu_keyboard()
        )
 
import re
import json
import hashlib
import time
import os
import hmac
from urllib.parse import urlparse, parse_qs
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
    DOWNLOAD_QUEUE_POSITION, DOWNLOAD_UPLOADING_TO_TELEGRAM, DOWNLOAD_UPLOADING_PROGRESS,
    DOWNLOAD_FAILED_START_AGAIN, DOWNLOAD_PROCESSING_STATUS, DOWNLOAD_TIMEOUT_TRY_LATER,
    DOWNLOAD_YOUTUBE_DOWNLOADING
)
from bot.utils.logger import Logger
from bot.utils.session_manager import SessionManager
from bot.utils.user_service import UserService
from bot.utils.translate_dub_to_ua import translate_dub_by_language
from bot.utils.redis_client import RedisClient
from bot.handlers.main_menu_btns_handler import get_main_menu_keyboard
from bot.utils.message_utils import smart_edit_or_send
from bot.helpers.back_button import add_back_button
from bot.keyboards.download_source_keyboard import get_download_source_keyboard
import asyncio
import base64

router = Router()
logger = Logger().get_logger()

# API endpoints
SCRAP_ALL_DUBS = "https://moviebot.click/hd/alldubs"

# HDRezka URL pattern (improved to support more domains and formats)
HDREZKA_URL_PATTERN = r'https?://(?:www\.)?(?:hd)?rezka(?:-ua)?\.(?:ag|co|me|org|net|com)/.*'

# YouTube URL pattern
YOUTUBE_URL_PATTERN = r'https?://(?:www\.)?(?:youtube\.com|youtu\.be|m\.youtube\.com)/(?:watch\?v=|embed/|v/|shorts/)?([a-zA-Z0-9_-]{11})(?:[^\s]*)?'

def normalize_youtube_url(url: str) -> str:
    """
    Normalize YouTube URL to remove UTM parameters and other tracking parameters.
    Returns a clean, canonical URL with only the video ID.
    
    Examples:
    - https://www.youtube.com/watch?v=I4AgeDIrHGY&utm_source=facebook&feature=share
    - https://youtu.be/I4AgeDIrHGY?t=30&list=PL123
    Both become: https://www.youtube.com/watch?v=I4AgeDIrHGY
    """
    try:
        # Handle youtu.be URLs
        if 'youtu.be' in url:
            # Extract video ID from youtu.be URLs
            video_id_match = re.search(r'youtu\.be/([a-zA-Z0-9_-]{11})', url)
            if video_id_match:
                video_id = video_id_match.group(1)
                return f"https://www.youtube.com/watch?v={video_id}"
        
        # Handle youtube.com URLs
        elif 'youtube.com' in url:
            # Parse the URL
            parsed = urlparse(url)
            
            # Extract video ID from query parameters
            query_params = parse_qs(parsed.query)
            video_id = query_params.get('v', [None])[0]
            
            if video_id and len(video_id) == 11:
                # Create clean URL with only the video ID
                return f"https://www.youtube.com/watch?v={video_id}"
        
        # If we can't parse it properly, try regex as fallback
        video_id_match = re.search(r'([a-zA-Z0-9_-]{11})', url)
        if video_id_match:
            video_id = video_id_match.group(1)
            return f"https://www.youtube.com/watch?v={video_id}"
            
    except Exception as e:
        logger.error(f"Error normalizing YouTube URL '{url}': {e}")
    
    # Return original URL if normalization fails
    return url

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
    max_attempts = 90  # 15 minutes if 10s interval
    interval = 10
    last_status = None
    last_animation_msg = loading_msg
    last_text_msg = None
    last_text = None
    upload_poll_count = 0  # Counter for upload progress

    async with ClientSession() as session:

        for attempt in range(max_attempts):
            # Try to poll with retries for network issues
            data = None
            for retry in range(4):  # 0, 1, 2, 3 = 4 attempts total
                try:
                    async with session.get(f"{status_url}/{task_id}") as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            break  # Success
                        elif 500 <= resp.status < 600 and retry < 3:
                            logger.warning(f"[User {user_id}] Server error {resp.status} on attempt {attempt}, retry {retry + 1}/3")
                            # Use exponential backoff for server errors
                            await asyncio.sleep(2 ** retry)  # 1s, 2s, 4s
                            continue
                        else:
                            logger.warning(f"[User {user_id}] Polling failed (status {resp.status}) on attempt {attempt}")
                            break
                            
                except (asyncio.TimeoutError, Exception) as e:
                    if retry < 3:
                        logger.warning(f"[User {user_id}] Poll exception on attempt {attempt}, retry {retry + 1}/3: {e}")
                        await asyncio.sleep(5)
                        continue
                    else:
                        logger.error(f"[User {user_id}] Poll failed after 3 retries: {e}")
                        break
            
            # If polling failed completely, wait and try next interval
            if data is None:
                logger.warning(f"[User {user_id}] Polling failed completely on attempt {attempt + 1}, waiting {interval}s before next attempt")
                await asyncio.sleep(interval)
                continue

            try:
                    status = data.get("status")
                    new_text = None
                    animation_url = None

                    # Log what we received
                    from datetime import datetime
                    logger.info(f"🔍 [User {user_id}] Poll #{attempt + 1} at {datetime.now().isoformat()}: Received status='{status}', data={data}")

                    # Determine which animation/caption to use
                    if status == "queued":
                        animation_url = "https://media.giphy.com/media/99PFodlfMDhG6KxnL2/giphy.gif"
                        position = data.get("queue_position") or '...'
                        new_text = gettext(DOWNLOAD_QUEUE_POSITION).format(position=position)
                    elif status == "downloading":
                        animation_url = "https://media.giphy.com/media/Hpvu9ljTG5YYnAKJPK/giphy.gif"
                        # Fetch progress from Redis
                        redis = RedisClient.get_client()
                        progress = 0
                        try:
                            progress_str = await redis.get(f"download:{task_id}:yt_download_progress")
                            if progress_str is not None:
                                progress = int(progress_str)
                                logger.info(f"[User {user_id}] YouTube download progress: {progress}%")
                        except Exception as e:
                            logger.error(f"[User {user_id}] Could not fetch YT download progress: {e}")
                        
                        if progress > 0 and progress < 100:
                            # Create a simple progress bar
                            filled = int(progress / 10)  # Each bar represents 10%
                            empty = 10 - filled
                            progress_bar = "█" * filled + "░" * empty
                            new_text = f"{gettext(DOWNLOAD_YOUTUBE_DOWNLOADING)}\n\n{progress_bar} {progress}%"
                        elif progress >= 100:
                            new_text = f"{gettext(DOWNLOAD_YOUTUBE_DOWNLOADING)}\n\n██████████ 100% ✅"
                        else:
                            new_text = gettext(DOWNLOAD_YOUTUBE_DOWNLOADING)
                    elif status == "uploading":
                        upload_poll_count += 1
                        num_pieces = upload_poll_count * 2
                        new_text = gettext(DOWNLOAD_UPLOADING_PROGRESS).format(num=num_pieces)
                        
                        # Select animation based on poll count
                        if upload_poll_count <= 7:
                            animation_url = "https://media.giphy.com/media/zX202CLqU5aqaWKcWY/giphy.gif"
                        elif upload_poll_count <= 14:
                            animation_url = "https://media.giphy.com/media/NjRGWOHZJGP0AiSxZb/giphy.gif"
                        else:
                            animation_url = "https://media.giphy.com/media/q9JhdEdX4cUWoTPAud/giphy.gif"
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
                        animation_url = "https://media.giphy.com/media/RDqkrKJr5XwPWxz3pa/giphy.gif"
                        new_text = gettext(DOWNLOAD_PROCESSING_STATUS).format(status=status)

                    # Check if we need to update the UI
                    should_update_ui = False
                    
                    # Update UI if status changed
                    if status != last_status:
                        should_update_ui = True
                        logger.info(f"🎬 [User {user_id}] STATUS CHANGE: '{last_status}' → '{status}', showing text: '{new_text}'")
                    # Also update UI if status is "downloading" and progress text changed
                    elif status == "downloading" and new_text != last_text:
                        should_update_ui = True
                        logger.info(f"📊 [User {user_id}] Progress update: '{last_text}' → '{new_text}'")
                    # Also update UI if status is "uploading" and progress text changed
                    elif status == "uploading" and new_text != last_text:
                        should_update_ui = True
                        logger.info(f"📤 [User {user_id}] Upload progress update: '{last_text}' → '{new_text}'")
                    
                    if should_update_ui:
                        # Delete old animation and send new one
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
                    else:
                        logger.info(f"🔄 [User {user_id}] No UI update needed, staying on '{status}'")  

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

# --- Download Movie Logic (reusable for both command and callback) ---
async def handle_download_movie_request(message_or_query):
    """Common logic for handling download movie requests from both commands and callbacks"""
    keyboard = get_download_source_keyboard()
    
    await smart_edit_or_send(
        message=message_or_query,
        text=gettext(DOWNLOAD_SOURCE_SELECTION),
        reply_markup=keyboard
    )


@router.message(F.text == "/download_movie")
async def download_movie_command_handler(message: types.Message):
    """Handle /download_movie command"""
    await handle_download_movie_request(message)


@router.callback_query(F.data == "download_movie")
async def direct_download_handler(query: types.CallbackQuery):
    """Handle main menu download button callback"""
    await handle_download_movie_request(query)
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
            emoji = "🇺🇦" if (user_lang == 'uk' and 'no Ukrainian dubs' not in dubs_result.get('message','')) else ("🇺🇸" if user_lang == 'en' else "🎙")
            display_dub = translate_dub_by_language(dub, user_lang)
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
        # Normalize the URL to remove UTM parameters and other tracking
        normalized_link = normalize_youtube_url(link)
        logger.info(f"[User {user_id}] Normalized YouTube link: {normalized_link}")

        # Create mock tmdb_id for YouTube downloads (using video ID from normalized URL)
        video_id_match = re.search(r'([a-zA-Z0-9_-]{11})', normalized_link)
        if video_id_match:
            video_id = video_id_match.group(1)
            mock_tmdb_id = int(hashlib.md5(video_id.encode()).hexdigest()[:8], 16)
            logger.info(f"[User {user_id}] Extracted video ID: {video_id}, generated tmdb_id: {mock_tmdb_id}")
        else:
            mock_tmdb_id = int(hashlib.md5(normalized_link.encode()).hexdigest()[:8], 16)
            logger.warning(f"[User {user_id}] Could not extract video ID from normalized link: {normalized_link}")
        
        # For YouTube, we don't need to fetch dubs - it's just one video
        # Create payload for YouTube download
        payload = {
            "tmdb_id": mock_tmdb_id,
            "lang": user_lang,
            "dub": "youtube",  # Use "youtube" as dub identifier
            "exp": int(time.time()) + 600,
            "tg_user_id": user_id,
            "video_url": normalized_link,  # Use normalized_link
            "video_title": "YouTube Video",
            "video_poster": None
        }

        data_b64, sig = SignedTokenManager.generate_token(payload)
        download_url = f"https://moviebot.click/youtube/download?data={data_b64}&sig={sig}"

        await processing_msg.delete()

        # Notify user we're starting
        loading_msg = await message.answer_animation(
            animation="https://media.giphy.com/media/lR4b8p34o95i0LkWoy/giphy.gif",
            caption=gettext(ADDED_TO_DOWNLOAD_QUEUE)
        )
        logger.info(f"🎬 [User {user_id}] Initial message shown: '{gettext(ADDED_TO_DOWNLOAD_QUEUE)}'")

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
                
                # Handle fast return case - video already exists in DB
                if backend_response.get("status") == "already_exists":
                    if loading_msg:
                        await loading_msg.delete()
                    
                    file_type = backend_response.get("file_type")
                    movie_title = backend_response.get("movie_title", "YouTube Video")
                    quality = backend_response.get("quality", "unknown")
                    
                    logger.info(f"[User {user_id}] 🚀 FAST RETURN: YouTube video already exists in DB (type: {file_type}, quality: {quality}, title: {movie_title})")
                    
                    # Create signed token for delivery bot
                    backend_secret = os.getenv('BACKEND_DOWNLOAD_SECRET')
                    if backend_secret is None:
                        logger.error("BACKEND_DOWNLOAD_SECRET environment variable is not set")
                        await message.answer(
                            gettext(UNEXPECTED_ERROR_DURING_DOWNLOAD),
                            reply_markup=get_main_menu_keyboard()
                        )
                        return
                    
                    file_type = backend_response.get("file_type")
                    movie_title = backend_response.get("movie_title", "YouTube Video")
                    
                    if file_type == "single":
                        # Single file - create direct access token using Redis-based approach
                        file_data = {
                            "tg_bot_token_file_owner": backend_response["tg_bot_token_file_owner"],
                            "telegram_file_id": backend_response["telegram_file_id"]
                        }
                        
                        # Generate a short token for Redis lookup (much shorter than encoding full data)
                        short_token = hashlib.md5(json.dumps(file_data, separators=(",", ":")).encode()).hexdigest()[:12]
                        
                        # Store file data in Redis (this is what delivery bot expects)
                        redis = RedisClient.get_client()
                        await redis.set(f"yt_single:{short_token}", json.dumps(file_data), ex=3600)
                        
                        # Create signed token with just the short token (much shorter)
                        signed_file_data = f"{short_token}_{hmac.new(backend_secret.encode(), short_token.encode(), hashlib.sha256).hexdigest()[:10]}"
                        delivery_bot_link = f"https://t.me/deliv3ry_bot?start=3_{signed_file_data}"
                    else:
                        # Multi-part file - create DB access token
                        db_id = backend_response["db_id_to_get_parts"]
                        signed_db_id = f"{db_id}_{hmac.new(backend_secret.encode(), str(db_id).encode(), hashlib.sha256).hexdigest()[:10]}"
                        delivery_bot_link = f"https://t.me/deliv3ry_bot?start=1_{signed_db_id}"
                    
                    await message.answer(
                        gettext(MOVIE_READY_START_DELIVERY_BOT).format(movie_title=movie_title),
                        reply_markup=types.InlineKeyboardMarkup(
                            inline_keyboard=[
                                [types.InlineKeyboardButton(text=gettext(OPEN_DELIVERY_BOT), url=delivery_bot_link)]
                            ]
                        )
                    )
                    return
                
                # Normal download flow - video doesn't exist, needs to be downloaded
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
 
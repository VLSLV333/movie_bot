import re
import json
import hashlib
from aiogram import Router, types, F
from aiogram.filters import Filter
from aiogram.utils.i18n import gettext
from aiohttp import ClientSession
from bot.locales.keys import (
    DOWNLOAD_SOURCE_SELECTION,
    DOWNLOAD_SEND_LINK_PROMPT, DOWNLOAD_INVALID_LINK, DOWNLOAD_LINK_PROCESSING,
     SOMETHING_WENT_WRONG_TRY_MAIN_MENU,
    CHOOSE_DUB_TO_DOWNLOAD, ONLY_ONE_DUB,
    NO_UA_DUBS, DOWNLOAD_DEFAULT_DUB, MOVIE_HAS_ONLY_DEFAULT_DUB,
    AVAILABLE_TO_DOWNLOAD, NO_DUBS_AVAILABLE_IN_LANGUAGE
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

router = Router()
logger = Logger().get_logger()

# API endpoints
SCRAP_ALL_DUBS = "https://moviebot.click/hd/alldubs"

# HDRezka URL pattern (improved to support more domains and formats)
HDREZKA_URL_PATTERN = r'https?://(?:www\.)?(?:hd)?rezka(?:-ua)?\.(?:ag|co|me|org|net|com)/.*'

# State filter for HDRezka link input
class HDRezkaLinkInputStateFilter(Filter):
    async def __call__(self, message: types.Message) -> bool:
        if message.from_user is None:
            return False
        state = await SessionManager.get_state(message.from_user.id)
        return state == "direct_download:waiting_for_hdrezka_link"

def generate_token(tmdb_id: int, lang: str, dub: str) -> str:
    """Generate token for dub selection (same as in mirror_watch_download_handler)"""
    base = f"{tmdb_id}:{lang}:{dub}"
    return hashlib.md5(base.encode()).hexdigest()[:12]

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
        # TODO: Implement YouTube download flow
        await query.answer("YouTube downloads coming soon!", show_alert=True)
        return
    
    # For HDRezka, set state and ask for link
    await SessionManager.set_state(user_id, "direct_download:waiting_for_hdrezka_link")
    
    # Create keyboard with back button to download source selection
    keyboard = add_back_button(types.InlineKeyboardMarkup(inline_keyboard=[]), source="download_source")
    
    await smart_edit_or_send(
        message=query,
        text=gettext(DOWNLOAD_SEND_LINK_PROMPT),
        reply_markup=keyboard
    )
    await query.answer()

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
            elif dubs_result['message'] == "️🎙️ Sorry, no Ukrainian dubs available for this movie.":
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
 
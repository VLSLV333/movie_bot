import aiohttp
from aiogram import Router, types
from aiogram.utils.i18n import gettext
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from bot.locales.keys import WELCOME_MESSAGE
from bot.utils.logger import Logger
from bot.handlers.main_menu_btns_handler import get_main_menu_keyboard
from bot.utils.notify_admin import notify_admin
from typing import Optional

router = Router()
logger = Logger().get_logger()

# Backend API URL
BACKEND_API_URL = "https://moviebot.click"

# Welcome GIF URL - replace with your actual GIF
WELCOME_GIF_URL = "https://media.giphy.com/media/3o7abKhOpu0NwenH3O/giphy.gif"


async def call_backend_api(endpoint: str, method: str = "GET", data: Optional[dict] = None) -> Optional[dict]:
    """Helper function to call backend API"""
    url = f"{BACKEND_API_URL}{endpoint}"
    logger.info(f"[BackendAPI] Making {method} request to {url} with data: {data}")
    
    try:
        async with aiohttp.ClientSession() as session:
            if method == "GET":
                async with session.get(url) as response:
                    logger.info(f"[BackendAPI] GET response status: {response.status}")
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"[BackendAPI] GET response data: {result}")
                        return result
                    else:
                        logger.error(f"[BackendAPI] GET request failed with status {response.status}")
                        return None
            elif method == "POST":
                async with session.post(url, json=data) as response:
                    logger.info(f"[BackendAPI] POST response status: {response.status}")
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"[BackendAPI] POST response data: {result}")
                        return result
                    else:
                        logger.error(f"[BackendAPI] POST request failed with status {response.status}")
                        return None
            elif method == "PUT":
                async with session.put(url, json=data) as response:
                    logger.info(f"[BackendAPI] PUT response status: {response.status}")
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"[BackendAPI] PUT response data: {result}")
                        return result
                    else:
                        logger.error(f"[BackendAPI] PUT request failed with status {response.status}")
                        return None
    except Exception as e:
        logger.error(f"[BackendAPI] Backend API call failed: {e}")
        return None

def validate_language_code(lang: str) -> str:
    """Validate and normalize language code"""
    logger.info(f"[LanguageValidation] Input language: '{lang}' (type: {type(lang)})")
    
    if not lang or not isinstance(lang, str):
        logger.info(f"[LanguageValidation] Invalid input, returning 'en'")
        return 'en'
    
    # Normalize to lowercase and ensure it's 2-3 characters
    lang = lang.lower().strip()
    logger.info(f"[LanguageValidation] After normalization: '{lang}'")
    
    if len(lang) < 2 or len(lang) > 3:
        logger.info(f"[LanguageValidation] Length {len(lang)} not in range 2-3, returning 'en'")
        return 'en'
    
    # Allow only letters
    if not lang.isalpha():
        logger.info(f"[LanguageValidation] Contains non-letters, returning 'en'")
        return 'en'
    
    logger.info(f"[LanguageValidation] Final validated language: '{lang}'")
    return lang

def validate_name(name: Optional[str]) -> Optional[str]:
    """Validate and clean name field"""
    if not name:
        return None
    
    # Strip whitespace
    name = name.strip()
    
    # Check length (max 100 characters as per backend)
    if len(name) > 100:
        name = name[:100]
    
    # Only check if it's not empty after trimming
    # Database handles Unicode characters including emojis and Cyrillic
    return name if name else None

async def get_or_create_user_backend(telegram_id: int, user_tg_lang: str, first_name: Optional[str] = None, last_name: Optional[str] = None) -> Optional[dict]:
    """Get or create user in backend with all language settings set to Telegram language"""
    logger.info(f"[BackendUserCreation] Starting user creation for telegram_id: {telegram_id}")
    logger.info(f"[BackendUserCreation] Input user_tg_lang: '{user_tg_lang}'")
    
    # Validate and clean input data
    validated_lang = validate_language_code(user_tg_lang)
    validated_first_name = validate_name(first_name)
    validated_last_name = validate_name(last_name)
    
    logger.info(f"[BackendUserCreation] Validated language: '{validated_lang}'")
    logger.info(f"[BackendUserCreation] Validated first_name: '{validated_first_name}'")
    logger.info(f"[BackendUserCreation] Validated last_name: '{validated_last_name}'")
    
    data = {
        "telegram_id": telegram_id,
        "user_tg_lang": validated_lang,  # User's Telegram language
        "movies_lang": validated_lang,   # Movies language = Telegram language
        "bot_lang": validated_lang,      # Bot interface language = Telegram language
        "first_name": validated_first_name,
        "last_name": validated_last_name,
        "is_premium": False
    }
    
    logger.info(f"[BackendUserCreation] Final data being sent to backend: {data}")
    return await call_backend_api("/users/get-or-create", "POST", data)

@router.message(CommandStart())
async def start_handler(message: types.Message, state: FSMContext):
    """Simple start handler - Welcome message + Main menu + Create user in DB"""
    if not message.from_user:
        logger.error("Message from_user is None")
        return
        
    user_id = message.from_user.id
    logger.info(f"[User {user_id}] Triggered /start")

    # Detailed language detection logging
    raw_language_code = message.from_user.language_code
    logger.info(f"[User {user_id}] Raw Telegram language_code: {raw_language_code}")
    
    # Log all available user information for debugging
    logger.info(f"[User {user_id}] User info - first_name: '{message.from_user.first_name}', last_name: '{message.from_user.last_name}'")
    logger.info(f"[User {user_id}] User info - username: '{message.from_user.username}', is_premium: {message.from_user.is_premium}")
    
    # Validate against supported languages
    supported_languages = ['en', 'uk', 'ru']
    user_lang = raw_language_code or 'en'
    if user_lang not in supported_languages:
        user_lang = 'en'  # Fallback to English
        logger.info(f"[User {user_id}] Unsupported language '{raw_language_code}' detected, falling back to 'en'")
    
    logger.info(f"[User {user_id}] Final validated language code: {user_lang}")

    # Create user in backend database with all language settings set to Telegram language
    user_data = await get_or_create_user_backend(
        telegram_id=user_id,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        user_tg_lang=user_lang
    )

    # Set FSM locale for i18n
    await state.update_data(locale=user_lang)
    logger.info(f"[User {user_id}] FSM locale set to: {user_lang}")

    # Show welcome message with main menu
    keyboard = get_main_menu_keyboard()
    await message.answer_animation(
        animation=WELCOME_GIF_URL,
        caption=gettext(WELCOME_MESSAGE),
        reply_markup=keyboard
    )

    if not user_data:
        logger.error(f"[User {user_id}] Failed to create/get user from backend")
        await notify_admin(f"[User {user_id}] Failed to create/get user from backend, first name: {message.from_user.first_name}, last name: {message.from_user.last_name}, user_tg_lang: {user_lang}")
    else:
        logger.info(f"[User {user_id}] User created/retrieved successfully: {user_data}")

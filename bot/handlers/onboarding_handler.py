import aiohttp
from aiogram import Router, types, F
from aiogram_i18n import I18nContext
from aiogram.filters import CommandStart, Filter
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from bot.locales.keys import WELCOME_MESSAGE, PREFERENCES_SUGGESTION, SET_PREFERENCES_BTN, MAYBE_LATER_BTN, \
    ONBOARDING_WELCOME, ONBOARDING_NAME_QUESTION, ONBOARDING_SKIPPED, CUSTOM_NAME_PROMPT, NAME_TOO_LONG, \
    END_ONBOARDING_SUCCESS, END_ONBOARDING_FAIL, ONBOARDING_LANGUAGE_QUESTION, NAME_TOO_SHORT
from bot.utils.logger import Logger
from bot.utils.session_manager import SessionManager
from bot.handlers.main_menu_btns_handler import get_main_menu_keyboard
from bot.keyboards.onboarding_keyboard import get_name_selection_keyboard, get_language_selection_keyboard
from bot.utils.notify_admin import notify_admin
from bot.utils.message_utils import smart_edit_or_send
from bot.utils.i18n_setup import initialize_user_language, set_user_language
from typing import Optional

router = Router()
logger = Logger().get_logger()

# Backend API URL
BACKEND_API_URL = "https://moviebot.click"

# Welcome GIF URL - replace with your actual GIF
WELCOME_GIF_URL = "https://media.giphy.com/media/3o7abKhOpu0NwenH3O/giphy.gif"

# Onboarding GIF URL - replace with your actual GIF
ONBOARDING_GIF_URL = "https://media.giphy.com/media/JE6xHkcUPtYs0/giphy.gif"


class OnboardingInputStateFilter(Filter):
    async def __call__(self, message: types.Message) -> bool:
        if not message.from_user:
            return False
        state = await SessionManager.get_state(message.from_user.id)
        return state == "onboarding:waiting_for_custom_name"


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

async def get_or_create_user_backend(telegram_id: int, user_tg_lang: str, first_name: Optional[str] = None, last_name: Optional[str] = None) -> Optional[dict]:
    """Get or create user in backend with proper language setup"""
    data = {
        "telegram_id": telegram_id,
        "user_tg_lang": user_tg_lang,  # Set Telegram language
        "movies_lang": user_tg_lang,   # Default movies language to Telegram language
        "bot_lang": user_tg_lang,      # Default bot language to Telegram language
        "first_name": first_name,
        "last_name": last_name,
        "is_premium": False
    }
    return await call_backend_api("/users/get-or-create", "POST", data)

async def update_user_onboarding_backend(telegram_id: int, custom_name: Optional[str] = None, bot_lang: Optional[str] = None) -> Optional[dict]:
    # TODO: when premium users will be available we can propose becoming premium here or here
    """Update user onboarding information with bot language"""
    
    # Get user's Telegram language for the required field
    # For now, we'll use the bot_lang as the user_tg_lang since we don't have it stored
    # In a real scenario, you'd want to get this from the user data
    user_tg_lang = bot_lang or "en"
    
    data = {
        "telegram_id": telegram_id,
        "user_tg_lang": user_tg_lang,  # Required by API
        "custom_name": custom_name,
        "bot_lang": bot_lang,  # Set bot interface language
        "is_premium": False
    }
    
    logger.info(f"[OnboardingBackend] Sending data to backend: {data}")
    
    result = await call_backend_api("/users/onboarding", "POST", data)
    
    logger.info(f"[OnboardingBackend] Backend response: {result}")
    
    return result

@router.message(CommandStart())
async def start_handler(message: types.Message, i18n: I18nContext, state: FSMContext):
    """Main start handler - Immediate Service + Optional Onboarding"""
    if not message.from_user:
        logger.error("Message from_user is None")
        return
        
    user_id = message.from_user.id
    logger.info(f"[User {user_id}] Triggered /start")

    # Use Telegram language code directly
    user_lang = message.from_user.language_code or 'en'

    # Initialize user language in FSM (backend → FSM sync)
    await initialize_user_language(user_id, state, user_lang)

    # Ensure user exists in backend database
    user_data = await get_or_create_user_backend(
        telegram_id=user_id,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        user_tg_lang=user_lang
    )

    # ALWAYS show main menu immediately (Immediate Service)
    keyboard = get_main_menu_keyboard(i18n)
    await message.answer_animation(
        animation=WELCOME_GIF_URL,
        caption=i18n.get(WELCOME_MESSAGE),
        reply_markup=keyboard
    )

    if not user_data:
        logger.error(f"[User {user_id}] Failed to create/get user from backend")
        await notify_admin(f"[User {user_id}] Failed to create/get user from backend, first name: {message.from_user.first_name}, last name: {message.from_user.last_name}, user_tg_lang: {user_lang}")

    # Optionally suggest onboarding if not completed (Optional Onboarding)
    if not user_data or not user_data.get("is_onboarded", False):
        await message.answer(
            i18n.get(PREFERENCES_SUGGESTION),
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text=i18n.get(SET_PREFERENCES_BTN), callback_data="start_onboarding")],
                [types.InlineKeyboardButton(text=i18n.get(MAYBE_LATER_BTN), callback_data="skip_onboarding")]
            ])
        )

@router.callback_query(F.data == "start_onboarding")
async def start_onboarding_handler(query: types.CallbackQuery, i18n: I18nContext):
    """Start the onboarding process"""
    #TODO: when premium users will be available we can propose becoming premium here or here
    if not query.from_user:
        return
        
    user_id = query.from_user.id
    logger.info(f"[User {user_id}] Started onboarding")

    if query.message:
        await query.message.answer_animation(
            animation=ONBOARDING_GIF_URL,
            caption=i18n.get(ONBOARDING_WELCOME)
        )
        
        keyboard = get_name_selection_keyboard(query.from_user, i18n)
        await query.message.answer(
            i18n.get(ONBOARDING_NAME_QUESTION),
            reply_markup=keyboard
        )
        logger.info(f"[User {user_id}] Sent name selection keyboard")
    
    await query.answer()

@router.callback_query(F.data == "skip_onboarding")
async def skip_onboarding_handler(query: types.CallbackQuery, i18n: I18nContext):
    """Skip onboarding and continue with default settings"""
    if not query.from_user:
        return
        
    user_id = query.from_user.id
    logger.info(f"[User {user_id}] Skipped onboarding")
    
    # Use smart edit or send utility
    await smart_edit_or_send(
        message=query,
        text=i18n.get(ONBOARDING_SKIPPED)
    )
    await query.answer()

@router.callback_query(F.data.startswith("select_name:"))
async def select_name_handler(query: types.CallbackQuery, i18n: I18nContext):
    """Handle name selection"""
    if not query.from_user or not query.data:
        return
        
    user_id = query.from_user.id
    selected_name = query.data.split(":", 1)[1]
    
    logger.info(f"[User {user_id}] Selected name: {selected_name}")
    
    # Store the selected name in SessionManager data
    await SessionManager.update_data(user_id, {"custom_name": selected_name})
    
    # Show language selection
    if query.message and isinstance(query.message, Message):
        await show_language_selection(query.message, selected_name, i18n)
    await query.answer()

@router.callback_query(F.data == "custom_name")
async def custom_name_handler(query: types.CallbackQuery, i18n: I18nContext):
    """Handle custom name input"""
    if not query.from_user:
        return
        
    user_id = query.from_user.id
    logger.info(f"[User {user_id}] Requested custom name input")
    
    await SessionManager.set_state(user_id, "onboarding:waiting_for_custom_name")
    logger.info(f"[User {user_id}] SessionManager state set to: onboarding:waiting_for_custom_name")
    
    # Verify state was set correctly
    verify_state = await SessionManager.get_state(user_id)
    logger.info(f"[User {user_id}] VERIFICATION - State after setting: '{verify_state}'")
    
    # Use smart edit or send utility
    await smart_edit_or_send(
        message=query,
        text=i18n.get(CUSTOM_NAME_PROMPT)
    )
    logger.info(f"[User {user_id}] Sent custom name prompt")
    await query.answer()

@router.message(F.text)
async def handle_custom_name_input(message: types.Message, i18n: I18nContext):
    """Handle custom name text input"""
    if not message.from_user:
        return
        
    user_id = message.from_user.id
    current_state = await SessionManager.get_state(user_id)
    
    # Only process if we're in the correct state
    if current_state != "onboarding:waiting_for_custom_name":
        # Not in onboarding state, let other handlers process this
        # We need to explicitly pass this to the fallback handler
        from bot.handlers.fallback_input_handler import fallback_input_handler
        await fallback_input_handler(message, i18n)
        return
    
    logger.info(f"[User {user_id}] ONBOARDING HANDLER PROCESSING custom name input: '{message.text}'")
    
    # Handle non-text messages (photos, stickers, voice, etc.)
    if not message.text:
        await message.answer(i18n.get(CUSTOM_NAME_PROMPT))
        return
    
    custom_name = message.text.strip()
    
    # Check if name is empty
    if not custom_name:
        await message.answer(i18n.get(NAME_TOO_SHORT))
        return
    
    # Check maximum length only
    if len(custom_name) > 50:
        await message.answer(i18n.get(NAME_TOO_LONG))
        return
    
    logger.info(f"[User {user_id}] Entered custom name: {custom_name}")
    
    # Store the custom name in SessionManager data
    await SessionManager.update_data(user_id, {"custom_name": custom_name})
    
    # Clear the state since we're done with input
    await SessionManager.clear_state(user_id)
    
    # Show language selection
    await show_language_selection(message, custom_name, i18n)

async def show_language_selection(message: types.Message, user_name: str, i18n: I18nContext):
    """Show language selection keyboard"""
    if not message.from_user:
        return
        
    # Use Telegram language code directly
    user_lang = message.from_user.language_code or 'en'
    
    keyboard = get_language_selection_keyboard(user_lang,i18n)
    
    await message.answer(i18n.get(ONBOARDING_LANGUAGE_QUESTION, user_name=user_name),
        reply_markup=keyboard
    )

@router.callback_query(F.data.startswith("select_lang:"))
async def select_language_handler(query: types.CallbackQuery, i18n: I18nContext, state: FSMContext):
    """Handle language selection"""
    if not query.from_user or not query.data:
        return
        
    user_id = query.from_user.id
    selected_language = query.data.split(":", 1)[1]
    
    # Get custom name from SessionManager data
    data = await SessionManager.get_data(user_id)
    custom_name = data.get("custom_name")
    
    logger.info(f"[User {user_id}] Selected language: {selected_language}, custom_name: {custom_name}")
    
    # Update user language in both FSM and backend using new helper function
    success = await set_user_language(user_id, selected_language, state)
    
    if success:
        logger.info(f"[User {user_id}] Successfully updated language to: {selected_language}")
        
        # Update backend with onboarding completion
        user_data = await update_user_onboarding_backend(
            telegram_id=user_id,
            custom_name=custom_name,
            bot_lang=selected_language
        )
        
        # Debug: Log what we received from backend
        if user_data:
            logger.info(f"[User {user_id}] Backend response: {user_data}")
            logger.info(f"[User {user_id}] Backend returned bot_lang: {user_data.get('bot_lang')}")
        else:
            logger.error(f"[User {user_id}] Backend returned None/empty response!")
        
        # Clear all onboarding data
        await SessionManager.clear_data(user_id)
        await SessionManager.clear_state(user_id)
        
        keyboard = get_main_menu_keyboard(i18n)
        if user_data:
            await smart_edit_or_send(
                message=query,
                text=i18n.get(END_ONBOARDING_SUCCESS),
                reply_markup=keyboard
            )
        else:
            await smart_edit_or_send(
                message=query,
                text=i18n.get(END_ONBOARDING_FAIL),
                reply_markup=keyboard
            )
    else:
        logger.error(f"[User {user_id}] Failed to update language to: {selected_language}")
        keyboard = get_main_menu_keyboard(i18n)
        await smart_edit_or_send(
            message=query,
            text=i18n.get(END_ONBOARDING_FAIL),
            reply_markup=keyboard
        )

    await query.answer()

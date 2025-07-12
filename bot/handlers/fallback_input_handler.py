from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.i18n import gettext
from bot.locales.keys import FALLBACK_MENU_PROMPT
from bot.utils.session_manager import SessionManager
from bot.handlers.main_menu_btns_handler import get_main_menu_keyboard
from bot.utils.logger import Logger

router = Router()
logger = Logger().get_logger()

@router.message(Command("test_locale"))
async def test_locale_handler(message: types.Message, state: FSMContext):
    """Test command to check current locale detection."""
    if not message.from_user:
        return
    user_id = message.from_user.id
    logger.info(f"[TestLocale] User {user_id} requested locale test")
    
    # Get FSM data
    try:
        fsm_data = await state.get_data()
        fsm_locale = fsm_data.get("user_locale", "NOT_SET")
        logger.info(f"[TestLocale] FSM locale: {fsm_locale}")
    except Exception as e:
        logger.error(f"[TestLocale] Failed to get FSM data: {e}")
        fsm_locale = "ERROR"
    
    # Send response
    test_msg = f"🔍 Locale Test Results:\n"
    test_msg += f"• FSM Storage: {fsm_locale}\n"
    test_msg += f"• User ID: {user_id}"
    
    await message.answer(test_msg)

@router.message(Command("set_lang"))
async def set_language_handler(message: types.Message, state: FSMContext):
    """Test command to manually set user language."""
    if not message.from_user:
        return
    
    user_id = message.from_user.id
    args = message.text.split()
    
    if len(args) != 2:
        await message.answer("Usage: /set_lang <language_code>\nExample: /set_lang en")
        return
    
    lang_code = args[1].lower()
    if lang_code not in ['en', 'uk', 'ru']:
        await message.answer("Supported languages: en, uk, ru")
        return
    
    logger.info(f"[SetLang] User {user_id} manually setting language to: {lang_code}")
    
    # Update user's bot language in backend
    from bot.utils.user_service import UserService
    try:
        success = await UserService.set_user_bot_language(user_id, lang_code)
        if success:
            await message.answer(f"✅ Language set to: {lang_code}")
        else:
            await message.answer("❌ Failed to set language")
    except Exception as e:
        logger.error(f"[SetLang] Error setting language: {e}")
        await message.answer("❌ Error setting language")

@router.message(Command("test_i18n"))
async def test_i18n_handler(message: types.Message, state: FSMContext):
    """Test command to check I18n middleware functionality."""
    if not message.from_user:
        return
    user_id = message.from_user.id
    logger.info(f"[TestI18n] User {user_id} requested I18n test")
    
    # Get FSM data
    try:
        fsm_data = await state.get_data()
        fsm_locale = fsm_data.get("user_locale", "NOT_SET")
        logger.info(f"[TestI18n] FSM locale: {fsm_locale}")
    except Exception as e:
        logger.error(f"[TestI18n] Failed to get FSM data: {e}")
        fsm_locale = "ERROR"
    
    # Get Telegram language
    telegram_lang = message.from_user.language_code or "NOT_SET"
    logger.info(f"[TestI18n] Telegram language: {telegram_lang}")
    
    # Get user info from backend
    from bot.utils.user_service import UserService
    try:
        user_data = await UserService.get_user_info(user_id)
        backend_lang = user_data.get("user_tg_lang", "NOT_FOUND") if user_data else "USER_NOT_FOUND"
        backend_bot_lang = user_data.get("bot_lang", "NOT_FOUND") if user_data else "USER_NOT_FOUND"
        backend_movies_lang = user_data.get("movies_lang", "NOT_FOUND") if user_data else "USER_NOT_FOUND"
    except Exception as e:
        logger.error(f"[TestI18n] Failed to get backend user data: {e}")
        backend_lang = "ERROR"
        backend_bot_lang = "ERROR"
        backend_movies_lang = "ERROR"
    
    # Send response
    test_msg = f"🔍 I18n Test Results:\n"
    test_msg += f"• FSM Storage: {fsm_locale}\n"
    test_msg += f"• Telegram Lang: {telegram_lang}\n"
    test_msg += f"• Backend user_tg_lang: {backend_lang}\n"
    test_msg += f"• Backend bot_lang: {backend_bot_lang}\n"
    test_msg += f"• Backend movies_lang: {backend_movies_lang}\n"
    test_msg += f"• User ID: {user_id}"
    
    await message.answer(test_msg)

@router.message()
async def fallback_input_handler(message: types.Message, state: FSMContext):
    if not message.from_user:
        return
        
    user_id = message.from_user.id
    session_state = await SessionManager.get_state(user_id)
    
    logger.info(f"[User {user_id}] FALLBACK HANDLER REACHED with message: '{message.text}', session_state: {session_state}")
    
    # Debug: Check FSM data
    try:
        fsm_data = await state.get_data()
        fsm_locale = fsm_data.get("user_locale", "NOT_SET")
        logger.info(f"[User {user_id}] FALLBACK HANDLER - FSM locale: {fsm_locale}")
    except Exception as e:
        logger.error(f"[User {user_id}] FALLBACK HANDLER - Failed to get FSM data: {e}")
        fsm_locale = "ERROR"

    if not session_state:
        logger.info(f"[User {user_id}] Sent free message without active state. Prompting to use main menu.")

        await message.answer(
            gettext(FALLBACK_MENU_PROMPT),
            reply_markup=get_main_menu_keyboard()
        )
    else:
        return

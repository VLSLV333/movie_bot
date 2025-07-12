from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram_i18n import I18nContext
from bot.locales.keys import FALLBACK_MENU_PROMPT
from bot.utils.session_manager import SessionManager
from bot.handlers.main_menu_btns_handler import get_main_menu_keyboard
from bot.utils.logger import Logger

router = Router()
logger = Logger().get_logger()

@router.message(Command("test_locale"))
async def test_locale_handler(message: types.Message, state: FSMContext, i18n: I18nContext):
    """Test command to check current locale detection."""
    if not message.from_user:
        return
    user_id = message.from_user.id
    logger.info(f"[TestLocale] User {user_id} requested locale test")
    
    # Get current locale from I18n context
    current_locale = i18n.locale
    logger.info(f"[TestLocale] I18n context locale: {current_locale}")
    
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
    test_msg += f"• I18n Context: {current_locale}\n"
    test_msg += f"• FSM Storage: {fsm_locale}\n"
    test_msg += f"• User ID: {user_id}"
    
    await message.answer(test_msg)

@router.message(Command("test_i18n"))
async def test_i18n_handler(message: types.Message, i18n: I18nContext, state: FSMContext):
    """Test command to check I18n middleware functionality."""
    if not message.from_user:
        return
    user_id = message.from_user.id
    logger.info(f"[TestI18n] User {user_id} requested I18n test")
    
    # Get current locale from I18n context
    current_locale = i18n.locale
    logger.info(f"[TestI18n] I18n context locale: {current_locale}")
    
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
    
    # Send response
    test_msg = f"🔍 I18n Test Results:\n"
    test_msg += f"• I18n Context: {current_locale}\n"
    test_msg += f"• FSM Storage: {fsm_locale}\n"
    test_msg += f"• Telegram Lang: {telegram_lang}\n"
    test_msg += f"• User ID: {user_id}"
    
    await message.answer(test_msg)

@router.message()
async def fallback_input_handler(message: types.Message, i18n: I18nContext, state: FSMContext):
    if not message.from_user:
        return
        
    user_id = message.from_user.id
    session_state = await SessionManager.get_state(user_id)
    
    logger.info(f"[User {user_id}] FALLBACK HANDLER REACHED with message: '{message.text}', session_state: {session_state}")
    logger.info(f"[User {user_id}] FALLBACK HANDLER - I18n context locale: {i18n.locale}")
    logger.info(f"[User {user_id}] FALLBACK HANDLER - I18n context available: {i18n is not None}")
    
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
            i18n.get(FALLBACK_MENU_PROMPT),
            reply_markup=get_main_menu_keyboard(i18n)
        )
    else:
        return

from aiogram import Router, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.i18n import gettext
from bot.locales.keys import FALLBACK_MENU_PROMPT
from bot.utils.session_manager import SessionManager
from bot.handlers.main_menu_btns_handler import get_main_menu_keyboard
from bot.utils.logger import Logger

router = Router()
logger = Logger().get_logger()

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

    if not session_state:
        logger.info(f"[User {user_id}] Sent free message without active state. Prompting to use main menu.")

        await message.answer(
            gettext(FALLBACK_MENU_PROMPT),
            reply_markup=get_main_menu_keyboard()
        )
    else:
        return

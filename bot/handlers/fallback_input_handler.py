from aiogram import Router, types
from aiogram_i18n import I18nContext
from bot.locales.keys import FALLBACK_MENU_PROMPT
from bot.utils.session_manager import SessionManager
from bot.handlers.main_menu_btns_handler import get_main_menu_keyboard
from bot.utils.logger import Logger

router = Router()
logger = Logger().get_logger()

@router.message()
async def fallback_input_handler(message: types.Message, i18n: I18nContext):
    if not message.from_user:
        return
        
    user_id = message.from_user.id
    state = await SessionManager.get_state(user_id)
    
    logger.info(f"[User {user_id}] FALLBACK HANDLER REACHED with message: '{message.text}', state: {state}")

    if not state:
        logger.info(f"[User {user_id}] Sent free message without active state. Prompting to use main menu.")

        await message.answer(
            i18n.get(FALLBACK_MENU_PROMPT),
            reply_markup=get_main_menu_keyboard(i18n)
        )
    else:
        return

from aiogram import Router, types
from bot.utils.session_manager import SessionManager
from bot.handlers.main_menu_btns_handler import get_main_menu_keyboard
from bot.utils.logger import Logger

router = Router()
logger = Logger().get_logger()

@router.message()
async def fallback_input_handler(message: types.Message):
    user_id = message.from_user.id
    state = await SessionManager.get_state(user_id)

    if not state:
        logger.info(f"[User {user_id}] Sent free message without active state. Prompting to use main menu.")

        await message.answer(
            "Use the menu below to find movies, get movies suggestions, or even download movies 🎬👇",
            reply_markup=get_main_menu_keyboard()
        )
    else:
        # Do nothing – let actual state-specific handlers handle this
        return

from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from bot.utils.user_service import UserService
from bot.utils.logger import Logger

router = Router()
logger = Logger().get_logger()


@router.callback_query(F.data.startswith("change_bot_lang:"))
async def change_bot_language_handler(query: types.CallbackQuery, state: FSMContext):
    if not query.data:
        await query.answer("Invalid callback data")
        return
        
    user_id = query.from_user.id
    selected_lang = query.data.split(":")[1]

    # Validate against supported languages
    supported_languages = ['en', 'uk', 'ru']
    if selected_lang not in supported_languages:
        await query.answer("Unsupported language")
        return

    # Set FSM locale for i18n - THIS CHANGES THE INTERFACE LANGUAGE
    await state.update_data(locale=selected_lang)
    logger.info(f"[User {user_id}] Bot language changed to: {selected_lang}")

    # Update backend for persistence across sessions
    await UserService.set_user_bot_language(user_id, selected_lang)

    # Confirm with translated message
    await query.answer()
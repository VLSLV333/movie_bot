from aiogram import Router, types, F
from aiogram.utils.i18n import gettext
from aiogram.fsm.context import FSMContext
from bot.locales.keys import (
    OPTIONS_WHAT_TO_CONFIGURE, OPTIONS_CHOOSE_BOT_LANGUAGE, OPTIONS_CHOOSE_MOVIES_LANGUAGE,
    OPTIONS_LANGUAGE_UPDATED, SOMETHING_WENT_WRONG_TRY_MAIN_MENU
)
from bot.utils.logger import Logger
from bot.utils.user_service import UserService
from bot.utils.command_updater import update_bot_commands_for_user
from bot.keyboards.options_keyboard import (
    get_options_main_keyboard, get_options_bot_language_keyboard, get_options_movies_language_keyboard
)
from bot.handlers.main_menu_btns_handler import get_main_menu_keyboard
from bot.utils.message_utils import smart_edit_or_send

router = Router()
logger = Logger().get_logger()

# Backend API URL
BACKEND_API_URL = "https://moviebot.click"

# --- Options Logic (reusable for both command and callback) ---
async def handle_options_request(message_or_query):
    """Common logic for handling options requests from both commands and callbacks"""
    keyboard = get_options_main_keyboard()
    
    await smart_edit_or_send(
        message=message_or_query,
        text=gettext(OPTIONS_WHAT_TO_CONFIGURE),
        reply_markup=keyboard
    )


@router.message(F.text == "/options")
async def options_command_handler(message: types.Message):
    """Handle /options command"""
    await handle_options_request(message)


@router.callback_query(F.data == "options")
async def options_handler(query: types.CallbackQuery):
    """Handle options button callback"""
    await handle_options_request(query)
    await query.answer()

@router.callback_query(F.data == "options_bot_lang")
async def options_bot_language_handler(query: types.CallbackQuery):
    """Handle bot language option selection"""
    logger.info(f"[User {query.from_user.id}] Clicked 'Bot language' option")
    
    keyboard = get_options_bot_language_keyboard()
    
    await smart_edit_or_send(
        message=query,
        text=gettext(OPTIONS_CHOOSE_BOT_LANGUAGE),
        reply_markup=keyboard
    )
    await query.answer()

@router.callback_query(F.data == "options_movies_lang")
async def options_movies_language_handler(query: types.CallbackQuery, state: FSMContext):
    """Handle movies language option selection"""
    logger.info(f"[User {query.from_user.id}] Clicked 'Movies language' option")
    
    keyboard = get_options_movies_language_keyboard()
    
    await smart_edit_or_send(
        message=query,
        text=gettext(OPTIONS_CHOOSE_MOVIES_LANGUAGE),
        reply_markup=keyboard
    )
    await query.answer()

@router.callback_query(lambda c: c.data.startswith("options_bot_lang_select:"))
async def options_bot_language_selection_handler(query: types.CallbackQuery, state: FSMContext):
    """Handle bot language selection in options"""
    if not query.data:
        keyboard = get_main_menu_keyboard()
        await query.message.answer(text=gettext(SOMETHING_WENT_WRONG_TRY_MAIN_MENU),reply_markup=keyboard)
        return
        
    user_id = query.from_user.id
    selected_lang = query.data.split(":")[1]
    
    logger.info(f"[User {user_id}] Selected bot language in options: {selected_lang}")
    
    # Update FSM locale immediately (changes interface language)
    await state.update_data(locale=selected_lang)
    logger.info(f"[User {user_id}] FSM locale updated to: {selected_lang}")
    
    # Update backend
    await UserService.set_user_bot_language(user_id, selected_lang)
    
    # Update bot commands for this user to match the new language
    try:
        await update_bot_commands_for_user(query.bot, user_id, selected_lang)
        logger.info(f"[User {user_id}] Bot commands updated to language: {selected_lang}")
    except Exception as e:
        logger.error(f"[User {user_id}] Failed to update bot commands: {e}")
    
    # Show success message and return to options menu
    keyboard = get_options_main_keyboard()
    
    await smart_edit_or_send(
        message=query,
        text=gettext(OPTIONS_LANGUAGE_UPDATED),
        reply_markup=keyboard
    )
    await query.answer()

@router.callback_query(lambda c: c.data.startswith("options_movies_lang_select:"))
async def options_movies_language_selection_handler(query: types.CallbackQuery, state: FSMContext):
    """Handle movies language selection in options"""
    if not query.data:
        keyboard = get_main_menu_keyboard()
        await query.message.answer(text=gettext(SOMETHING_WENT_WRONG_TRY_MAIN_MENU), reply_markup=keyboard)
        return
        
    user_id = query.from_user.id
    selected_lang = query.data.split(":")[1]
    
    logger.info(f"[User {user_id}] Selected movies language in options: {selected_lang}")
    
    # Update backend with movies language preference using UserService
    success = await UserService.set_user_movies_language(user_id, selected_lang)
    keyboard = get_options_main_keyboard()

    if success:
        logger.info(f"[User {user_id}] Successfully updated movies language to: {selected_lang}")
        await smart_edit_or_send(
            message=query,
            text=gettext(OPTIONS_LANGUAGE_UPDATED),
            reply_markup=keyboard
        )
        await query.answer()
    else:
        logger.error(f"[User {user_id}] Failed to update movies language to: {selected_lang}")
        keyboard = get_main_menu_keyboard()
        await query.message.answer(text=gettext(SOMETHING_WENT_WRONG_TRY_MAIN_MENU), reply_markup=keyboard)
        return

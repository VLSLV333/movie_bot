import aiohttp
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import CommandStart
from aiogram.types import Message
from bot.utils.logger import Logger
from bot.handlers.main_menu_btns_handler import get_main_menu_keyboard
from bot.keyboards.onboarding_keyboard import get_name_selection_keyboard, get_language_selection_keyboard
from bot.utils.notify_admin import notify_admin
from bot.utils.message_utils import smart_edit_or_send
from typing import Optional

router = Router()
logger = Logger().get_logger()

# Backend API URL
BACKEND_API_URL = "https://moviebot.click"

class OnboardingStates(StatesGroup):
    waiting_for_custom_name = State()
    waiting_for_language = State()

# Welcome GIF URL - replace with your actual GIF
WELCOME_GIF_URL = "https://media.giphy.com/media/3o7abKhOpu0NwenH3O/giphy.gif"

# Onboarding GIF URL - replace with your actual GIF
ONBOARDING_GIF_URL = "https://media.giphy.com/media/JE6xHkcUPtYs0/giphy.gif"

async def call_backend_api(endpoint: str, method: str = "GET", data: Optional[dict] = None) -> Optional[dict]:
    """Helper function to call backend API"""
    url = f"{BACKEND_API_URL}{endpoint}"
    
    try:
        async with aiohttp.ClientSession() as session:
            if method == "GET":
                async with session.get(url) as response:
                    return await response.json() if response.status == 200 else None
            elif method == "POST":
                async with session.post(url, json=data) as response:
                    return await response.json() if response.status == 200 else None
            elif method == "PUT":
                async with session.put(url, json=data) as response:
                    return await response.json() if response.status == 200 else None
    except Exception as e:
        logger.error(f"Backend API call failed: {e}")
        return None

async def get_or_create_user_backend(telegram_id: int, preferred_language: str, first_name: Optional[str] = None, last_name: Optional[str] = None) -> Optional[dict]:
    """Get or create user in backend database"""
    data = {
        "telegram_id": telegram_id,
        "first_name": first_name,
        "last_name": last_name,
        "preferred_language": preferred_language
    }
    return await call_backend_api("/users/get-or-create", "POST", data)

async def update_user_onboarding_backend(telegram_id: int, custom_name: Optional[str] = None, preferred_language: Optional[str] = None) -> Optional[dict]:
    """Update user onboarding in backend database"""
    data = {
        "telegram_id": telegram_id,
        "custom_name": custom_name,
        "preferred_language": preferred_language
    }
    return await call_backend_api("/users/onboarding", "POST", data)

@router.message(CommandStart())
async def start_handler(message: types.Message):
    """Main start handler - Immediate Service + Optional Onboarding"""
    if not message.from_user:
        logger.error("Message from_user is None")
        return
        
    user_id = message.from_user.id
    logger.info(f"[User {user_id}] Triggered /start")

    # Use Telegram language code directly
    user_lang = message.from_user.language_code or 'en'

    # Ensure user exists in backend database
    user_data = await get_or_create_user_backend(
        telegram_id=user_id,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        preferred_language=user_lang
    )

    # ALWAYS show main menu immediately (Immediate Service)
    keyboard = get_main_menu_keyboard()
    await message.answer_animation(
        animation=WELCOME_GIF_URL,
        caption="Hi, I am Juli your movie friend bot! 🎬\n\nI can help you find, watch and download movies!",
        reply_markup=keyboard
    )

    if not user_data:
        logger.error(f"[User {user_id}] Failed to create/get user from backend")
        await notify_admin(f"[User {user_id}] Failed to create/get user from backend, first name: {message.from_user.first_name}, last name: {message.from_user.last_name}, preferred_language: {user_lang}")

    # Optionally suggest onboarding if not completed (Optional Onboarding)
    if not user_data or not user_data.get("is_onboarded", False):
        await message.answer(
            "💡 Want to get better movies? Answer 2 questions",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="⚙️ Set Preferences", callback_data="start_onboarding")],
                [types.InlineKeyboardButton(text="❌ Maybe Later", callback_data="skip_onboarding")]
            ])
        )

@router.callback_query(F.data == "start_onboarding")
async def start_onboarding_handler(query: types.CallbackQuery):
    """Start the onboarding process"""
    if not query.from_user:
        return
        
    user_id = query.from_user.id
    logger.info(f"[User {user_id}] Started onboarding")

    # Show welcome GIF and name selection
    if query.message:
        await query.message.answer_animation(
            animation=ONBOARDING_GIF_URL,
            caption="Awesome! Only 2 questions"
        )
        
        # Show name selection keyboard
        keyboard = get_name_selection_keyboard(query.from_user)
        await query.message.answer(
            "Choose how to call you:",
            reply_markup=keyboard
        )
    
    await query.answer()

@router.callback_query(F.data == "skip_onboarding")
async def skip_onboarding_handler(query: types.CallbackQuery):
    """Skip onboarding and continue with default settings"""
    if not query.from_user:
        return
        
    user_id = query.from_user.id
    logger.info(f"[User {user_id}] Skipped onboarding")
    
    # Use smart edit or send utility
    await smart_edit_or_send(
        message=query,
        text="✅ Got it! You can always change your preferences later in the settings."
    )
    await query.answer()

@router.callback_query(F.data.startswith("select_name:"))
async def select_name_handler(query: types.CallbackQuery, state: FSMContext):
    """Handle name selection"""
    if not query.from_user or not query.data:
        return
        
    user_id = query.from_user.id
    selected_name = query.data.split(":", 1)[1]
    
    logger.info(f"[User {user_id}] Selected name: {selected_name}")
    
    # Store the selected name in state
    await state.update_data(custom_name=selected_name)
    
    # Show language selection
    if query.message and isinstance(query.message, Message):
        await show_language_selection(query.message, selected_name)
    await query.answer()

@router.callback_query(F.data == "custom_name")
async def custom_name_handler(query: types.CallbackQuery, state: FSMContext):
    """Handle custom name input"""
    if not query.from_user:
        return
        
    user_id = query.from_user.id
    logger.info(f"[User {user_id}] Requested custom name input")
    
    await state.set_state(OnboardingStates.waiting_for_custom_name)
    
    # Use smart edit or send utility
    await smart_edit_or_send(
        message=query,
        text="Please type and send me your preferred name:"
    )
    await query.answer()

@router.message(OnboardingStates.waiting_for_custom_name)
async def handle_custom_name_input(message: types.Message, state: FSMContext):
    """Handle custom name text input"""
    if not message.from_user or not message.text:
        return
        
    user_id = message.from_user.id
    custom_name = message.text.strip()
    
    if len(custom_name) > 50:
        await message.answer("Name is too long. Please use a shorter name (max 50 characters).")
        return
    
    if not custom_name:
        await message.answer("Please provide a valid name.")
        return
    
    logger.info(f"[User {user_id}] Entered custom name: {custom_name}")
    
    # Store the custom name in state
    await state.update_data(custom_name=custom_name)
    
    # Show language selection
    await show_language_selection(message, custom_name)

async def show_language_selection(message: types.Message, user_name: str):
    """Show language selection keyboard"""
    if not message.from_user:
        return
        
    # Use Telegram language code directly
    user_lang = message.from_user.language_code or 'en'
    
    keyboard = get_language_selection_keyboard(user_lang)
    
    await message.answer(
        f"Great {user_name}! In what language do you watch movies?",
        reply_markup=keyboard
    )

@router.callback_query(F.data.startswith("select_lang:"))
async def select_language_handler(query: types.CallbackQuery, state: FSMContext):
    """Handle language selection"""
    if not query.from_user or not query.data:
        return
        
    user_id = query.from_user.id
    selected_language = query.data.split(":", 1)[1]
    
    # Get the custom name from state
    state_data = await state.get_data()
    custom_name = state_data.get("custom_name")
    
    logger.info(f"[User {user_id}] Selected language: {selected_language}, custom_name: {custom_name}")
    
    # Update user onboarding in backend with both custom name and language
    # custom_name can be None if user didn't provide one, which is fine
    user_data = await update_user_onboarding_backend(
        telegram_id=user_id,
        custom_name=custom_name,  # This can be None, backend handles it
        preferred_language=selected_language
    )
    
    # Clear the state
    await state.clear()
    
    # Use smart edit or send utility with main menu keyboard
    keyboard = get_main_menu_keyboard()
    if user_data:
        await smart_edit_or_send(
            message=query,
            text=f"✅ Perfect! Your preferences have been saved.\n\n🎬 You're all set to start finding amazing movies!",
            reply_markup=keyboard
        )
    else:
        await smart_edit_or_send(
            message=query,
            text="❌ Sorry, there was an issue saving your preferences. You can try again later in settings.",
            reply_markup=keyboard
        )

    await query.answer()

# @router.callback_query(F.data == "other_lang")
# async def other_language_handler(query: types.CallbackQuery):
#     """Handle 'other language' selection"""
#     user_id = query.from_user.id
#     logger.info(f"[User {user_id}] Selected other language option")
#
#     keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
#         [types.InlineKeyboardButton(text="🇺🇦 Ukrainian", callback_data="select_lang:uk")],
#         [types.InlineKeyboardButton(text="🇺🇸 English", callback_data="select_lang:en")],
#         [types.InlineKeyboardButton(text="🇷🇺 Russian", callback_data="select_lang:ru")],
#         [types.InlineKeyboardButton(text="🇪🇸 Spanish", callback_data="select_lang:es")],
#         [types.InlineKeyboardButton(text="🇫🇷 French", callback_data="select_lang:fr")],
#         [types.InlineKeyboardButton(text="🇩🇪 German", callback_data="select_lang:de")]
#     ])
#
#     await query.message.edit_text(
#         "Choose your preferred language:",
#         reply_markup=keyboard
#     )
#     await query.answer()
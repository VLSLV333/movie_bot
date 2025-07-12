from aiogram import types
from bot.locales.keys import CUSTOM_NAME_BTN, LANG_ENGLISH, LANG_UKRAINIAN, LANG_RUSSIAN
from aiogram.utils.i18n import gettext

def get_name_selection_keyboard(user: types.User) -> types.InlineKeyboardMarkup:
    """Create keyboard for name selection"""
    keyboard = []
    
    # Add Telegram names if available
    if user.first_name:
        keyboard.append([types.InlineKeyboardButton(
            text=user.first_name, 
            callback_data=f"select_name:{user.first_name}"
        )])
    
    if user.last_name:
        keyboard.append([types.InlineKeyboardButton(
            text=user.last_name, 
            callback_data=f"select_name:{user.last_name}"
        )])
    
    keyboard.append([types.InlineKeyboardButton(
        text=gettext(CUSTOM_NAME_BTN), 
        callback_data="custom_name"
    )])
    
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_language_selection_keyboard(user_lang: str) -> types.InlineKeyboardMarkup:
    """Create keyboard for language selection"""
    # Map language codes to translation keys
    lang_keys = {
        "uk": LANG_UKRAINIAN,
        "en": LANG_ENGLISH, 
        "ru": LANG_RUSSIAN,
        # "es": "🇪🇸 Spanish",
        # "fr": "🇫🇷 French",
        # "de": "🇩🇪 German"
    }
    
    keyboard = []
    
    # Show user's Telegram language first if it's supported
    if user_lang in lang_keys:
        keyboard.append([types.InlineKeyboardButton(
            text=gettext(lang_keys[user_lang]),
            callback_data=f"select_lang:{user_lang}"
        )])
    else:
        keyboard.append([types.InlineKeyboardButton(
            text=gettext(lang_keys['en']),
            callback_data="select_lang:en"
        )])
    
    # Add other supported languages
    for lang_code, lang_key in lang_keys.items():
        if lang_code != user_lang:
            keyboard.append([types.InlineKeyboardButton(
                text=gettext(lang_key), 
                callback_data=f"select_lang:{lang_code}"
            )])
    
    # Add "Other" option for future expansion
    # keyboard.append([types.InlineKeyboardButton(
    #     text="🌍 Other languages",
    #     callback_data="other_lang"
    # )])
    
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard) 
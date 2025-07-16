from aiogram import types
from bot.locales.keys import (
    OPTIONS_BOT_LANGUAGE_BTN, OPTIONS_MOVIES_LANGUAGE_BTN,
    LANG_ENGLISH, LANG_UKRAINIAN, LANG_RUSSIAN
)
from aiogram.utils.i18n import gettext
from bot.helpers.back_to_main_menu_btn import add_back_to_main_menu_button

def get_options_main_keyboard() -> types.InlineKeyboardMarkup:
    """Create keyboard for main options menu"""
    keyboard = [
        [types.InlineKeyboardButton(
            text=gettext(OPTIONS_BOT_LANGUAGE_BTN),
            callback_data="options_bot_lang"
        )],
        [types.InlineKeyboardButton(
            text=gettext(OPTIONS_MOVIES_LANGUAGE_BTN),
            callback_data="options_movies_lang"
        )]
    ]
    base_keyboard = types.InlineKeyboardMarkup(inline_keyboard=keyboard)
    return add_back_to_main_menu_button(base_keyboard, source="options_main_keyboard")
    
def get_options_bot_language_keyboard() -> types.InlineKeyboardMarkup:
    """Create keyboard for bot language selection in options"""
    keyboard = [
        [types.InlineKeyboardButton(
            text=gettext(LANG_UKRAINIAN),
            callback_data="options_bot_lang_select:uk"
        )],
        [types.InlineKeyboardButton(
            text=gettext(LANG_ENGLISH),
            callback_data="options_bot_lang_select:en"
        )],
        [types.InlineKeyboardButton(
            text=gettext(LANG_RUSSIAN),
            callback_data="options_bot_lang_select:ru"
        )]
    ]
    
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_options_movies_language_keyboard() -> types.InlineKeyboardMarkup:
    """Create keyboard for movies language selection in options"""
    keyboard = [
        [types.InlineKeyboardButton(
            text=gettext(LANG_UKRAINIAN),
            callback_data="options_movies_lang_select:uk"
        )],
        [types.InlineKeyboardButton(
            text=gettext(LANG_ENGLISH),
            callback_data="options_movies_lang_select:en"
        )],
        [types.InlineKeyboardButton(
            text=gettext(LANG_RUSSIAN),
            callback_data="options_movies_lang_select:ru"
        )]
    ]
    
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard) 
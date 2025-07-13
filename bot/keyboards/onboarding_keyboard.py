from aiogram import types
from bot.locales.keys import LANG_ENGLISH, LANG_UKRAINIAN, LANG_RUSSIAN
from aiogram.utils.i18n import gettext

def get_bot_language_selection_keyboard() -> types.InlineKeyboardMarkup:
    """Create keyboard for bot interface language selection"""
    keyboard = [
        [types.InlineKeyboardButton(
            text=gettext(LANG_UKRAINIAN),
            callback_data="onboarding_bot_lang:uk"
        )],
        [types.InlineKeyboardButton(
            text=gettext(LANG_ENGLISH),
            callback_data="onboarding_bot_lang:en"
        )],
        [types.InlineKeyboardButton(
            text=gettext(LANG_RUSSIAN),
            callback_data="onboarding_bot_lang:ru"
        )]
    ]
    
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_movies_language_selection_keyboard(lang: str | None = None) -> types.InlineKeyboardMarkup:
    """Create keyboard for movies language preference selection"""
    # Language mapping for direct translation
    lang_texts = {
        'uk': {
            'ukrainian': '🇺🇦 Українська',
            'english': '🇺🇸 English',
            'russian': '🇷🇺 Русский'
        },
        'en': {
            'ukrainian': '🇺🇦 Ukrainian',
            'english': '🇺🇸 English',
            'russian': '🇷🇺 Russian'
        },
        'ru': {
            'ukrainian': '🇺🇦 Украинский',
            'english': '🇺🇸 Английский',
            'russian': '🇷🇺 Русский'
        }
    }
    
    # Default to English if no language specified
    texts = lang_texts.get(lang or 'en', lang_texts['en'])
    
    keyboard = [
        [types.InlineKeyboardButton(
            text=texts['ukrainian'],
            callback_data="onboarding_movies_lang:uk"
        )],
        [types.InlineKeyboardButton(
            text=texts['english'],
            callback_data="onboarding_movies_lang:en"
        )],
        [types.InlineKeyboardButton(
            text=texts['russian'],
            callback_data="onboarding_movies_lang:ru"
        )]
    ]
    
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard) 
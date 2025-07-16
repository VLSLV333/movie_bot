from aiogram import types
from aiogram.utils.i18n import gettext
from bot.locales.keys import DOWNLOAD_SOURCE_HDREZKA, DOWNLOAD_SOURCE_YOUTUBE
from bot.helpers.back_button import add_back_button

def get_download_source_keyboard() -> types.InlineKeyboardMarkup:
    """Create keyboard for download source selection"""
    keyboard = [
        [
            types.InlineKeyboardButton(
                text=gettext(DOWNLOAD_SOURCE_HDREZKA),
                callback_data="direct_download_source:hdrezka"
            )
        ],
        [
            types.InlineKeyboardButton(
                text=gettext(DOWNLOAD_SOURCE_YOUTUBE),
                callback_data="direct_download_source:youtube"
            )
        ]
    ]
    return add_back_button(types.InlineKeyboardMarkup(inline_keyboard=keyboard), source="main") 
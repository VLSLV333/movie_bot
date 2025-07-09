from aiogram import types
from bot.helpers.back_button import add_back_button
from aiogram_i18n import I18nContext


def get_search_type_keyboard(i18n: I18nContext) -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup(inline_keyboard = [
        [
            types.InlineKeyboardButton(text="🔤 Search by Name", callback_data="search_by_name"),
            types.InlineKeyboardButton(text="🎭 Search by Genre", callback_data="search_by_genre")
        ],
        [
            types.InlineKeyboardButton(text="🧑‍🎤 Search by Actor", callback_data="search_by_actor"),
            types.InlineKeyboardButton(text="🎬 Search by Director", callback_data="search_by_director"),
        ]
    ])

    keyboard = add_back_button(keyboard, source='main')
    return keyboard

from aiogram import types
from bot.helpers.back_button import add_back_button
from aiogram_i18n import I18nContext
from bot.locales.keys import SEARCH_BY_NAME_BTN, SEARCH_BY_GENRE_BTN, SEARCH_BY_ACTOR_BTN, SEARCH_BY_DIRECTOR_BTN


def get_search_type_keyboard(i18n: I18nContext) -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup(inline_keyboard = [
        [
            types.InlineKeyboardButton(text=i18n.get(SEARCH_BY_NAME_BTN), callback_data="search_by_name"),
            types.InlineKeyboardButton(text=i18n.get(SEARCH_BY_GENRE_BTN), callback_data="search_by_genre")
        ],
        [
            types.InlineKeyboardButton(text=i18n.get(SEARCH_BY_ACTOR_BTN), callback_data="search_by_actor"),
            types.InlineKeyboardButton(text=i18n.get(SEARCH_BY_DIRECTOR_BTN), callback_data="search_by_director"),
        ]
    ])

    keyboard = add_back_button(keyboard, source='main',i18n=i18n)
    return keyboard

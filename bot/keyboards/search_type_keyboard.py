from aiogram import types, Router, F
from bot.helpers.back_button import add_back_button
from aiogram.utils.i18n import gettext
from bot.locales.keys import SEARCH_BY_NAME_BTN, SEARCH_BY_GENRE_BTN, SEARCH_BY_ACTOR_BTN, SEARCH_BY_DIRECTOR_BTN, SEARCH_BY_ACTOR_COMING_SOON, SEARCH_BY_DIRECTOR_COMING_SOON

router = Router()

def get_search_type_keyboard() -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup(inline_keyboard = [
        [
            types.InlineKeyboardButton(text=gettext(SEARCH_BY_NAME_BTN), callback_data="search_by_name"),
            types.InlineKeyboardButton(text=gettext(SEARCH_BY_GENRE_BTN), callback_data="search_by_genre")
        ],
        [
            types.InlineKeyboardButton(text=gettext(SEARCH_BY_ACTOR_BTN), callback_data="search_by_actor"),
            types.InlineKeyboardButton(text=gettext(SEARCH_BY_DIRECTOR_BTN), callback_data="search_by_director"),
        ]
    ])

    keyboard = add_back_button(keyboard, source='main')
    return keyboard

# Temporary handlers for coming soon features
@router.callback_query(F.data == "search_by_actor")
async def search_by_actor_handler(query: types.CallbackQuery):
    await query.answer(gettext(SEARCH_BY_ACTOR_COMING_SOON), show_alert=True)

@router.callback_query(F.data == "search_by_director")
async def search_by_director_handler(query: types.CallbackQuery):
    await query.answer(gettext(SEARCH_BY_DIRECTOR_COMING_SOON), show_alert=True)

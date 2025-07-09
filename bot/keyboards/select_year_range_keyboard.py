from aiogram import types
from bot.helpers.back_button import add_back_button
from aiogram_i18n import I18nContext

def get_year_range_keyboard(i18n: I18nContext) -> types.InlineKeyboardMarkup:
    """
    Returns an inline keyboard with selectable year ranges.
    Each button leads to a specific year selection set.
    """
    ranges = [
        (2025, 2016),
        (2015, 2006),
        (2005, 1996),
        (1995, 1986),
        (1985, 1976)
    ]

    keyboard = []
    row = []

    for idx, (start, end) in enumerate(ranges):
        label = f"{start}–{end}"
        callback_data = f"select_year_range:{start}-{end}"

        row.append(types.InlineKeyboardButton(
            text=label,
            callback_data=callback_data
        ))

        # 2 buttons per row
        if (idx + 1) % 2 == 0:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    return add_back_button(types.InlineKeyboardMarkup(inline_keyboard=keyboard),source='select_genre',index=0,i18n=i18n)

from aiogram import types
from typing import List
from bot.helpers.back_button import add_back_button
from aiogram.utils.i18n import gettext
from bot.locales.keys import CONFIRM_BTN

def get_select_year_keyboard(year_list: List[int], selected_years: List[int]) -> types.InlineKeyboardMarkup:
    """
    Generate a keyboard for selecting years with dynamic range logic:
    - Selecting one-year highlights just that year
    - Selecting a second year highlights the full range between them (including both tapped years)
    - Selecting a third year (in or out of range) resets the range to that year only (basically same as selecting one year only)
    """
    keyboard = []
    row = []

    # Apply range logic
    if len(selected_years) == 1:
        highlighted_years = selected_years[:]
    elif len(selected_years) == 2:
        start, end = sorted(selected_years)
        highlighted_years = list(range(start, end + 1))
    elif len(selected_years) > 2:
        highlighted_years = [selected_years[-1]]
    else:
        highlighted_years = []

    for year in range(year_list[0], year_list[-1] - 1, -1):
        is_selected = year in highlighted_years
        display = f"✅ {year}" if is_selected else str(year)

        row.append(types.InlineKeyboardButton(
            text=display,
            callback_data=f"select_year:{year}"
        ))

        if len(row) == 3:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    # Add confirm button at the top only if at least one year is selected
    if highlighted_years:
        keyboard.append([
            types.InlineKeyboardButton(text=gettext(CONFIRM_BTN), callback_data="confirm_years")
        ])

    return add_back_button(types.InlineKeyboardMarkup(inline_keyboard=keyboard),source='year_range',index=0)
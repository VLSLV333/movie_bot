from aiogram import types
from aiogram_i18n import I18nContext
from bot.locales.keys import BACK_TO_MAIN_MENU

def get_back_to_main_menu_keyboard(i18n: I18nContext) -> types.InlineKeyboardMarkup:
    """Returns a keyboard with just the 'Back to Main Menu' button."""
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=i18n.get(BACK_TO_MAIN_MENU), callback_data="back_to_main")]
    ])


def add_back_to_main_menu_button(existing_keyboard: types.InlineKeyboardMarkup, i18n: I18nContext , source: str = "generic") -> types.InlineKeyboardMarkup:
    """
    Appends a context-aware 'Back to Main Menu' button as a new row in an existing keyboard.
    Returns a new InlineKeyboardMarkup with the extra button.
    """
    # Get the keyboard structure - handle both aiogram 2.x and 3.x
    try:
        # Try to access inline_keyboard attribute
        if hasattr(existing_keyboard, 'inline_keyboard'):
            new_keyboard = existing_keyboard.inline_keyboard.copy()
        elif hasattr(existing_keyboard, 'keyboard'):
            new_keyboard = existing_keyboard.keyboard.copy()
        else:
            # Fallback: create a new keyboard with just the back button
            return types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text=i18n.get(BACK_TO_MAIN_MENU), callback_data=f"back_to_main:{source}")]
            ])
    except Exception:
        # If we can't access the keyboard structure, create a new one
        return types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text=i18n.get(BACK_TO_MAIN_MENU), callback_data=f"back_to_main:{source}")]
        ])

    new_keyboard.append([
        types.InlineKeyboardButton(text=i18n.get(BACK_TO_MAIN_MENU), callback_data=f"back_to_main:{source}")
    ])
    return types.InlineKeyboardMarkup(inline_keyboard=new_keyboard)

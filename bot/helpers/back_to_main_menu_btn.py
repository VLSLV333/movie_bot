from aiogram import types

def get_back_to_main_menu_keyboard() -> types.InlineKeyboardMarkup:
    """Returns a keyboard with just the 'Back to Main Menu' button."""
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🏠 Back to Main Menu", callback_data="back_to_main")]
    ])


def add_back_to_main_menu_button(existing_keyboard: types.InlineKeyboardMarkup, source: str = "generic") -> types.InlineKeyboardMarkup:
    """
    Appends a context-aware 'Back to Main Menu' button as a new row in an existing keyboard.
    Returns a new InlineKeyboardMarkup with the extra button.
    """
    new_keyboard = existing_keyboard.inline_keyboard.copy()
    new_keyboard.append([
        types.InlineKeyboardButton(text="🏠 Back to Main Menu", callback_data=f"back_to_main:{source}")
    ])
    return types.InlineKeyboardMarkup(inline_keyboard=new_keyboard)

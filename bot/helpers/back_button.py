from aiogram import types

def get_back_button_keyboard(destination: str) -> types.InlineKeyboardMarkup:
    """
    Creates an inline keyboard with a single "Back" button.
    :param destination: where the back button should go (e.g., 'main', 'search', etc.)
    :return: InlineKeyboardMarkup with back button
    """
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="🔙 Back", callback_data=f"back:{destination}")]
        ]
    )

def add_back_button(keyboard: types.InlineKeyboardMarkup, source: str = "main", index: int | None = None) -> types.InlineKeyboardMarkup:
    """
    Appends a context-aware 'Back' button as a new row in an existing keyboard.
    Returns a new InlineKeyboardMarkup with the extra button.
    """
    back_button = types.InlineKeyboardButton(text="🔙 Back", callback_data=f"back:{source}")

    # Make a safe copy of all rows
    original_rows = keyboard.inline_keyboard
    copied_rows = [row.copy() for row in original_rows]  # Don't mutate the original

    # Insert at desired position or append
    if index is None:
        copied_rows.append([back_button])
    else:
        index = max(0, min(index, len(copied_rows)))
        copied_rows.insert(index, [back_button])

    return types.InlineKeyboardMarkup(inline_keyboard=copied_rows)



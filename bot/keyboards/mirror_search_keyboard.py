# File: bot/keyboards/mirror_search_keyboard.py

from aiogram import types
from bot.search.mirror_search_session import MirrorSearchSession

def get_mirror_search_keyboard(movie_index: int) -> types.InlineKeyboardMarkup:
    """
    Create a keyboard with Confirm and Wrong Language buttons.
    movie_index is needed to identify which movie user confirmed.
    """
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(
                text="✅ Confirm",
                callback_data=f"confirm_mirror_movie:{movie_index}"
            ),
            types.InlineKeyboardButton(
                text="🌐 Wrong Language",
                callback_data="wrong_language"
            )
        ]
    ])
    return keyboard


def get_mirror_navigation_keyboard(session: MirrorSearchSession) -> types.InlineKeyboardMarkup:
    """
    Create top/bottom navigation keyboard for mirror browsing.
    Hide "Previous 5" if at very beginning.
    """
    buttons = []

    show_previous = not (session.current_mirror_index == 0 and session.current_result_index <= 5)

    if show_previous:
        buttons.append(
            types.InlineKeyboardButton(
                text="⬅ Previous 5",
                callback_data="previous_mirror_result"
            )
        )

    buttons.append(
        types.InlineKeyboardButton(
            text="➡ Next 5",
            callback_data="next_mirror_result"
        )
    )

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[buttons])
    return keyboard

from aiogram import types
from bot.search.mirror_search_session import MirrorSearchSession
from typing import Tuple

def get_mirror_navigation_keyboard(session: MirrorSearchSession, position: str = "bottom",click_source: str | None = None) -> Tuple[str, types.InlineKeyboardMarkup]:
    """
    Create top/bottom navigation panel with message text and buttons.
    Adds dynamic scroll hints based on where the user clicked.
    """

    current = session.current_result_index
    total = len(session.mirrors_search_results.get(session.current_mirror_index, {}).get("results", []))
    end = min(current + 5, total)

    hint = ""

    # 🔁 Dynamic scroll hint
    if click_source == "top" and position == "top":
        hint = "👇 Scroll down to see more results"
    elif click_source == "top" and position == "bottom":
        hint = "➡️ Click ➡ Next to continue"
    elif click_source == "bottom" and position == "top":
        hint = "➡️ Click ➡ Next to continue"
    elif click_source == "bottom" and position == "bottom":
        hint = "👆 Scroll up to see more results"

    text = "🎬 Select a movie and start watching"
    if hint:
        text += f"\n{hint}"

    # ⬅ / ➡ buttons
    buttons = []
    show_previous = not (session.current_mirror_index == 0 and session.current_result_index <= 5)
    if show_previous:
        buttons.append(types.InlineKeyboardButton(text="⬅ Previous 5", callback_data="previous_mirror_result"))

    buttons.append(
        types.InlineKeyboardButton(
            text="➡ Next 5",
            callback_data="next_mirror_result"
        )
    )

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[buttons])
    return text, keyboard

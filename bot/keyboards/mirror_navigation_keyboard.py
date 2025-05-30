from aiogram import types
from bot.search.mirror_search_session import MirrorSearchSession
from typing import Tuple
from bot.utils.logger import Logger

logger = Logger().get_logger()

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
        hint = "👇 Scroll down to see all results"
    elif click_source == "top" and position == "bottom":
        hint = "Click ➡ Next to see more movies"
    elif click_source == "bottom" and position == "top":
        hint = "Click ➡ Next to see more movies"
    elif click_source == "bottom" and position == "bottom":
        hint = "👆 Scroll up to see all results"

    text = "🎬 Select a movie and start watching"
    if hint:
        text += f"\n\n{hint}"

    # ⬅ / ➡ buttons
    buttons = []
    show_previous = session.current_result_index > 0
    if show_previous:
        buttons.append(types.InlineKeyboardButton(text="⬅ Previous 5", callback_data="previous_mirror_result"))

    buttons.append(
        types.InlineKeyboardButton(
            text="➡ Next 5",
            callback_data="next_mirror_result"
        )
    )

    logger.debug(
        f"[NavPanel] Mirror: {session.current_mirror_index}, Batch: {current}-{end}, Source: {click_source}, Position: {position}")
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[buttons])
    return text, keyboard

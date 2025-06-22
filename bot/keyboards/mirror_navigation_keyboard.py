from aiogram import types
from bot.search.mirror_search_session import MirrorSearchSession
from typing import Tuple
from bot.utils.logger import Logger

logger = Logger().get_logger()

def get_mirror_navigation_keyboard(session: MirrorSearchSession, position: str = "bottom",click_source: str | None = None) -> Tuple[str, types.InlineKeyboardMarkup]:
    """
    Create top/bottom navigation panel with message text and buttons.
    """

    current = session.current_result_index
    total = len(session.mirrors_search_results.get(session.current_mirror_index, {}).get("results", []))
    end = min(current + 1, total)

    hint = f"Click ➡ Next if you don't see '{session.original_query}'"

    text = f"🎬 Select '{session.original_query}' and start watching"
    if hint:
        text += f"\n\n{hint}"

    # ⬅ / ➡ buttons
    buttons = []
    show_previous = session.current_result_index > 0
    if show_previous:
        buttons.append(types.InlineKeyboardButton(text="⬅ Previous", callback_data="previous_mirror_result"))

    buttons.append(
        types.InlineKeyboardButton(
            text="➡ Next",
            callback_data="next_mirror_result"
        )
    )

    logger.debug(
        f"[NavPanel] Mirror: {session.current_mirror_index}, Result: {current + 1}/{total}, Source: {click_source}, Position: {position}")
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[buttons])
    return text, keyboard

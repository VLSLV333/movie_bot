from aiogram import types
from typing import Tuple, Optional
from bot.config import BATCH_SIZE
from bot.search.user_search_context import UserSearchContext
from bot.utils.logger import Logger
from aiogram.utils.i18n import gettext
from bot.locales.keys import (
    SCROLL_DOWN_HINT, PRESS_NEXT_HINT, SCROLL_UP_HINT,
    EXPLORING_MOVIES_DEFAULT, SHOWING_MOVIES_RANGE,
    PREVIOUS_MOVIES_BTN, NEXT_MOVIES_BTN
)

logger = Logger().get_logger()

def render_navigation_panel(
    context: UserSearchContext,
    position: str = "bottom",  # "top" or "bottom"
    batch_size: int = BATCH_SIZE,
    click_source: Optional[str] = None) -> Tuple[str, types.InlineKeyboardMarkup]:
    """
    Build navigation panel text and buttons.
    Args:
        context: current user search context
        position: "top" or "bottom" (affects scroll hint text)
        batch_size: number of movies in batch
        click_source: top" or "bottom" (affects scroll hint text)
    Returns:
        Tuple of (text, InlineKeyboardMarkup)
    """
    # Local positions
    local_start_idx = max(context.current_result_idx - BATCH_SIZE + 1, 1)
    local_end_idx = context.current_result_idx

    # Calculate global positions
    global_start = (context.current_page - 1) * 20 + local_start_idx
    global_end = (context.current_page - 1) * 20 + local_end_idx

    total_results = context.total_results or "20+"

    # Build text hint
    if click_source == "top" and position == "top":
        scroll_hint = gettext(SCROLL_DOWN_HINT).format(batch_size=batch_size)
    elif click_source == "top" and position == "bottom":
        scroll_hint = gettext(PRESS_NEXT_HINT)
    elif click_source == "bottom" and position == "top":
        scroll_hint = gettext(PRESS_NEXT_HINT)
    elif click_source == "bottom" and position == "bottom":
        scroll_hint = gettext(SCROLL_UP_HINT).format(batch_size=batch_size)
    else:
        if position == "top":
            scroll_hint = gettext(PRESS_NEXT_HINT)
        elif position == "bottom":
            scroll_hint = gettext(SCROLL_UP_HINT).format(batch_size=batch_size)
        else:
            scroll_hint = ""

    try:
        context_line = context.strategy.get_context_text()
    except Exception as e:
        context_line = gettext(EXPLORING_MOVIES_DEFAULT)
        logger.error(f"error while getting search context text, error: {e}")

    text = gettext(SHOWING_MOVIES_RANGE).format(global_start=global_start, global_end=global_end, total_results=total_results) + "\n\n"

    if context_line:
        text += f"{context_line}\n\n"

    text += scroll_hint


    # Build navigation buttons
    buttons = []

    # "Previous" button — disable if at first batch
    if context.current_result_idx > batch_size or context.current_page != 1:
        buttons.append(types.InlineKeyboardButton(
            text=gettext(PREVIOUS_MOVIES_BTN).format(batch_size=batch_size),
            callback_data="show_previous_results"
        ))
    else:
        pass

    # "Next" button — only show if not at last result of last tmdb page
    if context.current_result_idx + 20 * (context.current_page - 1) < context.total_results:
        buttons.append(types.InlineKeyboardButton(
            text=gettext(NEXT_MOVIES_BTN).format(batch_size=batch_size),
            callback_data="show_more_results"
        ))
    else:
        pass

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[buttons])

    return text, keyboard

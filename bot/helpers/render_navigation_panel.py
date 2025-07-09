from aiogram import types
from typing import Tuple, Optional
from bot.config import BATCH_SIZE
from bot.search.user_search_context import UserSearchContext
from bot.utils.logger import Logger
from aiogram_i18n import I18nContext
from bot.locales.keys import (
    SCROLL_DOWN_HINT, PRESS_NEXT_HINT, SCROLL_UP_HINT,
    EXPLORING_MOVIES_DEFAULT, SHOWING_MOVIES_RANGE,
    PREVIOUS_MOVIES_BTN, NEXT_MOVIES_BTN
)

logger = Logger().get_logger()

def render_navigation_panel(
    context: UserSearchContext,
    i18n: I18nContext,
    position: str = "bottom",  # "top" or "bottom"
    batch_size: int = BATCH_SIZE,
    click_source: Optional[str] = None,
) -> Tuple[str, types.InlineKeyboardMarkup]:
    """
    Build navigation panel text and buttons.
    Args:
        context: current user search context
        i18n: I18n context for translation
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
        scroll_hint = i18n.get(SCROLL_DOWN_HINT).format(batch_size)
    elif click_source == "top" and position == "bottom":
        scroll_hint = i18n.get(PRESS_NEXT_HINT)
    elif click_source == "bottom" and position == "top":
        scroll_hint = i18n.get(PRESS_NEXT_HINT)
    elif click_source == "bottom" and position == "bottom":
        scroll_hint = i18n.get(SCROLL_UP_HINT, batch_size=batch_size)
    else:
        if position == "top":
            scroll_hint = i18n.get(PRESS_NEXT_HINT)
        elif position == "bottom":
            scroll_hint = i18n.get(SCROLL_UP_HINT, batch_size=batch_size)
        else:
            scroll_hint = ""

    try:
        context_line = context.strategy.get_context_text()
    except Exception as e:
        context_line = i18n.get(EXPLORING_MOVIES_DEFAULT)
        logger.error(f"error while getting search context text, error: {e}")

    text = i18n.get(SHOWING_MOVIES_RANGE, global_start=global_start, global_end=global_end, total_results=total_results) + "\n\n"

    if context_line:
        text += f"{context_line}\n\n"

    text += scroll_hint


    # Build navigation buttons
    buttons = []

    logger.info(f'\n\ncurrent_result_idx: {context.current_result_idx}')
    logger.info(f'\n\nbatch_size: {batch_size}')
    logger.info(f'\n\ncurrent page: {context.current_page}')
    logger.info(f'\n\ntotal_results: {context.total_results}')

    # "Previous" button — disable if at first batch
    if context.current_result_idx > batch_size or context.current_page != 1:
        buttons.append(types.InlineKeyboardButton(
            text=i18n.get(PREVIOUS_MOVIES_BTN, batch_size=batch_size),
            callback_data="show_previous_results"
        ))
    else:
        pass

    # "Next" button — only show if not at last result of last tmdb page
    if context.current_result_idx + 20 * (context.current_page - 1) < context.total_results:
        buttons.append(types.InlineKeyboardButton(
            text=i18n.get(NEXT_MOVIES_BTN, batch_size=batch_size),
            callback_data="show_more_results"
        ))
    else:
        pass

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[buttons])

    return text, keyboard

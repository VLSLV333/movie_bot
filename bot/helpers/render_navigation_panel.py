from aiogram import types
from typing import Tuple, Optional
from bot.config import BATCH_SIZE
from bot.search.user_search_context import UserSearchContext
from bot.search.search_strategy import SearchStrategy
from bot.utils.logger import Logger

logger = Logger().get_logger()

def render_navigation_panel(
    context: UserSearchContext,
    position: str = "bottom",  # "top" or "bottom"
    batch_size: int = BATCH_SIZE,
    click_source: Optional[str] = None
) -> Tuple[str, types.InlineKeyboardMarkup]:
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
        scroll_hint = f"👇 Scroll down to see all {batch_size} movies!"
    elif click_source == "top" and position == "bottom":
        scroll_hint = "➡️ Press 'Next' to see more movies!"
    elif click_source == "bottom" and position == "top":
        scroll_hint = "➡️ Press 'Next' to see more movies!"
    elif click_source == "bottom" and position == "bottom":
        scroll_hint = f"👆 Scroll up to see all {batch_size} movies!"
    else:
        if position == "top":
            scroll_hint = "➡️ Press 'Next' to see more movies!"
        elif position == "bottom":
            scroll_hint = f"👆 Scroll up to see all {batch_size} movies!"
        else:
            scroll_hint = ""

    try:
        context_line = context.strategy.get_context_text()
    except Exception as e:
        context_line = "🔎 You're exploring movies..."
        logger.error(f"error while getting search context text, error: {e}")

    text = f"🎬 Showing movies {global_start}–{global_end} of {total_results}\n\n"

    if context_line:
        text += f"{context_line}\n\n"

    text += scroll_hint


    # Build navigation buttons
    buttons = []

    # "Previous" button — disable if at first batch
    if global_start > batch_size:
        buttons.append(types.InlineKeyboardButton(
            text=f"⬅️ {batch_size} Previous Movies",
            callback_data="show_previous_results"
        ))
    else:
        pass

    # "Next" button — always show, later we can disable if last page is reached
    buttons.append(types.InlineKeyboardButton(
        text=f"➡️ {batch_size} Next Movies",
        callback_data="show_more_results"
    ))

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[buttons])

    return text, keyboard

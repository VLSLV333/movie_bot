import asyncio
from aiohttp import ClientSession
from aiogram.utils.i18n import gettext
from bot.handlers.main_menu_btns_handler import get_main_menu_keyboard
from bot.utils.logger import Logger
from bot.locales.keys import (
    POLL_ERROR_OCCURRED_WATCH_AGAIN,
    POLL_MOVIE_CONFIG_MISSING,
    POLL_STILL_WORKING_WAIT,
    POLL_TAKING_TOO_LONG_WATCH_AGAIN
)
logger = Logger().get_logger()


async def poll_watch_until_ready(
    user_id: int,
    task_id: str,
    status_url: str,
    loading_gif_msg,
    query,
    max_attempts: int = 150, #300 secs
    poll_interval: float = 2.0) -> dict | None:
    """
    Polls a background task status endpoint until completion or failure.

    Returns:
        dict with "config" on success, or None if error/timeout.
    """
    for attempt in range(max_attempts):
        await asyncio.sleep(poll_interval)
        logger.debug(f"[{user_id}] Polling attempt {attempt + 1}/{max_attempts} for task_id={task_id}")

        try:
            async with ClientSession() as session:
                async with session.get(f"{status_url}/{task_id}") as resp:
                    status_data = await resp.json()
                    logger.debug(f"[{user_id}] Poll response: {status_data}")
        except Exception as e:
            logger.warning(f"[{user_id}] Failed to poll status: {e}")
            continue

        # Check for error responses that contain an "error" field
        if "error" in status_data:
            error_msg = status_data.get("error", "Unknown error.")
            logger.error(f"[{user_id}] Extraction failed: {error_msg}")
            logger.debug(f"[{user_id}] Full error response: {status_data}")

            keyboard = get_main_menu_keyboard()

            await loading_gif_msg.delete()
            await query.message.answer(
                gettext(POLL_ERROR_OCCURRED_WATCH_AGAIN),
                reply_markup=keyboard)
            return None

        status = status_data.get("status")

        if status == "done":
            config = status_data.get("data")

            if not config:
                logger.warning(f"[{user_id}] Extraction done, but config is missing.")
                keyboard = get_main_menu_keyboard()
                await query.message.answer(gettext(POLL_MOVIE_CONFIG_MISSING), reply_markup=keyboard)
                return None

            logger.info(f"[{user_id}] Extraction complete.")
            return config

        elif status == "error":
            error_msg = status_data.get("error", "Unknown error.")
            logger.error(f"[{user_id}] Extraction failed: {error_msg}")

            keyboard = get_main_menu_keyboard()

            await loading_gif_msg.delete()
            await query.message.answer(
                gettext(POLL_ERROR_OCCURRED_WATCH_AGAIN),
                reply_markup=keyboard)
            return None

        elif attempt % 15 == 0 and attempt > 0:
            logger.info(f"[{user_id}] Extraction still running after {attempt * poll_interval:.0f}s")
            await query.message.answer(gettext(POLL_STILL_WORKING_WAIT))

    logger.error(f"[{user_id}] Timed out after {max_attempts * poll_interval:.0f}s – no success or failure.")
    keyboard = get_main_menu_keyboard()

    await loading_gif_msg.delete()
    await query.message.answer(
        gettext(POLL_TAKING_TOO_LONG_WATCH_AGAIN),
        reply_markup=keyboard
    )
    return None

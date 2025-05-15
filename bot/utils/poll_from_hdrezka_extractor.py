import asyncio
from aiohttp import ClientSession
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.helpers.back_button import add_back_button
from bot.utils.logger import Logger

logger = Logger().get_logger()


async def poll_task_until_ready(
    user_id: int,
    task_id: str,
    status_url: str,
    loading_gif_msg,
    query,
    max_attempts: int = 150, #300 secs
    poll_interval: float = 2.0,
) -> dict | None:
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
        except Exception as e:
            logger.warning(f"[{user_id}] Failed to poll status: {e}")
            continue

        status = status_data.get("status")

        if status == "done":
            config = status_data.get("data")

            if not config:
                logger.warning(f"[{user_id}] Extraction done, but config is missing.")
                await query.message.answer("⚠️ Movie config is missing. Try again later.")
                return None

            logger.info(f"[{user_id}] Extraction complete.")
            return config

        elif status == "error":
            error_msg = status_data.get("error", "Unknown error.")
            logger.error(f"[{user_id}] Extraction failed: {error_msg}")

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔁 Try Again", callback_data="suggest_movie")]
            ])
            add_back_button(keyboard, source="main")

            await loading_gif_msg.delete()
            await query.message.answer(
                f"⛔ An error occurred during extraction:\n\n`{error_msg}`",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            return None

        elif attempt % 15 == 0 and attempt > 0:
            logger.info(f"[{user_id}] Extraction still running after {attempt * poll_interval:.0f}s")
            await query.message.answer("⏳ Bot is still working, everything is fine, sorry you are waiting... Just a bit more!")

    logger.error(f"[{user_id}] Timed out after {max_attempts * poll_interval:.0f}s – no success or failure.")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 Try Again", callback_data="suggest_movie")]
    ])
    add_back_button(keyboard, source="main")

    await loading_gif_msg.delete()
    await query.message.answer(
        "⏳ It's taking too long. Want to try again?",
        reply_markup=keyboard
    )
    return None

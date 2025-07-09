import asyncio
from aiohttp import ClientSession
from aiogram import types
from bot.handlers.main_menu_btns_handler import get_main_menu_keyboard
from bot.utils.logger import Logger
from bot.utils.notify_admin import notify_admin
from aiogram_i18n import I18nContext
from bot.locales.keys import (
    DOWNLOAD_QUEUE_POSITION,
    DOWNLOAD_EXTRACTING_DATA,
    DOWNLOAD_CONVERTING_VIDEO,
    DOWNLOAD_UPLOADING_TO_TELEGRAM,
    DOWNLOAD_PROCESSING_STATUS,
    DOWNLOAD_FAILED_START_AGAIN,
    DOWNLOAD_TIMEOUT_TRY_LATER
)

logger = Logger().get_logger()

# Animation URLs for different statuses
STATUS_ANIMATIONS = {
    "queued": "https://media.giphy.com/media/F99PZtJC8Hxm0/giphy.gif",
    "extracting": "https://media.giphy.com/media/3oEjI6SIIHBdRxXI40/giphy.gif",
    "merging": "https://media.giphy.com/media/26ufnwz3wDUli7GU0/giphy.gif",
    "uploading": "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",
    "default": "https://media.giphy.com/media/hvRJCLFzcasrR4ia7z/giphy.gif"
}

SPINNER_FRAMES = ['|', '/', '-', '\\']

def make_progress_bar(percent, length=10):
    filled = int(percent / 100 * length)
    return "█" * filled + "-" * (length - filled)

async def poll_download_until_ready(user_id: int, i18n: I18nContext, task_id: str, status_url: str, loading_msg: types.Message,
                                    query: types.CallbackQuery, bot):
    """
    Polls the backend for download status and updates the user with animation and caption.
    If query.message is None, uses the provided bot instance to send animations.
    """
    max_attempts = 120  # 60 minutes if 30s interval
    interval = 30
    last_status = None
    last_animation_msg = loading_msg
    last_text_msg = None
    last_text = None

    async with ClientSession() as session:
        for attempt in range(max_attempts):
            try:
                async with session.get(f"{status_url}/{task_id}") as resp:
                    if resp.status != 200:
                        logger.warning(f"[User {user_id}] Polling failed (status {resp.status}) on attempt {attempt}")
                        await asyncio.sleep(interval)
                        continue

                    data = await resp.json()
                    status = data.get("status")
                    new_text = None
                    animation_url = None

                    # Determine which animation/caption to use
                    if status == "queued":
                        animation_url = STATUS_ANIMATIONS["queued"]
                        position = data.get("queue_position") or '...'
                        new_text = i18n.get(DOWNLOAD_QUEUE_POSITION).format(position)
                    elif status == "extracting":
                        animation_url = STATUS_ANIMATIONS["extracting"]
                        new_text = i18n.get(DOWNLOAD_EXTRACTING_DATA)
                    elif status == "merging":
                        animation_url = STATUS_ANIMATIONS["merging"]
                        # Fetch progress from merge_progress endpoint
                        try:
                            async with session.get(f"https://moviebot.click/hd/status/merge_progress/{task_id}") as merge_resp:
                                if merge_resp.status == 200:
                                    merge_data = await merge_resp.json()
                                    percent = int(merge_data.get("progress", 0))
                                    progress_bar = make_progress_bar(percent)
                                    new_text = i18n.get(DOWNLOAD_CONVERTING_VIDEO).format(progress_bar=progress_bar,percent=percent)
                                else:
                                    progress_bar = make_progress_bar(0)
                                    new_text = i18n.get(DOWNLOAD_CONVERTING_VIDEO).format(progress_bar=progress_bar,percent=0)
                        except Exception as e:
                            logger.error(f"[User {user_id}] Could not fetch merge progress: {e}")
                            progress_bar = make_progress_bar(0)
                            new_text = i18n.get(DOWNLOAD_CONVERTING_VIDEO).format(progress_bar=progress_bar,percent=0)
                    elif status == "uploading":
                        animation_url = STATUS_ANIMATIONS["uploading"]
                        new_text = i18n.get(DOWNLOAD_UPLOADING_TO_TELEGRAM)
                    elif status == "done":
                        result = data.get("result")
                        if result:
                            try:
                                await last_animation_msg.delete()
                            except Exception as err:
                                logger.error(f"[User {user_id}] Could not delete last animation message: {err}")
                            if last_text_msg:
                                try:
                                    await last_text_msg.delete()
                                except Exception as err:
                                    logger.error(f"[User {user_id}] Could not delete last text message: {err}")
                            return result  # contains {file_id, bot_token}
                        else:
                            logger.warning(f"[User {user_id}] status=done but no result found.")
                            break
                    elif status == "error":
                        error_text = data.get("error", "Unknown error")
                        try:
                            await last_animation_msg.delete()
                        except Exception as err:
                            logger.error(f"[User {user_id}] Could not delete last animation message: {err}")
                        if last_text_msg:
                            try:
                                await last_text_msg.delete()
                            except Exception as err:
                                logger.error(f"[User {user_id}] Could not delete last text message: {err}")

                        logger.error(f"[User {user_id}].❌ Download failed: {error_text}")
                        await query.message.answer(
                            i18n.get(DOWNLOAD_FAILED_START_AGAIN),
                            reply_markup=get_main_menu_keyboard(i18n=i18n)
                        )
                        return None
                    else:
                        animation_url = STATUS_ANIMATIONS["default"]
                        new_text = i18n.get(DOWNLOAD_PROCESSING_STATUS).format(status=status)

                    # If status changed, delete old animation and send new one, and update text message
                    if status != last_status:
                        try:
                            await last_animation_msg.delete()
                        except Exception as err:
                            logger.error(f"[User {user_id}] Could not delete last animation message: {err}")
                        if query.message is not None:
                            last_animation_msg = await query.message.answer_animation(
                                animation=animation_url,
                                caption=None
                            )
                        elif bot is not None:
                            last_animation_msg = await bot.send_animation(
                                chat_id=query.from_user.id,
                                animation=animation_url,
                                caption=None
                            )
                        else:
                            logger.error(f"[User {user_id}] Cannot send animation: both query.message and bot are None.")
                            raise RuntimeError("Cannot send animation: both query.message and bot are None.")
                        # Delete previous text message if exists
                        if last_text_msg:
                            try:
                                await last_text_msg.delete()
                            except Exception as err:
                                logger.error(f"[User {user_id}] Could not delete last text message: {err}")
                        # Send new text message
                        if query.message is not None:
                            last_text_msg = await query.message.answer(new_text)
                        elif bot is not None:
                            last_text_msg = await bot.send_message(
                                chat_id=query.from_user.id,
                                text=new_text
                            )
                        else:
                            logger.error(f"[User {user_id}] Cannot send text message: both query.message and bot are None.")
                            raise RuntimeError("Cannot send text message: both query.message and bot are None.")
                        last_status = status
                        last_text = new_text
                    # If status is merging, update text message for progress (even if status didn't change)
                    elif status == "merging" and new_text != last_text:
                        if last_text_msg:
                            try:
                                await last_text_msg.edit_text(new_text)
                            except Exception as edit_error:
                                if "message is not modified" in str(edit_error):
                                    logger.error(f"[User {user_id}] tried to edit text while merging but it was not modified")
                                else:
                                    logger.error(f"[User {user_id}] Failed to edit text: {edit_error}")
                        last_text = new_text

            except Exception as e:
                error_str = str(e)
                if "message is not modified" in error_str:
                    logger.error(f"[User {user_id}] tried to edit text while polling but it was not modified")
                    pass
                elif "query is too old" in error_str:
                    logger.warning(f"[User {user_id}] Callback query expired, continuing without query context")
                    pass
                else:
                    logger.error(f"[User {user_id}] Exception during polling: {e}")
                    await notify_admin(f"[User {user_id}] Exception during polling: {e}")

            await asyncio.sleep(interval)

    # Timed out
    try:
        await last_animation_msg.delete()
    except Exception as e:
        logger.warning(f"[User {user_id}] Could not delete loading message: {e}")
    try:
        await query.message.answer(
            i18n.get(DOWNLOAD_TIMEOUT_TRY_LATER),
            reply_markup=get_main_menu_keyboard(i18n=i18n)
        )
    except Exception as e:
        logger.error(f"[User {user_id}] Could not send timeout message: {e}")
    await notify_admin(f"[User {user_id}] Waited in queue longer than 60 min and did not get a result!")
    return None

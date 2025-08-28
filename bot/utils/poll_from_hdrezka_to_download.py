import asyncio
from aiohttp import ClientSession
from aiogram import types
from bot.handlers.main_menu_btns_handler import get_main_menu_keyboard
from bot.utils.logger import Logger
from bot.utils.notify_admin import notify_admin
from aiogram.utils.i18n import gettext
from bot.locales.keys import (
    DOWNLOAD_QUEUE_POSITION,
    DOWNLOAD_EXTRACTING_DATA,
    DOWNLOAD_CONVERTING_VIDEO,
    DOWNLOAD_UPLOADING_TO_TELEGRAM,
    DOWNLOAD_UPLOADING_PROGRESS,
    DOWNLOAD_PROCESSING_STATUS,
    DOWNLOAD_FAILED_START_AGAIN,
    DOWNLOAD_TIMEOUT_TRY_LATER
)
from bot.config import BACKEND_API_URL

logger = Logger().get_logger()

# Animation URLs for different statuses
STATUS_ANIMATIONS = {
    "queued": "https://media.giphy.com/media/99PFodlfMDhG6KxnL2/giphy.gif",
    "extracting": "https://media.giphy.com/media/8spTpadAS5THlYjUSf/giphy.gif",
    "merging": "https://media.giphy.com/media/yZz8AcxJ6NpNYHbXc9/giphy.gif",
    "uploading": "https://media.giphy.com/media/Af3gPNhmG0W0B2vchq/giphy.gif",
    "uploading_phase2": "https://media.giphy.com/media/jTNzYBEbExHjnkvCcY/giphy.gif",
    "uploading_phase3": "https://media.giphy.com/media/p8jkTJc6Nd1FAwtfkE/giphy.gif",
    "default": "https://media.giphy.com/media/RDqkrKJr5XwPWxz3pa/giphy.gif"
}

def make_progress_bar(percent, length=10):
    filled = int(percent / 100 * length)
    return "█" * filled + "-" * (length - filled)

async def poll_download_until_ready(user_id: int, task_id: str, status_url: str, loading_msg: types.Message,
                                    query: types.CallbackQuery, bot):
    """
    Polls the backend for download status and updates the user with animation and caption.
    If query.message is None, uses the provided bot instance to send animations.
    """
    max_attempts = 120  # 20 minutes if 10s interval
    interval = 10
    last_status = None
    last_animation_msg = loading_msg
    last_text_msg = None
    last_text = None
    upload_poll_count = 0  # Counter for upload progress
    last_animation_key = None  # Track last sent animation phase/key

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
                    animation_key = None

                    # Determine which animation/caption to use
                    if status == "queued":
                        animation_key = "queued"
                        animation_url = STATUS_ANIMATIONS[animation_key]
                        position = data.get("queue_position") or '...'
                        new_text = gettext(DOWNLOAD_QUEUE_POSITION).format(position=position)
                    elif status == "extracting":
                        animation_key = "extracting"
                        animation_url = STATUS_ANIMATIONS[animation_key]
                        new_text = gettext(DOWNLOAD_EXTRACTING_DATA)
                    elif status == "merging":
                        animation_key = "merging"
                        animation_url = STATUS_ANIMATIONS[animation_key]
                        # Fetch progress from merge_progress endpoint
                        try:
                            async with session.get(f"{BACKEND_API_URL}/hd/status/merge_progress/{task_id}") as merge_resp:
                                if merge_resp.status == 200:
                                    merge_data = await merge_resp.json()
                                    percent = int(merge_data.get("progress", 0))
                                    progress_bar = make_progress_bar(percent)
                                    new_text = gettext(DOWNLOAD_CONVERTING_VIDEO).format(progress_bar=progress_bar, percent=percent)
                                else:
                                    progress_bar = make_progress_bar(0)
                                    new_text = gettext(DOWNLOAD_CONVERTING_VIDEO).format(progress_bar=progress_bar, percent=0)
                        except Exception as e:
                            logger.error(f"[User {user_id}] Could not fetch merge progress: {e}")
                            progress_bar = make_progress_bar(0)
                            new_text = gettext(DOWNLOAD_CONVERTING_VIDEO).format(progress_bar=progress_bar, percent=0)
                    elif status == "uploading":
                        # Prefer real percent if backend provides it, fallback to heuristic
                        percent = data.get("upload_progress_percent")
                        try:
                            logger.info(f"[User {user_id}] Upload status payload: percent={percent}")
                        except Exception:
                            pass
                        # Be lenient: accept strings like "42"
                        if percent is not None and not isinstance(percent, int):
                            try:
                                percent = int(percent)
                            except Exception:
                                percent = None
                        if isinstance(percent, int) and 0 <= percent <= 100:
                            progress_bar = make_progress_bar(percent)
                            new_text = gettext(DOWNLOAD_UPLOADING_TO_TELEGRAM) + f"\n\n{progress_bar} {percent}%"
                        else:
                            try:
                                logger.info(f"[User {user_id}] No real percent available, falling back to heuristic pieces UI")
                            except Exception:
                                pass
                            upload_poll_count += 1
                            num_pieces = upload_poll_count * 2
                            new_text = gettext(DOWNLOAD_UPLOADING_PROGRESS).format(num=num_pieces)
                        
                        # Select animation based on poll count
                        if upload_poll_count <= 7:
                            animation_key = "uploading"
                        elif upload_poll_count <= 14:
                            animation_key = "uploading_phase2"
                        else:
                            animation_key = "uploading_phase3"
                        animation_url = STATUS_ANIMATIONS[animation_key]
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
                            gettext(DOWNLOAD_FAILED_START_AGAIN),
                            reply_markup=get_main_menu_keyboard()
                        )
                        return None
                    else:
                        animation_key = "default"
                        animation_url = STATUS_ANIMATIONS[animation_key]
                        new_text = gettext(DOWNLOAD_PROCESSING_STATUS).format(status=status)

                    # If status changed, delete old animation and send new one, and update text message
                    if status != last_status or animation_key != last_animation_key:
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
                        last_animation_key = animation_key
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
                    # If status is uploading, update text message for progress (even if status didn't change)
                    elif status == "uploading" and new_text != last_text:
                        if last_text_msg:
                            try:
                                await last_text_msg.edit_text(new_text)
                            except Exception as edit_error:
                                if "message is not modified" in str(edit_error):
                                    logger.error(f"[User {user_id}] tried to edit text while uploading but it was not modified")
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
            gettext(DOWNLOAD_TIMEOUT_TRY_LATER),
            reply_markup=get_main_menu_keyboard()
        )
    except Exception as e:
        logger.error(f"[User {user_id}] Could not send timeout message: {e}")
    await notify_admin(f"[User {user_id}] Waited in queue longer than 60 min and did not get a result!")
    return None

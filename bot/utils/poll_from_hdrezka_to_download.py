import asyncio
from aiohttp import ClientSession
from aiogram import types
from bot.handlers.main_menu_btns_handler import get_main_menu_keyboard
from bot.utils.logger import Logger
from bot.utils.notify_admin import notify_admin

logger = Logger().get_logger()


async def poll_download_until_ready(user_id: int, task_id: str, status_url: str, loading_msg: types.Message,
                                    query: types.CallbackQuery):
    max_attempts = 120  # 60 minutes if 30s interval
    interval = 30

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

                    if status == "queued":
                        position = data.get("queue_position")
                        await loading_msg.edit_caption(
                            f"⏳ Still waiting in queue...\nYour position: {position or '...'}"
                        )

                    elif status == "merging":
                        await loading_msg.edit_caption("⚙️ Download started, converting video...")

                    elif status == "uploading":
                        await loading_msg.edit_caption("Your video is ready and soon will be in telegram:)")

                    elif status == "done":
                        result = data.get("result")
                        if result:
                            return result  # contains {file_id, bot_token}
                        else:
                            logger.warning(f"[User {user_id}] status=done but no result found.")
                            break

                    elif status == "error":
                        error_text = data.get("error", "Unknown error")
                        await loading_msg.delete()
                        await query.message.answer(f"❌ Download failed: {error_text}",
                                                   reply_markup=get_main_menu_keyboard())
                        return None

                    else:
                        logger.warning(f"[User {user_id}] Unexpected status '{status}'")
                        await notify_admin(f"[User {user_id}] Unexpected status '{status}'")

            except Exception as e:
                logger.error(f"[User {user_id}] Exception during polling: {e}")
                await notify_admin(f"[User {user_id}] Exception during polling: {e}")


            await asyncio.sleep(interval)

    # Timed out
    await loading_msg.delete()
    await query.message.answer("⚠️ Sorry, this is taking too long. Please try again later.",
                               reply_markup=get_main_menu_keyboard())
    await notify_admin(f"[User {user_id}] Waited in queue longer then 60 min and did not get a result!")
    return None

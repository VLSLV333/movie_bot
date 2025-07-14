import aiohttp
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("delivery_bot")

async def clean_up_expired_file_id(telegram_file_id: str):
    """
    Call the backend API to clean up expired Telegram file ID
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://moviebot.click/cleanup-expired-file",
                json={"telegram_file_id": telegram_file_id}
            ) as resp:
                if resp.status == 200:
                    cleanup_result = await resp.json()
                    logger.info(f"Successfully cleaned up expired file ID {telegram_file_id}: {cleanup_result}")
                    return cleanup_result
                else:
                    logger.error(f"Failed to cleanup expired file ID {telegram_file_id}, status: {resp.status}")
                    return None
    except Exception as e:
        logger.error(f"Exception while cleaning up expired file ID {telegram_file_id}: {e}")
        return None
import os
import logging
import aiohttp
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()

ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
PING_BOT_TOKEN = os.getenv("PING_BOT_TOKEN")

async def notify_admin(message: str):

    if not PING_BOT_TOKEN:
        logger.warning("⚠️ Cannot notify admin: MAIN_BOT_TOKEN not set")
        return

    notify_url = f"https://api.telegram.org/bot{PING_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": ADMIN_CHAT_ID,
        "text": message
    }

    try:
        async with aiohttp.ClientSession() as session:
            await session.post(notify_url, json=payload)
    except Exception as e:
        logger.warning(f"⚠️ Failed to notify admin: {e}")

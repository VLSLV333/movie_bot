import os
import json
import logging
import hmac
import hashlib
import aiohttp
from urllib.parse import quote
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from redis.asyncio import Redis
from dotenv import load_dotenv
from aiogram.client.default import DefaultBotProperties

load_dotenv()

ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
PING_BOT_TOKEN = os.getenv("PING_BOT_TOKEN")
BOT_TOKEN = os.getenv("DELIVERY_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("DELIVERY_BOT_TOKEN environment variable is not set!")
TASK_ID_SECRET = os.getenv("BACKEND_DOWNLOAD_SECRET")

redis_host = os.getenv("REDIS_HOST", "localhost")
redis_port = int(os.getenv("REDIS_PORT", 6379))
REDIS_URL = f"redis://{redis_host}:{redis_port}"
redis = Redis.from_url(REDIS_URL, decode_responses=True)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("delivery_bot")

async def notify_admin(message: str):
    if not PING_BOT_TOKEN:
        logger.warning("⚠️ Cannot notify admin: PING_BOT_TOKEN not set")
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


def verify_task_id(signed: str, secret: str) -> str | None:
    try:
        task_id, sig = signed.split(":")
        expected_sig = hmac.new(secret.encode(), task_id.encode(), hashlib.sha256).hexdigest()[:10]
        return task_id if sig == expected_sig else None
    except Exception:
        return None

@dp.message()
async def catch_all(message: Message):
    logger.info(f"CATCH-ALL: Received message: {message.text} from user {getattr(message.from_user, 'id', None)}")
    await message.answer("I received your message, but it didn't match any command.")

# === Handlers ===
@dp.message(CommandStart(deep_link=True))
async def handle_start(message: Message):
    try:
        logger.info(f"Received /start from user_id={getattr(message.from_user, 'id', None)}, text='{getattr(message, 'text', None)}', args='{getattr(message, 'get_args', lambda: None)()}'")
        user_id = getattr(message.from_user, 'id', None)
        if user_id is None:
            logger.error("Message has no from_user.id!")
            await message.answer("❌ Internal error: no user ID found.")
            return

        args = getattr(message, 'get_args', lambda: None)()
        logger.info(f"/start args: {args}")
        if not args or "_" not in args:
            await message.answer("❌ Malformed or missing start link.")
            logger.error(f"❌ Malformed or missing start link for user {user_id}, args: {args}")
            return

        flow_type, signed_payload = args.split("_", 1)
        logger.info(f"Parsed flow_type={flow_type}, signed_payload={signed_payload} for user {user_id}")

        if flow_type == "1":
            if not TASK_ID_SECRET:
                logger.error("TASK_ID_SECRET is not set!")
                await message.answer("❌ Internal error: missing secret. Pls start download from beginning:(")
                return
            task_id = verify_task_id(signed_payload, TASK_ID_SECRET)
            logger.info(f"Verified task_id={task_id} for user {user_id}")
            if not task_id:
                logger.warning(f"Invalid signature: user {user_id} sent {signed_payload}")
                await message.answer("❌ Invalid or malformed download link. Pls start download from beginning:(")
                return

            redis_key_user = f"download:{task_id}:user_id"
            stored_user_id = await redis.get(redis_key_user)
            logger.info(f"Redis user for task_id={task_id}: {stored_user_id}")

            if not stored_user_id:
                await message.answer("⚠️ This download link has expired or is no longer available. Pls start download from beginning:(")
                logger.warning(f"No stored user for task_id={task_id}")
                return

            if str(user_id) != stored_user_id:
                logger.warning(f"❗ Tampering: user {user_id} tried task {task_id} belonging to {stored_user_id}")
                await notify_admin(
                    f"❗ Tampering in delivery bot: user {user_id} tried task {task_id} belonging to {stored_user_id}")
                await redis.incr(f"tamper:{user_id}")
                await message.answer("🚫 This download link was not created for your account.")
                return

            redis_key_result = f"download:{task_id}:result"
            result_json = await redis.get(redis_key_result)
            ttl = await redis.ttl(f"download:{task_id}:result")
            logger.info(f"Result for task_id={task_id}: {result_json}, TTL={ttl}")

            if ttl > 0:
                ttl_minutes = ttl // 60
                logger.info(f"User {user_id}, download session is valid for {ttl_minutes} min.")
            elif ttl == -2:
                await message.answer("⚠️ This download has expired. Pls start download from beginning:(")
                logger.info(f"User {user_id}, download session expired.")
                await notify_admin(f"User {user_id}, download session expired.")
                return

            if not result_json:
                await message.answer("⚠️ The video is not ready yet or the link expired. Pls start download from beginning:(")
                logger.warning(f"No result found for task_id={task_id}")
                return

            try:
                result = json.loads(result_json)
                logger.info(f"Parsed result for user {user_id}: {result}")

                if "telegram_file_id" in result:
                    await message.answer("📦 Here is your video! Enjoy 🎬")
                    await bot.send_video(chat_id=user_id, video=result["telegram_file_id"])
                elif "db_id_to_get_parts" in result:
                    db_id = result["db_id_to_get_parts"]
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                                f"https://moviebot.click/all_movie_parts_by_id?db_id={db_id}") as resp:
                            if resp.status != 200:
                                logger.error(f"Failed to retrieve multipart file info from backend, status={resp.status}")
                                raise Exception("Failed to retrieve multipart file info from backend")
                            data = await resp.json()
                    parts = data.get("parts", [])
                    logger.info(f"Sending {len(parts)} parts to user {user_id}")
                    for part in parts:
                        await bot.send_video(chat_id=user_id, video=part["telegram_file_id"])
                    await message.answer("📦Video is too long to fit into TG, so was divided into parts🎬")
                else:
                    logger.error(f"Invalid result format for user {user_id}: {result}")
                    raise ValueError("Invalid result format")

                await notify_admin(f"Tg user:{user_id} just received his video for download!")

            except Exception as e:
                logger.error(f"❌ Failed to deliver file for task {task_id} to user {user_id}", exc_info=e)
                await message.answer("❌ An error occurred while delivering your video. Please try again later.")
                await notify_admin(
                    f"❌ An error occurred while delivering your video. Please try again later. task_id:{task_id} tg_user_id:{user_id}")

        elif flow_type == "2":
            if not TASK_ID_SECRET:
                logger.error("TASK_ID_SECRET is not set!")
                await message.answer("❌ Internal error: missing secret. Pls start download from beginning:(")
                return
            try:
                watch_token, sig = signed_payload.split("_")
                expected_sig = hmac.new(TASK_ID_SECRET.encode(), watch_token.encode(), hashlib.sha256).hexdigest()[:10]
            except Exception as e:
                logger.error(f"Malformed watch token or signature for user {user_id}: {signed_payload}", exc_info=e)
                await message.answer("❌ Malformed watch link. Pls start download from beginning:(")
                return

            if sig != expected_sig:
                await message.answer("❌ Invalid or tampered watch link.")
                logger.error(f"❌ User {user_id}, tried to use wrong signature, he used this sig:{sig} expected was {expected_sig}. Watch token he passed was: {watch_token}")
                return

            redis_key = f"downloaded_dub_info:{watch_token}"
            ttl = await redis.ttl(redis_key)
            info_json = await redis.get(redis_key)

            if not info_json:
                await message.answer("⚠️ Watch session expired. Please try again from the main bot.")
                logger.info(f"❌ User's {user_id},watch session expired.")
                return

            if ttl > 0:
                ttl_minutes = ttl // 60
                logger.info(f"User {user_id}, watch session is valid for {ttl_minutes} min.")
            elif ttl == -2:
                await message.answer("⚠️ This link has already expired.")
                logger.info(f"❌ User's {user_id},watch session expired.")
                await notify_admin(f"❌ Watch session expired. Pls start download from beginning:(")
                return

            try:
                info = json.loads(info_json)
                logger.info(f"Parsed watch info for user {user_id}: {info}")
                if str(info.get("tg_user_id")) != str(user_id):
                    await notify_admin(
                        f"❗ Tampering: user {user_id} tried to watch token {watch_token} belonging to {info.get('tg_user_id')}")
                    await message.answer("🚫 This link was not created for your account.")
                    return

                tmdb_id, lang, dub = info.get("tmdb_id"), info.get("lang"), info.get("dub")
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                            f"https://moviebot.click/all_movie_parts?tmdb_id={tmdb_id}&lang={lang}&dub={quote(dub)}"
                    ) as resp:
                        if resp.status != 200:
                            logger.error(f"Failed to fetch movie parts for user {user_id}, status={resp.status}")
                            raise Exception("Failed to fetch movie parts")
                        data = await resp.json()
                parts = data.get("parts", [])
                logger.info(f"Sending {len(parts)} parts to user {user_id}")
                for part in parts:
                    await bot.send_video(chat_id=user_id, video=part["telegram_file_id"])
                await message.answer("🎬 Enjoy your content!")

            except Exception as e:
                logger.error(f"Failed to handle watch_downloaded flow for user {user_id}: {e}", exc_info=e)
                await message.answer("❌ Failed to load your content. Please try again later.")

        else:
            logger.error(f"Unknown flow_type '{flow_type}' for user {user_id}")
            await message.answer("❌ Unknown start link type.")

    except Exception as e:
        logger.error(f"Exception in handle_start for user {getattr(message.from_user, 'id', None)}: {e}", exc_info=e)
        await message.answer("❌ Internal error in delivery bot. Please try again later.")


# === Run the bot ===
if __name__ == "__main__":
    import asyncio
    asyncio.run(dp.start_polling(bot))

import asyncio
import json
import logging
from typing import Optional
from backend.video_redirector.utils.redis_client import RedisClient
from backend.video_redirector.hdrezka.hdrezka_download_executor import handle_download_task
from backend.video_redirector.exceptions import RetryableDownloadError
from backend.video_redirector.config import MAX_CONCURRENT_DOWNLOADS, MAX_RETRIES_FOR_DOWNLOAD

logger = logging.getLogger(__name__)

QUEUE_KEY = "download_queue"
ACTIVE_COUNT_KEY = "active_downloads"

class DownloadQueueManager:

    @staticmethod
    async def enqueue(task: dict) -> int:
        redis = RedisClient.get_client()
        await redis.rpush(QUEUE_KEY, json.dumps(task))
        length = await redis.llen(QUEUE_KEY)
        return length

    @staticmethod
    async def queue_worker():
        redis = RedisClient.get_client()
        logger.info("📡 Queue worker started and monitoring for downloads...")

        log_interval = 300  # seconds (5 min)
        last_log_time = asyncio.get_event_loop().time()

        while True:
            now = asyncio.get_event_loop().time()
            if now - last_log_time >= log_interval:
                queue_length = await redis.llen(QUEUE_KEY)
                active = int(await redis.get(ACTIVE_COUNT_KEY) or 0)
                logger.info(f"📊 Queue status — Queue length: {queue_length}, Active downloads: {active}")
                last_log_time = now

            active = int(await redis.get(ACTIVE_COUNT_KEY) or 0)
            if active >= MAX_CONCURRENT_DOWNLOADS:
                await asyncio.sleep(5)
                continue

            task_data = await redis.lpop(QUEUE_KEY)
            if not task_data:
                await asyncio.sleep(3)
                continue

            task = json.loads(task_data)
            task_id = task["task_id"]

            try:
                await redis.incr(ACTIVE_COUNT_KEY)
                logger.info(f"🎬 Starting queued download: {task_id}")
                asyncio.create_task(
                    DownloadQueueManager.wrap_download(task)
                )
            except Exception as e:
                logger.error(f"❌ Failed to start task {task_id}: {e}")
                await redis.decr(ACTIVE_COUNT_KEY)

    @staticmethod
    async def wrap_download(task: dict):
        redis = RedisClient.get_client()
        task_id = task["task_id"]

        try:
            # Convert tmdb_id to integer with error handling
            try:
                tmdb_id = int(task["tmdb_id"])
            except (ValueError, TypeError) as e:
                logger.error(f"❌ Invalid tmdb_id '{task['tmdb_id']}' for task {task_id}: {e}")
                await redis.set(f"download:{task_id}:status", "error", ex=3600)
                await redis.set(f"download:{task_id}:error", f"Invalid tmdb_id: {task['tmdb_id']}", ex=3600)
                return

            await handle_download_task(
                task_id=task["task_id"],
                movie_url=task["movie_url"],
                tmdb_id=tmdb_id,
                lang=task["lang"],
                dub=task["dub"],
                movie_title=task.get("movie_title"),
                movie_poster=task.get("movie_poster")
            )
        except RetryableDownloadError as e:
            retries = int(await redis.get(f"download:{task_id}:retries") or 0)
            await redis.set(f"download:{task_id}:status", "error", ex=3600)
            await redis.set(f"download:{task_id}:error", str(e), ex=3600)
            if retries < MAX_RETRIES_FOR_DOWNLOAD:
                await asyncio.sleep(10)
                logger.warning(f"🔁 Retrying task {task_id} due to retryable error: {e}")
                await redis.set(f"download:{task_id}:retries", retries + 1, ex=3600)
                await redis.rpush(QUEUE_KEY, json.dumps(task))
            else:
                logger.error(f"❌ Final retry failed for task {task_id}: {e}")
        except Exception as e:
            # Non-retryable error — just log it
            await redis.set(f"download:{task_id}:status", "error", ex=3600)
            await redis.set(f"download:{task_id}:error", str(e), ex=3600)
            logger.error(f"❌ Non-retryable error in task {task_id}: {e}")
        finally:
            await redis.delete(f"download:{task_id}:retries")
            await redis.decr(ACTIVE_COUNT_KEY)

    @staticmethod
    async def get_position_by_task_id(task_id: str) -> Optional[int]:
        redis = RedisClient.get_client()
        queue = await redis.lrange(QUEUE_KEY, 0, -1)
        for i, item in enumerate(queue):
            try:
                task = json.loads(item)
                if task.get("task_id") == task_id:
                    return i + 1
            except Exception as e:
                logger.error(f"Error occurred while getting users queue position: {e}")
        return None
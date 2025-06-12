import asyncio
from backend.video_redirector.utils.download_queue_manager import DownloadQueueManager

async def start_background_workers():
    asyncio.create_task(DownloadQueueManager.queue_worker())

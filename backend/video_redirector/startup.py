import asyncio
from backend.video_redirector.utils.download_queue_manager import DownloadQueueManager
from backend.video_redirector.utils.pyrogram_acc_manager import idle_client_cleanup, initialize_proxy_on_startup

async def start_background_workers():
    await initialize_proxy_on_startup()
    asyncio.create_task(DownloadQueueManager.queue_worker())
    asyncio.create_task(idle_client_cleanup())

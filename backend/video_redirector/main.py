import logging
logging.getLogger("pyrogram").setLevel(logging.INFO)
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from backend.video_redirector.startup import start_background_workers
from backend.video_redirector.hdrezka import router as hdrezka_router
from backend.video_redirector.utils.redis_client import RedisClient
from backend.video_redirector.routes.mirror_search_route import  router as mirror_search_route
from backend.video_redirector.routes.tg_id_movies import router as tg_id_route
from backend.video_redirector.routes.user_routes import router as user_routes
from backend.video_redirector.routes.youtube_routes import router as youtube_routes
from backend.video_redirector.utils.pyrogram_acc_manager import UPLOAD_ACCOUNT_POOL

if not logging.getLogger().hasHandlers():
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"
    )

logger = logging.getLogger(__name__)

session_path = "/app/backend/session_files"
if not os.path.exists(session_path):
    logger.critical(f"❗️ Pyrogram session_files NOT FOUND! Expected at: {session_path}")
    logger.critical("🛑 Upload to Telegram with user account will FAIL. Stopping application startup.")
    raise SystemExit(f"❌ Startup aborted: Required .session file is missing → {session_path}")
else:
    logger.info("✅ Pyrogram session file found. Upload is enabled.")

@asynccontextmanager
async def lifespan(app_as: FastAPI):
    await RedisClient.init()
    await start_background_workers()
    yield
    await RedisClient.close()
    for account in UPLOAD_ACCOUNT_POOL:
        await account.stop_client()

app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory="video_redirector/static"), name="static")
app.include_router(hdrezka_router)
app.include_router(mirror_search_route)
app.include_router(tg_id_route)
app.include_router(user_routes)
app.include_router(youtube_routes)

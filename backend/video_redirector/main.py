from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import logging

from backend.video_redirector.startup import start_background_workers

from backend.video_redirector.hdrezka import router as hdrezka_router
from backend.video_redirector.utils.redis_client import RedisClient
from backend.video_redirector.routes.mirror_search_route import  router as mirror_search_route
from backend.video_redirector.routes.tg_id_movies import router as tg_id_route

app = FastAPI()

if not logging.getLogger().hasHandlers():
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"
    )

app.mount("/static", StaticFiles(directory="video_redirector/static"), name="static")

#TODO: CHANGE DEPRECATED METHODS
@app.on_event("startup")
async def startup_redis():
    await RedisClient.init()
    await start_background_workers()

@app.on_event("shutdown")
async def shutdown_redis():
    await RedisClient.close()

app.include_router(hdrezka_router)
app.include_router(mirror_search_route)
app.include_router(tg_id_route)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from backend.video_redirector.hdrezka import router as hdrezka_router
from backend.video_redirector.utils.redis_client import RedisClient
from backend.video_redirector.routes.mirror_search_route import  router as mirror_search_route

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

#TODO: CHANGE DEPRECATED METHODS
@app.on_event("startup")
async def startup_redis():
    await RedisClient.init()

@app.on_event("shutdown")
async def shutdown_redis():
    await RedisClient.close()

app.include_router(hdrezka_router)
app.include_router(mirror_search_route)

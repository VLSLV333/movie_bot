from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.video_redirector.hdrezka import router as hdrezka_router
from backend.video_redirector.utils.redis_client import RedisClient
from backend.video_redirector.routes.mirror_search_route import  router as mirror_search_route

app = FastAPI()

app.mount("/static", StaticFiles(directory="video_redirector/static"), name="static")

#TODO: CHANGE DEPRECATED METHODS
@app.on_event("startup")
async def startup_redis():
    await RedisClient.init()

@app.on_event("shutdown")
async def shutdown_redis():
    await RedisClient.close()

app.include_router(hdrezka_router)
app.include_router(mirror_search_route)

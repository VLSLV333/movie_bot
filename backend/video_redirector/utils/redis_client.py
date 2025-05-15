import redis.asyncio as redis
import os
from backend.video_redirector.config import REDIS_HOST,REDIS_PORT

class RedisClient:
    _client = None

    @classmethod
    async def init(cls):
        if cls._client is None:
            cls._client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                decode_responses=True
            )

    @classmethod
    def get_client(cls):
        if cls._client is None:
            raise ValueError("Redis client not initialized!")
        return cls._client

    @classmethod
    async def close(cls):
        if cls._client:
            await cls._client.close()
            cls._client = None

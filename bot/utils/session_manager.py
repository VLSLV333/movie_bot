from bot.utils.redis_client import RedisClient
import json
from bot.config import SESSION_EXPIRATION_SECONDS, STATE_EXPIRATION_SECONDS
from bot.search.user_search_context import UserSearchContext
from bot.utils.logger import Logger


logger = Logger().get_logger()

class SessionManager:
    @staticmethod
    async def save_context(
            user_id: int,
            context: UserSearchContext,
            current_cards_message_ids: list = None,
            pagination_message_id: int = None,
            top_pagination_message_id: int = None,
    ):
        client = RedisClient.get_client()

        session_data = context.to_dict()
        session_data.update({
            "current_cards_message_ids": current_cards_message_ids or [],
            "pagination_message_id": pagination_message_id,
            "top_pagination_message_id": top_pagination_message_id
        })

        await client.set(f"user_session:{user_id}", json.dumps(session_data), ex=SESSION_EXPIRATION_SECONDS)  # Expires in 1 hour
        strategy_name = context.strategy.get_search_id() if context.strategy else "Unknown"
        logger.info(f"[User {user_id}] Session saved to Redis with strategy: {strategy_name}.")

    @staticmethod
    async def get_user_session(user_id: int):
        client = RedisClient.get_client()
        session_data = await client.get(f"user_session:{user_id}")
        if session_data:
            try:
                data = json.loads(session_data)
                if not isinstance(data, dict):
                    raise ValueError("Invalid session format")
                logger.info(f"[User {user_id}] Session loaded from Redis. Strategy: {data.get('strategy', {}).get('type')}")
                return data
            except Exception as e:
                logger.error(f"[User {user_id}] Failed to parse session: {e}")
                return None

        logger.info(f"[User {user_id}] Tried to load session but none found.")
        return None

    @staticmethod
    async def clear_user_session(user_id: int):
        client = RedisClient.get_client()
        await client.delete(f"user_session:{user_id}")
        logger.info(f"[User {user_id}] Session cleared from Redis.")

    @staticmethod
    async def set_state(user_id: int, state: str):
        client = RedisClient.get_client()
        await client.set(f"user_state:{user_id}", state, ex=STATE_EXPIRATION_SECONDS)
        logger.debug(f"[User {user_id}] State set in Redis: '{state}' with expiry {STATE_EXPIRATION_SECONDS}s")

    @staticmethod
    async def get_state(user_id: int) -> str | None:
        client = RedisClient.get_client()
        state = await client.get(f"user_state:{user_id}")
        if not state:
            logger.debug(f"[User {user_id}] No state found in Redis")
            return None
        decoded_state = state.decode() if isinstance(state, bytes) else state
        logger.debug(f"[User {user_id}] State retrieved from Redis: '{decoded_state}' (type: {type(state)})")
        return decoded_state

    @staticmethod
    async def clear_state(user_id: int):
        client = RedisClient.get_client()
        await client.delete(f"user_state:{user_id}")

    @staticmethod
    async def update_data(user_id: int, new_data: dict):
        """
        Merges new data into existing user_data:{user_id} without overwriting previous keys.
        """
        existing = await SessionManager.get_data(user_id)
        updated = {**existing, **new_data}

        client = RedisClient.get_client()
        await client.set(f"user_data:{user_id}", json.dumps(updated), ex=SESSION_EXPIRATION_SECONDS)
        logger.info(f"[User {user_id}] Custom session data updated in Redis.")

    @staticmethod
    async def get_data(user_id: int) -> dict:
        client = RedisClient.get_client()
        raw = await client.get(f"user_data:{user_id}")
        if raw:
            try:
                return json.loads(raw)
            except Exception as e:
                logger.error(f"[User {user_id}] Failed to parse custom session data: {e}")
                return {}
        return {}

    @staticmethod
    async def clear_data(user_id: int):
        client = RedisClient.get_client()
        await client.delete(f"user_data:{user_id}")
        logger.info(f"[User {user_id}] Custom session data cleared.")

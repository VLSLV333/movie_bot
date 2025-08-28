import uuid
from typing import Callable, Dict, Any, Awaitable, Optional

from aiogram import BaseMiddleware
from aiogram.types import Update
from bot.utils.redis_client import RedisClient
from common.analytics.analytics import Analytics


analytics = Analytics("movieBot")


def _extract_user_id(update: Update) -> Optional[int]:
    if getattr(update, "message", None) and update.message.from_user:
        return update.message.from_user.id
    if getattr(update, "callback_query", None) and update.callback_query.from_user:
        return update.callback_query.from_user.id
    if getattr(update, "inline_query", None) and update.inline_query.from_user:
        return update.inline_query.from_user.id
    if getattr(update, "my_chat_member", None) and update.my_chat_member.from_user:
        return update.my_chat_member.from_user.id
    return None


class JourneyMiddleware(BaseMiddleware):
    def __init__(self, ttl_s: int = 24 * 3600):
        super().__init__()
        self.ttl_s = ttl_s

    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any],
    ) -> Any:
        user_id = _extract_user_id(event)
        journey_id: Optional[str] = None
        try:
            if user_id:
                r = RedisClient.get_client()
                key = f"journey:{user_id}"
                journey_id = await r.get(key)
                if not journey_id:
                    journey_id = str(uuid.uuid4())
                    await r.setex(key, self.ttl_s, journey_id)
                data["journey_id"] = journey_id
        except Exception:
            pass

        # Important events mapping
        try:
            if getattr(event, "message", None):
                text = getattr(event.message, "text", None)
                if text and text.startswith("/start"):
                    await analytics.log_event(user_id, journey_id, "bot_start", {"text": text})
                elif text:
                    await analytics.log_event(user_id, journey_id, "input", {"text": text[:128], "len": len(text)})
                else:
                    await analytics.log_event(user_id, journey_id, "input", {"kind": "non-text"})
            elif getattr(event, "callback_query", None):
                data_payload = getattr(event.callback_query, "data", None)
                await analytics.log_event(user_id, journey_id, "btn_clicked", {"data": (data_payload or "")[:128]})
            else:
                await analytics.log_event(user_id, journey_id, "update", {})
        except Exception:
            pass

        return await handler(event, data)



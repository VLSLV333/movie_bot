from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Update

from bot.middleware.state import graspil_forwarder


class GraspilMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any],
    ) -> Any:
        try:
            # Use Telegram field aliases (e.g., "from" instead of "from_user")
            update_dict = event.model_dump(exclude_none=True, by_alias=True)
            await graspil_forwarder.enqueue_update(update_dict)
        except Exception:
            # analytics must never block bot
            pass
        return await handler(event, data)



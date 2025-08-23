from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Update

from bot.middleware.state import graspil_forwarder
from bot.utils.logger import Logger


logger = Logger().get_logger()

# Log a few diagnostic samples to compare raw vs aliased structures
_GRASPIL_DIAG_SAMPLES = 10


class GraspilMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any],
    ) -> Any:
        try:
            global _GRASPIL_DIAG_SAMPLES
            # Raw (no alias) vs aliased (Telegram-compatible) structures
            raw_update = event.model_dump(exclude_none=True)
            aliased_update = event.model_dump(exclude_none=True, by_alias=True)

            if _GRASPIL_DIAG_SAMPLES > 0:
                update_id = aliased_update.get("update_id")
                raw_msg = raw_update.get("message") or {}
                aliased_msg = aliased_update.get("message") or {}
                logger.info(
                    f"Graspil diag: update_id={update_id}, has_raw_from_user={'from_user' in raw_msg}, has_aliased_from={'from' in aliased_msg}"
                )
                _GRASPIL_DIAG_SAMPLES -= 1

            await graspil_forwarder.enqueue_update(aliased_update)
        except Exception:
            # analytics must never block bot
            pass
        return await handler(event, data)



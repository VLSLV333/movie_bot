import os
import asyncio
import datetime as dt
from enum import Enum
from typing import Any, Dict, List, Optional

import aiohttp

from bot.utils.logger import Logger


# Sentinel for dropping fields not serializable/unsupported
class _Drop:  # simple identity marker
    pass


_DROP = _Drop()


logger = Logger().get_logger()

GRASPIL_API_KEY = os.getenv("GRASPIL_API_KEY", "")
GRASPIL_ENABLED_ENV = os.getenv("GRASPIL_ENABLED", "false").lower() in ("1", "true", "yes", "y")

GRASPIL_BATCH_URL = "https://api.graspil.com/v1/send-batch-update"
GRASPIL_SINGLE_URL = "https://api.graspil.com/v1/send-update"


class GraspilForwarder:
    def __init__(
        self,
        batch_window_s: float = 60.0,
        max_batch: int = 800,
        max_queue: int = 5000,
        heartbeat_interval_s: float = 3600.0,
    ) -> None:
        self.batch_window_s = batch_window_s
        self.max_batch = max_batch
        self.heartbeat_interval_s = heartbeat_interval_s

        self.queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=max_queue)

        self._task_flusher: Optional[asyncio.Task] = None
        self._task_heartbeat: Optional[asyncio.Task] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._stop = asyncio.Event()

        # Enable only when both flag and API key present
        self._enabled = bool(GRASPIL_API_KEY) and GRASPIL_ENABLED_ENV

        # telemetry
        self._dropped_count = 0
        self._sent_count = 0
        self._failed_flushes = 0

    async def start(self) -> None:
        if not self._enabled:
            logger.info("Graspil forwarder disabled (flag off or API key missing)")
            return
        headers = {
            "Api-Key": GRASPIL_API_KEY,
            "Content-Type": "application/json",
        }
        self._session = aiohttp.ClientSession(headers=headers)
        self._stop.clear()
        self._task_flusher = asyncio.create_task(self._flusher(), name="graspil_flusher")
        self._task_heartbeat = asyncio.create_task(self._heartbeat(), name="graspil_heartbeat")
        logger.info(
            f"Graspil forwarder started (batch_window_s={self.batch_window_s}, max_batch={self.max_batch})"
        )

    async def stop(self) -> None:
        if not self._enabled:
            return
        self._stop.set()
        # Wait tasks
        tasks: List[asyncio.Task] = []
        if self._task_flusher:
            tasks.append(self._task_flusher)
        if self._task_heartbeat:
            tasks.append(self._task_heartbeat)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        # Close session
        if self._session is not None:
            await self._session.close()
            self._session = None
        logger.info(
            f"Graspil forwarder stopped (sent={self._sent_count}, dropped={self._dropped_count}, failed_flushes={self._failed_flushes})"
        )

    @staticmethod
    def _now_iso_ms() -> str:
        # Always use UTC, include ms and timezone per Graspil docs
        return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")

    @staticmethod
    def _to_unix_seconds(value: dt.datetime) -> int:
        # Convert datetime to Unix seconds (int). Assume UTC if naive.
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return int(value.timestamp())

    def _sanitize_update(self, obj: Any) -> Any:
        # Recursively ensure JSON-serializable, Telegram-compatible primitives
        # - Drop aiogram Default sentinels
        # - Convert datetime -> unix seconds
        # - Convert Enum -> value
        # - Tuples/Sets -> lists
        # - Fallback to str for unknown types
        # Dict
        if isinstance(obj, dict):
            result: Dict[str, Any] = {}
            for k, v in obj.items():
                sanitized = self._sanitize_update(v)
                if sanitized is _DROP:
                    continue
                result[k] = sanitized
            return result
        # List/Tuple/Set
        if isinstance(obj, (list, tuple, set)):
            out_list: List[Any] = []
            for v in obj:
                sanitized = self._sanitize_update(v)
                if sanitized is _DROP:
                    continue
                out_list.append(sanitized)
            return out_list
        # Datetime
        if isinstance(obj, dt.datetime):
            return self._to_unix_seconds(obj)
        # Enum
        if isinstance(obj, Enum):
            return obj.value
        # aiogram Default sentinel (avoid importing the class; match by name)
        if obj.__class__.__name__ == "Default":
            return _DROP
        # Primitives
        if obj is None or isinstance(obj, (str, int, float, bool)):
            return obj
        # Fallback: stringify
        return str(obj)

    async def enqueue_update(self, update_dict: Dict[str, Any]) -> None:
        if not self._enabled:
            return
        normalized_update = self._sanitize_update(update_dict)
        item = {"date": self._now_iso_ms(), "update": normalized_update}
        try:
            self.queue.put_nowait(item)
        except asyncio.QueueFull:
            self._dropped_count += 1
            # Log every 100 drops to avoid noise
            if self._dropped_count % 100 == 0:
                logger.warning(
                    f"Graspil queue full; dropped updates count={self._dropped_count}"
                )

    async def _flush_batch(self, items: List[Dict[str, Any]]) -> None:
        if not items:
            return
        assert self._session is not None
        try:
            async with self._session.post(GRASPIL_BATCH_URL, json=items, timeout=10) as resp:
                body_bytes = await resp.read()
                body_text = body_bytes.decode("utf-8", errors="ignore") if body_bytes else ""
                if resp.status >= 400:
                    raise RuntimeError(f"Graspil HTTP {resp.status}: {body_text}")
                # Success path: count and log response details (truncate body)
                self._sent_count += len(items)
                truncated = body_text[:200]
                logger.info(
                    f"Graspil batch sent: count={len(items)}, status={resp.status}, body={truncated}"
                )
                # Extra diagnostic: log first item's keys to confirm schema
                first_update = items[0].get("update", {}) if items else {}
                top_keys = list(first_update.keys())[:3]
                logger.info(f"Graspil diag: first update top-level keys={top_keys}")
        except Exception as exc:
            self._failed_flushes += 1
            raise exc

    async def _flusher(self) -> None:
        buf: List[Dict[str, Any]] = []
        loop = asyncio.get_running_loop()
        last_flush = loop.time()
        backoff_s = 1.0
        while not self._stop.is_set():
            # Gather
            try:
                item = await asyncio.wait_for(self.queue.get(), timeout=self.batch_window_s)
                buf.append(item)
            except asyncio.TimeoutError:
                pass

            now = loop.time()
            should_flush = bool(buf) and (
                len(buf) >= self.max_batch or (now - last_flush) >= self.batch_window_s
            )
            if not should_flush:
                continue

            # Try flush; on failure keep buf and backoff
            try:
                await self._flush_batch(buf)
                buf.clear()
                last_flush = now
                backoff_s = 1.0
            except Exception as exc:
                logger.info(f"Graspil flush failed; retrying in {backoff_s:.1f}s: {exc}")
                await asyncio.sleep(backoff_s)
                backoff_s = min(backoff_s * 2, 30.0)

        # On shutdown: flush buffer, then drain queue in chunks
        if buf:
            try:
                await self._flush_batch(buf)
            except Exception as exc:
                logger.info(f"Graspil final buffer flush failed: {exc}")
        await self._drain_queue_in_chunks()

    async def _drain_queue_in_chunks(self) -> None:
        remaining: List[Dict[str, Any]] = []
        while not self.queue.empty():
            try:
                remaining.append(self.queue.get_nowait())
            except asyncio.QueueEmpty:
                break
            # Flush in chunks of max_batch
            if len(remaining) >= self.max_batch:
                try:
                    await self._flush_batch(remaining)
                except Exception as exc:
                    logger.info(f"Graspil final chunk flush failed: {exc}")
                remaining.clear()
        if remaining:
            try:
                await self._flush_batch(remaining)
            except Exception as exc:
                logger.info(f"Graspil last chunk flush failed: {exc}")

    async def _heartbeat(self) -> None:
        # Lightweight reachability probe; HEAD avoids creating noisy analytics entries
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.heartbeat_interval_s)
                if self._stop.is_set():
                    break
            except asyncio.TimeoutError:
                pass
            if self._session is None:
                continue
            try:
                async with self._session.head(GRASPIL_BATCH_URL, timeout=5) as resp:
                    # Any response means connectivity is OK; status may be 405 for HEAD which is fine
                    _ = resp.status
                logger.debug("Graspil heartbeat OK")
            except Exception as exc:
                logger.info(f"Graspil heartbeat failed: {exc}")



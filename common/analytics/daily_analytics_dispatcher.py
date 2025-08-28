import os
import io
import zipfile
import asyncio
import datetime as dt
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Optional
import logging

import aiohttp


def _yesterday_local(now_utc: dt.datetime, tz: ZoneInfo) -> str:
    local_now = now_utc.astimezone(tz)
    y = (local_now - dt.timedelta(days=1)).date()
    return y.strftime("%Y-%m-%d")


class DailyAnalyticsDispatcher:
    """
    Sends yesterday's analytics JSONL (per service) daily via Telegram, then deletes that file.
    """

    def __init__(
        self,
        service_name: str,
        analytics_dir: str,
        send_time_local: str = "00:10",
        tz_name: str = "Europe/Kiev",
        tg_token: Optional[str] = None,
        tg_chat_id: Optional[str] = None,
        retention_days: int = 14,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.service = service_name
        self.dir = Path(analytics_dir) / service_name
        self.tz = ZoneInfo(tz_name)
        hh, mm = map(int, send_time_local.split(":"))
        self.send_time = (hh, mm)
        self.tg_token = tg_token or os.getenv("LOG_TG_TOKEN") or os.getenv("PING_BOT_TOKEN")
        self.tg_chat_id = tg_chat_id or os.getenv("LOG_TG_CHAT_ID") or os.getenv("ADMIN_CHAT_ID")
        self.retention_days = retention_days
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self.log = logger or logging.getLogger(f"{service_name}.daily_analytics")

    def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._run(), name=f"{self.service}_daily_analytics_dispatch")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await self._task
            finally:
                self._task = None

    def _seconds_until_next_send(self) -> float:
        now = dt.datetime.now(self.tz)
        hh, mm = self.send_time
        next_send = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if next_send <= now:
            next_send += dt.timedelta(days=1)
        return (next_send - now).total_seconds()

    def _collect_yesterday_file(self) -> Optional[Path]:
        if not self.dir.exists():
            return None
        y = _yesterday_local(dt.datetime.now(dt.timezone.utc), self.tz)
        f = self.dir / f"{y}.jsonl"
        return f if f.exists() else None

    def _zip_file_to_bytes(self, f: Path) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(f, arcname=f.name)
        buf.seek(0)
        return buf.read()

    async def _send_via_telegram(self, zip_bytes: bytes, basename: str) -> None:
        if not (self.tg_token and self.tg_chat_id):
            self.log.info("Telegram dispatch disabled (no token/chat).")
            return
        url = f"https://api.telegram.org/bot{self.tg_token}/sendDocument"
        data = aiohttp.FormData()
        data.add_field("chat_id", str(self.tg_chat_id))
        data.add_field("caption", f"{self.service} analytics for {basename}")
        data.add_field("document", zip_bytes, filename=f"{basename}.zip", content_type="application/zip")
        async with aiohttp.ClientSession() as s:
            async with s.post(url, data=data, timeout=60) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    raise RuntimeError(f"TG sendDocument HTTP {resp.status}: {body}")

    def _cleanup(self, f: Path) -> None:
        try:
            f.unlink(missing_ok=True)
        except Exception:
            pass
        # Retention sweep
        try:
            cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=self.retention_days)
            for p in self.dir.glob("*.jsonl"):
                if p.is_file() and dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc) < cutoff:
                    p.unlink(missing_ok=True)
        except Exception:
            pass

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._seconds_until_next_send())
                if self._stop.is_set():
                    break
            except asyncio.TimeoutError:
                pass

            f = self._collect_yesterday_file()
            if not f:
                self.log.info("No analytics file for yesterday; skipping.")
                continue

            basename = f"{self.service}-{f.stem}"
            try:
                payload = self._zip_file_to_bytes(f)
                await self._send_via_telegram(payload, basename)
                self._cleanup(f)
                self.log.info(f"Dispatched and cleaned {f.name}")
            except Exception as e:
                self.log.error(f"Analytics dispatch failed: {e}")



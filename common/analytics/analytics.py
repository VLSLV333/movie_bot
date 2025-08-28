import os
import json
import asyncio
import datetime as dt
from pathlib import Path
from typing import Any, Optional


class Analytics:
    """
    Minimal JSONL analytics writer. Each service writes to
    /app/logs/analytics/<service>/<YYYY-MM-DD>.jsonl by default.
    """

    def __init__(self, service_name: str, base_dir: Optional[str] = None) -> None:
        base_dir = base_dir or os.getenv("ANALYTICS_DIR", "/app/logs/analytics")
        self.dir = Path(base_dir) / service_name
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    def _file_for_today(self) -> Path:
        today = dt.datetime.now(dt.timezone.utc).date().strftime("%Y-%m-%d")
        return self.dir / f"{today}.jsonl"

    async def log_event(
        self,
        user_id: int | str | None,
        journey_id: str | None,
        event: str,
        props: Optional[dict[str, Any]] = None,
    ) -> None:
        record = {
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"),
            "user_id": user_id,
            "journey_id": journey_id,
            "event": event,
            "props": props or {},
        }
        line = json.dumps(record, ensure_ascii=False)
        async with self._lock:
            await asyncio.to_thread(self._append_line, line)

    def _append_line(self, line: str) -> None:
        path = self._file_for_today()
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")



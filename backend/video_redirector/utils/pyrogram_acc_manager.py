import os
import json
import asyncio
import time
from pathlib import Path
from pyrogram.client import Client
from sqlalchemy.ext.asyncio import AsyncSession
from backend.video_redirector.db.crud_upload_accounts import (
    increment_uploads,
    get_account_stats_by_session_name,
    get_least_used_accounts_today,
)

MULTI_ACCOUNT_CONFIG_PATH = Path('app/backend/video_redirector/utils/upload_accounts.json')
SESSION_DIR = "/app/backend/session_files"

if MULTI_ACCOUNT_CONFIG_PATH.exists():
    with open(MULTI_ACCOUNT_CONFIG_PATH, 'r') as f:
        UPLOAD_ACCOUNTS = json.load(f)
else:
    UPLOAD_ACCOUNTS = [{
        "api_id": os.getenv("API_ID"),
        "api_hash": os.getenv("API_HASH"),
        "session_name": os.getenv("SESSION_NAME")
    }]

IDLE_TIMEOUT_SECONDS = 15 * 60  # 15 minutes

class UploadAccount:
    def __init__(self, config):
        api_id = config.get("api_id")
        api_hash = config.get("api_hash")
        session_name = config.get("session_name")
        # Type and presence checks
        if api_id is None:
            raise ValueError(f"api_id missing in account config: {config}")
        if isinstance(api_id, str):
            if not api_id.isdigit():
                raise ValueError(f"api_id must be an int or digit string: {config}")
            api_id = int(api_id)
        elif not isinstance(api_id, int):
            raise ValueError(f"api_id must be an int: {config}")
        if api_hash is None or not isinstance(api_hash, str):
            raise ValueError(f"api_hash missing or not a string in account config: {config}")
        if session_name is None or not isinstance(session_name, str):
            raise ValueError(f"session_name missing or not a string in account config: {config}")
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = session_name
        self.lock = asyncio.Lock()
        self.client = None
        self.last_used = 0
        self.busy = False

    async def get_client(self):
        if self.client is None:
            session_path = os.path.join(str(SESSION_DIR), str(self.session_name))
            self.client = Client(session_path, api_id=self.api_id, api_hash=self.api_hash)
            await self.client.start()
        self.last_used = time.time()
        return self.client

    async def stop_client(self):
        if self.client is not None:
            try:
                await self.client.stop()
            except Exception:
                pass
            self.client = None

UPLOAD_ACCOUNT_POOL = [UploadAccount(cfg) for cfg in UPLOAD_ACCOUNTS]

# --- DB-based stat functions ---

async def increment_daily_stat(db: AsyncSession, session_name: str):
    await increment_uploads(db, session_name)

async def get_daily_stat(db: AsyncSession, session_name: str) -> int:
    stats = await get_account_stats_by_session_name(db, session_name)
    value = getattr(stats, 'today_uploads', 0)
    return value if isinstance(value, int) else 0

async def get_least_used_accounts(db: AsyncSession):
    accounts = await get_least_used_accounts_today(db)
    if not accounts:
        return list(range(len(UPLOAD_ACCOUNT_POOL)))
    min_uploads = getattr(accounts[0], 'today_uploads', 0)
    if not isinstance(min_uploads, int):
        min_uploads = 0
    least_used_names = [acc.session_name for acc in accounts if getattr(acc, 'today_uploads', 0) == min_uploads]
    return [i for i, acc in enumerate(UPLOAD_ACCOUNT_POOL) if acc.session_name in least_used_names]

async def select_upload_account(db: AsyncSession):
    least_used = await get_least_used_accounts(db)
    for idx in least_used:
        acc = UPLOAD_ACCOUNT_POOL[idx]
        if not acc.busy:
            return idx, acc
    for idx, acc in enumerate(UPLOAD_ACCOUNT_POOL):
        if not acc.busy:
            return idx, acc
    return 0, UPLOAD_ACCOUNT_POOL[0]

async def idle_client_cleanup():
    while True:
        now = time.time()
        for account in UPLOAD_ACCOUNT_POOL:
            if account.client is not None and (now - account.last_used) > IDLE_TIMEOUT_SECONDS:
                await account.stop_client()
        await asyncio.sleep(300)  # Check every 5 minutes

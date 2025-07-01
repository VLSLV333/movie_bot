import os
import json
import datetime
import asyncio
from pathlib import Path
from pyrogram.client import Client

MULTI_ACCOUNT_CONFIG_PATH = Path('app/backend/video_redirector/utils/upload_accounts.json')
DAILY_STATS_PATH = Path('app/backend/video_redirector/utils/upload_daily_stats.json')
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
        return self.client

    async def stop_client(self):
        if self.client is not None:
            await self.client.stop()
            self.client = None

UPLOAD_ACCOUNT_POOL = [UploadAccount(cfg) for cfg in UPLOAD_ACCOUNTS]

def load_daily_stats():
    if DAILY_STATS_PATH.exists():
        with open(DAILY_STATS_PATH, 'r') as f:
            data = json.load(f)
    else:
        data = {}
    today = datetime.date.today().isoformat()
    if data.get('date') != today:
        data = {'date': today, 'stats': {}}
    return data

def save_daily_stats(data):
    with open(DAILY_STATS_PATH, 'w') as f:
        json.dump(data, f)

def increment_daily_stat(account_idx):
    data = load_daily_stats()
    stats = data.setdefault('stats', {})
    stats[str(account_idx)] = stats.get(str(account_idx), 0) + 1
    save_daily_stats(data)

def get_daily_stat(account_idx):
    data = load_daily_stats()
    return data.get('stats', {}).get(str(account_idx), 0)

def get_least_used_accounts():
    data = load_daily_stats()
    stats = data.get('stats', {})
    min_count = min(stats.values(), default=0)
    return [i for i, _ in enumerate(UPLOAD_ACCOUNT_POOL) if stats.get(str(i), 0) == min_count]

def increment_total_stat(account_idx):
    pass

def get_total_stat(account_idx):
    return 0

async def select_upload_account():
    least_used = get_least_used_accounts()
    for idx in least_used:
        acc = UPLOAD_ACCOUNT_POOL[idx]
        if not acc.busy:
            return idx, acc
    for idx, acc in enumerate(UPLOAD_ACCOUNT_POOL):
        if not acc.busy:
            return idx, acc
    return 0, UPLOAD_ACCOUNT_POOL[0]

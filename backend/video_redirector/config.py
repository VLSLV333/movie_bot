import os
import json
from dotenv import load_dotenv

load_dotenv()

REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT"))
DEFAULT_USER_DOWNLOAD_LIMIT = 1
PREMIUM_USER_DOWNLOAD_LIMIT = 3
MAX_CONCURRENT_DOWNLOADS = 2
MAX_RETRIES_FOR_DOWNLOAD = 1

PROXY_CONFIG = {
    "enabled": os.getenv("PROXY_ENABLED", "false").lower() == "true",
    "url": os.getenv("PROXY_URL", ""),
    "rotation_interval": int(os.getenv("PROXY_ROTATION_INTERVAL", "20")),
    "rotation_url": os.getenv("PROXY_ROTATION_URL", ""),
    "rotation_method": os.getenv("PROXY_ROTATION_METHOD", "GET"),
    "rotation_headers": json.loads(os.getenv("PROXY_ROTATION_HEADERS", "{}")),
    "rotation_timeout": int(os.getenv("PROXY_ROTATION_TIMEOUT", "300")),
    "rotate_on_startup": os.getenv("PROXY_ROTATE_ON_STARTUP", "false").lower() == "true",
}
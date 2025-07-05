import os
import json
from dotenv import load_dotenv

load_dotenv()

REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT"))
DEFAULT_USER_DOWNLOAD_LIMIT = 1
PREMIUM_USER_DOWNLOAD_LIMIT = 3
MAX_CONCURRENT_DOWNLOADS = 2  
MAX_CONCURRENT_MERGES_OF_TS_INTO_MP4 = 3  
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
    "smart_rotation_enabled": os.getenv("PROXY_SMART_ROTATION_ENABLED", "true").lower() == "true", # detects if TG is giving us "wait to upload big file" 
    "rate_limit_wait_threshold": int(os.getenv("PROXY_RATE_LIMIT_WAIT_THRESHOLD", "5")), # if "wait to upload big file for 5 seconds" - reload proxy IP
    "rate_limit_detection_window": int(os.getenv("PROXY_RATE_LIMIT_DETECTION_WINDOW", "10")), # if "wait to upload big file for 5 seconds" happened in last 10 minutes - reload proxy IP
    "max_rate_limit_events": int(os.getenv("PROXY_MAX_RATE_LIMIT_EVENTS", "3")), # if "wait to upload big file for 5 seconds" happened in last 10 minutes 3 times - reload proxy IP
}
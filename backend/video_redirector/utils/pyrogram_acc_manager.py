import os
import json
import asyncio
import time
import aiohttp
from pathlib import Path
from pyrogram.client import Client
from sqlalchemy.ext.asyncio import AsyncSession
from backend.video_redirector.db.crud_upload_accounts import (
    increment_uploads,
    get_account_stats_by_session_name,
    get_least_used_accounts_today,
)
import logging
from backend.video_redirector.config import PROXY_CONFIG

logger = logging.getLogger(__name__)

MULTI_ACCOUNT_CONFIG_PATH = Path('app/backend/video_redirector/utils/upload_accounts.json')
SESSION_DIR = "/app/backend/session_files"

# Log proxy configuration status
if PROXY_CONFIG["enabled"]:
    logger.info("🌐 Proxy support enabled")
    logger.info(f"   Rotation interval: {PROXY_CONFIG['rotation_interval']} uploads")
    logger.info(f"   Rotation timeout: {PROXY_CONFIG['rotation_timeout']} seconds")
    if PROXY_CONFIG["rotation_url"]:
        logger.info(f"   IP rotation URL: {PROXY_CONFIG['rotation_url']}")
        logger.info(f"   Rotation method: {PROXY_CONFIG['rotation_method']}")
    else:
        logger.warning("⚠️ Proxy enabled but no rotation URL configured")
else:
    logger.info("🌐 Proxy support disabled")

async def initialize_ip_detection():
    """Initialize IP detection on startup"""
    if PROXY_CONFIG["enabled"]:
        logger.info("🌐 Initializing IP detection...")
        initial_ip = await get_current_ip()
        if initial_ip:
            logger.info(f"🌐 Initial IP detected: {initial_ip}")
        else:
            logger.warning("⚠️ Could not detect initial IP address")
    else:
        logger.info("🌐 IP detection skipped - proxy not enabled")

# Track uploads for IP rotation
_upload_counter = 0
_last_ip_rotation = 0
_current_ip = None  # Track current IP address

# Global upload management
_global_upload_lock = asyncio.Lock()  # Prevents new uploads during rotation
_active_uploads = set()  # Track active upload task IDs
_rotation_in_progress = False  # Flag to indicate rotation is happening

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

async def get_current_ip():
    """Get the current public IP address"""
    global _current_ip
    
    try:
        # Use multiple IP check services for reliability
        ip_check_urls = [
            "https://api.ipify.org",
            "https://ipinfo.io/ip",
            "https://icanhazip.com",
            "https://checkip.amazonaws.com"
        ]
        
        async with aiohttp.ClientSession() as session:
            for url in ip_check_urls:
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        if response.status == 200:
                            ip = (await response.text()).strip()
                            if ip and len(ip.split('.')) == 4:  # Basic IPv4 validation
                                _current_ip = ip
                                logger.info(f"🌐 Current IP detected: {ip} (via {url})")
                                return ip
                except Exception as e:
                    logger.debug(f"Failed to get IP from {url}: {e}")
                    continue
        
        logger.warning("⚠️ Could not detect current IP address from any service")
        return _current_ip  # Return last known IP if available
        
    except Exception as e:
        logger.error(f"❌ Error getting current IP: {e}")
        return _current_ip

async def log_ip_change(old_ip: str | None, new_ip: str | None):
    """Log IP change with detailed information"""
    if old_ip and new_ip and old_ip != new_ip:
        logger.info(f"🔄 IP Rotation Successful!")
        logger.info(f"   Previous IP: {old_ip}")
        logger.info(f"   New IP: {new_ip}")
        logger.info(f"   IP Changed: ✅")
    elif old_ip and new_ip and old_ip == new_ip:
        logger.warning(f"⚠️ IP Rotation Completed but IP remains the same")
        logger.info(f"   Current IP: {new_ip}")
        logger.info(f"   IP Changed: ❌ (same IP)")
    elif not old_ip and new_ip:
        logger.info(f"🌐 Initial IP detected: {new_ip}")
    else:
        logger.error(f"❌ IP detection failed")

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
        self.last_client_creation = 0  # Track when client was last created
        self.client_creation_cooldown = 60  # 60 seconds cooldown between client creations

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
                logger.info(f"Stopped client for account {self.session_name}")
            except Exception as e:
                # Log but don't raise - client might already be stopped
                logger.warning(f"Error stopping client for {self.session_name}: {e}")
            finally:
                self.client = None
                # Don't update last_client_creation here - only when creating new clients

    async def is_client_healthy(self):
        """Check if the client is healthy and can be used"""
        if self.client is None:
            return False
        try:
            # Check if client is connected without making API calls
            if not self.client.is_connected:
                return False
            return True
        except Exception:
            return False

    async def ensure_client_ready(self):
        """Ensure client is ready for use, start if needed"""
        current_time = time.time()
        
        # Check if we're in cooldown period
        if (self.client is None and 
            current_time - self.last_client_creation < self.client_creation_cooldown):
            logger.warning(f"Account {self.session_name} in cooldown, waiting...")
            await asyncio.sleep(self.client_creation_cooldown - (current_time - self.last_client_creation))
        
        if self.client is None:
            session_path = os.path.join(str(SESSION_DIR), str(self.session_name))
            
            # Configure proxy if enabled
            proxy_config = None
            if PROXY_CONFIG["enabled"] and PROXY_CONFIG["url"]:
                proxy_config = {
                    "scheme": PROXY_CONFIG["url"].split("://")[0],
                    "hostname": PROXY_CONFIG["url"].split("@")[-1].split(":")[0],
                    "port": int(PROXY_CONFIG["url"].split(":")[-1]),
                }
                
                # Add authentication if present
                if "@" in PROXY_CONFIG["url"]:
                    auth_part = PROXY_CONFIG["url"].split("@")[0].split("://")[1]
                    if ":" in auth_part:
                        username, password = auth_part.split(":")
                        proxy_config["username"] = username
                        proxy_config["password"] = password
                
                # Log proxy configuration
                logger.info(f"🔧 Creating client with proxy for account {self.session_name}")
                logger.info(f"   Proxy: {proxy_config['scheme']}://{proxy_config['hostname']}:{proxy_config['port']}")
                if 'username' in proxy_config:
                    logger.info(f"   Auth: {proxy_config['username']}:***")
            else:
                logger.info(f"🔧 Creating client without proxy for account {self.session_name}")
            
            client_kwargs = {
                "session_path": session_path,
                "api_id": self.api_id,
                "api_hash": self.api_hash,
            }
            if proxy_config:
                client_kwargs["proxy"] = proxy_config
            
            self.client = Client(**client_kwargs)
            await self.client.start()
            self.last_client_creation = current_time
            
            # Get and log current IP after client creation
            if PROXY_CONFIG["enabled"]:
                current_ip = await get_current_ip()
                if current_ip:
                    logger.info(f"🌐 Client {self.session_name} created successfully with IP: {current_ip}")
                else:
                    logger.warning(f"⚠️ Client {self.session_name} created but IP detection failed")
            else:
                logger.info(f"✅ Client {self.session_name} created successfully (no proxy)")
        elif not self.client.is_connected:
            # Try to restart the client if it's not connected
            try:
                await self.client.stop()
            except Exception:
                pass
            self.client = None
            
            # Check cooldown before recreating
            if current_time - self.last_client_creation < self.client_creation_cooldown:
                logger.warning(f"Account {self.session_name} in cooldown after disconnect, waiting...")
                await asyncio.sleep(self.client_creation_cooldown - (current_time - self.last_client_creation))
            
            session_path = os.path.join(str(SESSION_DIR), str(self.session_name))
            
            # Configure proxy if enabled
            proxy_config = None
            if PROXY_CONFIG["enabled"] and PROXY_CONFIG["url"]:
                proxy_config = {
                    "scheme": PROXY_CONFIG["url"].split("://")[0],
                    "hostname": PROXY_CONFIG["url"].split("@")[-1].split(":")[0],
                    "port": int(PROXY_CONFIG["url"].split(":")[-1]),
                }
                
                # Add authentication if present
                if "@" in PROXY_CONFIG["url"]:
                    auth_part = PROXY_CONFIG["url"].split("@")[0].split("://")[1]
                    if ":" in auth_part:
                        username, password = auth_part.split(":")
                        proxy_config["username"] = username
                        proxy_config["password"] = password
                
                # Log proxy configuration for recreation
                logger.info(f"🔧 Recreating client with proxy for account {self.session_name}")
                logger.info(f"   Proxy: {proxy_config['scheme']}://{proxy_config['hostname']}:{proxy_config['port']}")
                if 'username' in proxy_config:
                    logger.info(f"   Auth: {proxy_config['username']}:***")
            else:
                logger.info(f"🔧 Recreating client without proxy for account {self.session_name}")
            
            client_kwargs = {
                "session_path": session_path,
                "api_id": self.api_id,
                "api_hash": self.api_hash,
            }
            if proxy_config:
                client_kwargs["proxy"] = proxy_config
            
            self.client = Client(**client_kwargs)
            await self.client.start()
            self.last_client_creation = time.time()
            
            # Get and log current IP after client recreation
            if PROXY_CONFIG["enabled"]:
                current_ip = await get_current_ip()
                if current_ip:
                    logger.info(f"🌐 Client {self.session_name} recreated successfully with IP: {current_ip}")
                else:
                    logger.warning(f"⚠️ Client {self.session_name} recreated but IP detection failed")
            else:
                logger.info(f"✅ Client {self.session_name} recreated successfully (no proxy)")
        
        self.last_used = time.time()
        return self.client

UPLOAD_ACCOUNT_POOL = [UploadAccount(cfg) for cfg in UPLOAD_ACCOUNTS]

# --- Global upload management functions ---

async def register_upload_start(task_id: str):
    """Register that an upload has started"""
    global _active_uploads
    _active_uploads.add(task_id)
    logger.debug(f"📤 Upload {task_id} registered as active")

async def register_upload_end(task_id: str):
    """Register that an upload has ended"""
    global _active_uploads
    _active_uploads.discard(task_id)
    logger.debug(f"✅ Upload {task_id} completed and unregistered")

async def wait_for_ongoing_uploads(timeout: int | None = None):
    """Wait for all ongoing uploads to complete"""
    global _active_uploads, _rotation_in_progress
    
    if timeout is None:
        timeout = PROXY_CONFIG["rotation_timeout"]
    
    if not _active_uploads:
        logger.info("🔄 No active uploads to wait for")
        return True
    
    logger.info(f"⏳ Waiting for {len(_active_uploads)} ongoing uploads to complete...")
    logger.info(f"   Active uploads: {list(_active_uploads)}")
    
    start_time = time.time()
    timeout_seconds = timeout or PROXY_CONFIG["rotation_timeout"]
    while _active_uploads and (time.time() - start_time) < timeout_seconds:
        remaining = list(_active_uploads)
        logger.info(f"⏳ Still waiting for {len(remaining)} uploads: {remaining}")
        await asyncio.sleep(5)  # Check every 5 seconds
    
    if _active_uploads:
        logger.warning(f"⚠️ Timeout reached, {len(_active_uploads)} uploads still active: {list(_active_uploads)}")
        return False
    else:
        logger.info("✅ All uploads completed successfully")
        return True

async def acquire_upload_permission():
    """Acquire permission to start a new upload (waits if rotation is in progress)"""
    global _rotation_in_progress
    
    # Wait for any ongoing rotation to complete
    while _rotation_in_progress:
        logger.info("⏳ Upload rotation in progress, waiting for completion...")
        await asyncio.sleep(2)
    
    # Acquire the global upload lock
    await _global_upload_lock.acquire()
    return True

def release_upload_permission():
    """Release the upload permission lock"""
    try:
        _global_upload_lock.release()
    except RuntimeError:
        # Lock might already be released
        pass

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
    """Select the best available upload account with improved rate limiting handling"""
    # First try to get least used accounts
    least_used = await get_least_used_accounts(db)
    
    # Check least used accounts first
    for idx in least_used:
        acc = UPLOAD_ACCOUNT_POOL[idx]
        if not acc.busy:
            # Check if account was recently used (within last 30 seconds)
            if time.time() - acc.last_used > 30:
                # Only check health if client exists, don't create new connections
                if acc.client is None or await acc.is_client_healthy():
                    return idx, acc
                else:
                    # Client is unhealthy, stop it and continue
                    logger.warning(f"Account {acc.session_name} has unhealthy client, stopping it")
                    await acc.stop_client()
    
    # If no least used accounts available, try any non-busy account
    for idx, acc in enumerate(UPLOAD_ACCOUNT_POOL):
        if not acc.busy:
            # Check if account was recently used (within last 30 seconds)
            if time.time() - acc.last_used > 30:
                # Only check health if client exists, don't create new connections
                if acc.client is None or await acc.is_client_healthy():
                    return idx, acc
                else:
                    # Client is unhealthy, stop it and continue
                    logger.warning(f"Account {acc.session_name} has unhealthy client, stopping it")
                    await acc.stop_client()
    
    # If all accounts are busy or recently used, wait a bit and return the first one
    logger.warning("All upload accounts are busy or recently used, waiting...")
    await asyncio.sleep(10)  # Wait 10 seconds
    return 0, UPLOAD_ACCOUNT_POOL[0]

async def idle_client_cleanup():
    while True:
        now = time.time()
        for account in UPLOAD_ACCOUNT_POOL:
            if account.client is not None and (now - account.last_used) > IDLE_TIMEOUT_SECONDS:
                await account.stop_client()
        await asyncio.sleep(300)  # Check every 5 minutes

async def rotate_proxy_ip():
    """Rotate the proxy IP address with upload coordination"""
    global _last_ip_rotation, _rotation_in_progress, _current_ip
    
    if not PROXY_CONFIG["enabled"] or not PROXY_CONFIG["rotation_url"]:
        logger.info("🔄 Proxy rotation skipped - proxy not enabled or no rotation URL")
        return
    
    current_time = time.time()
    # Prevent too frequent rotations (minimum 30 seconds between rotations)
    if current_time - _last_ip_rotation < 30:
        logger.info("🔄 Proxy rotation skipped - too recent (minimum 30s between rotations)")
        return
    
    # Get current IP before rotation
    old_ip = await get_current_ip()
    logger.info(f"🔄 Starting proxy IP rotation")
    logger.info(f"   Current IP before rotation: {old_ip or 'Unknown'}")
    logger.info(f"   Rotation URL: {PROXY_CONFIG['rotation_url']}")
    logger.info(f"   Rotation method: {PROXY_CONFIG['rotation_method']}")
    
    # Set rotation flag to prevent new uploads
    _rotation_in_progress = True
    logger.info("🔄 Preventing new uploads during rotation...")
    
    try:
        # Wait for ongoing uploads to complete
        all_completed = await wait_for_ongoing_uploads()
        
        if not all_completed:
            logger.warning("⚠️ Some uploads didn't complete before timeout, proceeding with rotation anyway")
        
        # Perform the actual IP rotation
        logger.info(f"🔄 Sending rotation request to proxy provider...")
        async with aiohttp.ClientSession() as session:
            if PROXY_CONFIG["rotation_method"].upper() == "POST":
                async with session.post(
                    PROXY_CONFIG["rotation_url"],
                    headers=PROXY_CONFIG["rotation_headers"],
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        logger.info("✅ Proxy rotation request successful")
                        _last_ip_rotation = current_time
                    else:
                        logger.warning(f"⚠️ Proxy rotation failed with status {response.status}")
                        logger.warning(f"   Response: {await response.text()}")
            else:
                async with session.get(
                    PROXY_CONFIG["rotation_url"],
                    headers=PROXY_CONFIG["rotation_headers"],
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        logger.info("✅ Proxy rotation request successful")
                        _last_ip_rotation = current_time
                    else:
                        logger.warning(f"⚠️ Proxy rotation failed with status {response.status}")
                        logger.warning(f"   Response: {await response.text()}")
        
        # Wait a moment for the new IP to be active
        logger.info("⏳ Waiting 5 seconds for new IP to become active...")
        await asyncio.sleep(5)
        
        # Get new IP after rotation
        new_ip = await get_current_ip()
        
        # Log IP change details
        await log_ip_change(old_ip, new_ip)
        
        # Update global IP tracker
        _current_ip = new_ip
        
    except Exception as e:
        logger.error(f"❌ Proxy rotation error: {e}")
        logger.error(f"   Error type: {type(e).__name__}")
    finally:
        # Clear rotation flag to allow new uploads
        _rotation_in_progress = False
        logger.info("🔄 Proxy IP rotation completed - new uploads can proceed")

def should_rotate_ip():
    """Check if we should rotate IP based on upload count"""
    global _upload_counter
    
    if not PROXY_CONFIG["enabled"]:
        return False
    
    _upload_counter += 1
    should_rotate = _upload_counter >= PROXY_CONFIG["rotation_interval"]
    
    if should_rotate:
        _upload_counter = 0
        logger.info(f"🔄 IP rotation triggered after {PROXY_CONFIG['rotation_interval']} uploads")
        logger.info(f"   Upload counter reset to 0")
    else:
        logger.debug(f"📊 Upload counter: {_upload_counter}/{PROXY_CONFIG['rotation_interval']} (rotation at {PROXY_CONFIG['rotation_interval']})")
    
    return should_rotate

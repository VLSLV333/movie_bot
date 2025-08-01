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
    create_or_get_account_stats,
    get_all_stats,
)
import logging
from backend.video_redirector.config import PROXY_CONFIG

# Import aiohttp_socks for SOCKS5 support (optional - will be installed)
try:
    from aiohttp_socks import ProxyConnector
    SOCKS5_AVAILABLE = True
except ImportError:
    SOCKS5_AVAILABLE = False
    ProxyConnector = None

logger = logging.getLogger(__name__)

MULTI_ACCOUNT_CONFIG_PATH = Path('/app/backend/video_redirector/utils/upload_accounts.json')
SESSION_DIR = "/app/backend/session_files"

# Log proxy configuration status
if PROXY_CONFIG["enabled"]:
    logger.info("🌐 Proxy support enabled")
    logger.info(f"   Rotation interval: {PROXY_CONFIG['rotation_interval']} uploads")
    logger.info(f"   Rotation timeout: {PROXY_CONFIG['rotation_timeout']} seconds")
    if not PROXY_CONFIG["rotation_url"]:
        logger.warning("⚠️ Proxy enabled but no rotation URL configured")
    
    # Log smart rotation configuration
    if PROXY_CONFIG.get("smart_rotation_enabled", True):
        logger.info("🧠 Smart IP rotation enabled")
        logger.info(f"   Rate limit threshold: {PROXY_CONFIG.get('rate_limit_wait_threshold', 5)}s")
    else:
        logger.info("🧠 Smart IP rotation disabled - using upload counter only")
else:
    logger.info("🌐 Proxy support disabled")

async def initialize_ip_detection():
    """Initialize IP detection on startup"""
    if PROXY_CONFIG["enabled"]:
        initial_ip = await get_current_ip()
        if not initial_ip:
            logger.warning("⚠️ Could not detect initial IP address")
    else:
        logger.info("🌐 IP detection skipped - proxy not enabled")

async def initialize_proxy_on_startup():
    """Initialize proxy settings on bot startup"""
    global _upload_counter
    
    if PROXY_CONFIG["enabled"]:

        # Reset upload counter to ensure fresh start
        _upload_counter = 0

        # Optionally force IP rotation on startup for fresh IP
        if PROXY_CONFIG.get("rotate_on_startup", False):
            logger.info("🔄 Forcing IP rotation on startup...")
            await rotate_proxy_ip()
        else:
            logger.info("🌐 Using current proxy IP (no rotation on startup)")
        
        # Initialize IP detection
        await initialize_ip_detection()
    else:
        logger.info("🌐 Proxy initialization skipped - proxy not enabled")

# Track uploads for IP rotation
_upload_counter = 0
_last_ip_rotation = 0
_current_ip = None  # Track current IP address

# Smart rotation tracking
_rate_limit_events = []  # Track rate limit events with timestamps
_rate_limit_detection_window = PROXY_CONFIG.get("rate_limit_detection_window", 10)
_rate_limit_wait_threshold = PROXY_CONFIG.get("rate_limit_wait_threshold", 5)
_max_rate_limit_events = PROXY_CONFIG.get("max_rate_limit_events", 3)

# Global upload management
_global_upload_lock = asyncio.Lock()  # Prevents new uploads during rotation
_active_uploads = set()  # Track active upload task IDs
_rotation_in_progress = False  # Flag to indicate rotation is happening
_rotation_lock = asyncio.Lock()  # Prevents multiple simultaneous rotation calls

# Initialize UPLOAD_ACCOUNTS with fallback
logger.debug(f"🔍 Looking for upload accounts config at: {MULTI_ACCOUNT_CONFIG_PATH}")
logger.debug(f"🔍 Current working directory: {os.getcwd()}")
logger.debug(f"🔍 Config file exists: {MULTI_ACCOUNT_CONFIG_PATH.exists()}")

if MULTI_ACCOUNT_CONFIG_PATH.exists():
    with open(MULTI_ACCOUNT_CONFIG_PATH, 'r') as f:
        UPLOAD_ACCOUNTS = json.load(f)
        logger.info(f"✅ Loaded {len(UPLOAD_ACCOUNTS)} accounts from {MULTI_ACCOUNT_CONFIG_PATH}")
else:
    logger.error(f'❌ MULTI_ACCOUNT_CONFIG_PATH was not found at {MULTI_ACCOUNT_CONFIG_PATH}! No accounts can be used to upload videos')
    # Fallback to empty list to prevent NameError
    UPLOAD_ACCOUNTS = []

IDLE_TIMEOUT_SECONDS = 15 * 60  # 15 minutes

async def get_current_ip():
    """Get the current public IP address"""
    global _current_ip
    
    try:
        # Use multiple IP check services for reliability
        ip_check_urls = [
            "http://api.ipify.org",
            "http://ipinfo.io/ip",
            "http://icanhazip.com",
            "http://checkip.amazonaws.com"
        ]
        
        # Configure proxy for IP detection if enabled
        proxy_config = None
        if PROXY_CONFIG["enabled"] and PROXY_CONFIG["url"]:
            proxy_url = PROXY_CONFIG["url"]
            scheme = proxy_url.split("://")[0]
            hostname = proxy_url.split("@")[-1].split(":")[0]
            port = int(proxy_url.split(":")[-1])
            
            # Extract authentication if present
            username = None
            password = None
            if "@" in proxy_url:
                auth_part = proxy_url.split("@")[0].split("://")[1]
                if ":" in auth_part:
                    username, password = auth_part.split(":")
            
            # Configure proxy for aiohttp with proper SOCKS5 support
            if scheme == "socks5":
                if SOCKS5_AVAILABLE and ProxyConnector:
                    if username and password:
                        connector = ProxyConnector.from_url(f"socks5://{username}:{password}@{hostname}:{port}")
                    else:
                        connector = ProxyConnector.from_url(f"socks5://{hostname}:{port}")
                else:
                    logger.warning("⚠️ SOCKS5 proxy configured but aiohttp-socks not available. IP detection may fail.")
                    connector = None
                    proxy_config = None
            else:
                # HTTP proxy configuration (fallback)
                if username and password:
                    proxy_config = f"http://{username}:{password}@{hostname}:{port}"
                else:
                    proxy_config = f"http://{hostname}:{port}"
                connector = None
        else:
            connector = None
            proxy_config = None
        
        # Create session with appropriate connector
        if connector:
            async with aiohttp.ClientSession(connector=connector) as session:
                for url in ip_check_urls:
                    try:
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                            if response.status == 200:
                                ip = (await response.text()).strip()
                                if ip and len(ip.split('.')) == 4:  # Basic IPv4 validation
                                    _current_ip = ip
                                    return ip
                    except Exception as e:
                        logger.debug(f"Failed to get IP from {url} via SOCKS5: {e}")
                        continue
        else:
            # Use regular aiohttp session
            async with aiohttp.ClientSession() as session:
                for url in ip_check_urls:
                    try:
                        if proxy_config:
                            async with session.get(url, proxy=proxy_config, timeout=aiohttp.ClientTimeout(total=10)) as response:
                                if response.status == 200:
                                    ip = (await response.text()).strip()
                                    if ip and len(ip.split('.')) == 4:  # Basic IPv4 validation
                                        _current_ip = ip
                                        logger.info(f"🌐 Current IP detected via HTTP proxy: {ip} (via {url})")
                                        return ip
                        else:
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
        logger.info(f"🌐 Previous IP: {old_ip}")
        logger.info(f"🌐 New IP: {new_ip}")
        logger.debug(f"IP Changed: ✅")
    elif old_ip and new_ip and old_ip == new_ip:
        logger.warning(f"⚠️ IP Rotation Completed but IP remains the same")
        logger.debug(f"   Current IP: {new_ip}")
        logger.debug(f"   IP Changed: ❌ (same IP)")
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
            remaining_cooldown = self.client_creation_cooldown - (current_time - self.last_client_creation)
            logger.warning(f"Account {self.session_name} in cooldown, waiting {remaining_cooldown:.1f}s...")
            await asyncio.sleep(remaining_cooldown)
        
        if self.client is None:
            session_path = os.path.join(str(SESSION_DIR), str(self.session_name))
            
            # 🔍 ENHANCED DIAGNOSTICS: Check session file
            session_file = f"{session_path}.session"
            logger.info(f"🔍 [{self.session_name}] Checking session file: {session_file}")
            
            if not os.path.exists(session_file):
                logger.error(f"❌ [{self.session_name}] Session file not found: {session_file}")
                logger.error(f"   Expected directory: {SESSION_DIR}")
                logger.error(f"   Directory exists: {os.path.exists(SESSION_DIR)}")
                logger.error(f"   Directory contents: {os.listdir(SESSION_DIR) if os.path.exists(SESSION_DIR) else 'N/A'}")
                return None
            
            # Check session file size and permissions
            try:
                session_size = os.path.getsize(session_file)
                session_permissions = oct(os.stat(session_file).st_mode)[-3:]
                logger.info(f"📁 [{self.session_name}] Session file size: {session_size} bytes, permissions: {session_permissions}")
                
                if session_size == 0:
                    logger.error(f"❌ [{self.session_name}] Session file is empty: {session_file}")
                    return None
                elif session_size < 100:
                    logger.warning(f"⚠️ [{self.session_name}] Session file seems too small: {session_size} bytes")
            except Exception as e:
                logger.error(f"❌ [{self.session_name}] Error checking session file: {e}")
                return None
            
            # 🔍 ENHANCED DIAGNOSTICS: Check API credentials
            logger.info(f"🔑 [{self.session_name}] API credentials check:")
            logger.info(f"   API ID: {self.api_id} (type: {type(self.api_id)})")
            logger.info(f"   API Hash: {self.api_hash[:10]}... (length: {len(self.api_hash)})")
            
            if not self.api_id or not self.api_hash:
                logger.error(f"❌ [{self.session_name}] Missing API credentials")
                return None
            
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
                
                # 🔍 ENHANCED DIAGNOSTICS: Log proxy configuration
                logger.info(f"🌐 [{self.session_name}] Proxy configuration:")
                logger.info(f"   Scheme: {proxy_config['scheme']}")
                logger.info(f"   Hostname: {proxy_config['hostname']}")
                logger.info(f"   Port: {proxy_config['port']}")
                logger.info(f"   Username: {proxy_config.get('username', 'None')}")
                logger.info(f"   Password: {'***' if proxy_config.get('password') else 'None'}")
            else:
                logger.info(f"🌐 [{self.session_name}] No proxy configured")
            
            # Create client with detailed error handling
            try:
                logger.info(f"🔧 [{self.session_name}] Creating Pyrogram client...")
                
                if proxy_config:
                    self.client = Client(
                        session_path,
                        api_id=self.api_id,
                        api_hash=self.api_hash,
                        proxy=proxy_config
                    )
                else:
                    self.client = Client(
                        session_path,
                        api_id=self.api_id,
                        api_hash=self.api_hash
                    )
                
                logger.info(f"✅ [{self.session_name}] Client object created successfully")
                
                # Start client with detailed logging
                logger.info(f"🚀 [{self.session_name}] Starting client...")
                await self.client.start()
                logger.info(f"✅ [{self.session_name}] Client started successfully")
                
                self.last_client_creation = current_time
                
                # Get and log current IP after client creation
                if PROXY_CONFIG["enabled"]:
                    current_ip = await get_current_ip()
                    if current_ip:
                        logger.info(f"🌐 [{self.session_name}] Client created with IP: {current_ip}")
                    else:
                        logger.warning(f"⚠️ [{self.session_name}] Client created but IP detection failed")
                else:
                    logger.info(f"✅ [{self.session_name}] Client created successfully (no proxy)")
                    
            except Exception as e:
                logger.error(f"❌ [{self.session_name}] Failed to create/start client: {type(e).__name__}: {e}")
                
                # 🔍 ENHANCED DIAGNOSTICS: Categorize the error
                error_str = str(e).lower()
                if "session" in error_str or "auth" in error_str:
                    logger.error(f"🔐 [{self.session_name}] Authentication/Session error - check API credentials and session file")
                elif "proxy" in error_str or "connection" in error_str:
                    logger.error(f"🌐 [{self.session_name}] Proxy/Connection error - check proxy configuration")
                elif "timeout" in error_str:
                    logger.error(f"⏰ [{self.session_name}] Timeout error - check network connectivity")
                else:
                    logger.error(f"❓ [{self.session_name}] Unknown error type - {type(e).__name__}")
                
                self.client = None
                return None
        
        self.last_used = time.time()
        return self.client

UPLOAD_ACCOUNT_POOL = [UploadAccount(cfg) for cfg in UPLOAD_ACCOUNTS]

# Validate that we have at least one account
if not UPLOAD_ACCOUNT_POOL:
    logger.critical("🚨 No upload accounts available! Application cannot start.")
    logger.critical(f"   Expected config file: {MULTI_ACCOUNT_CONFIG_PATH}")
    logger.critical("   Please ensure upload_accounts.json exists and contains valid account configurations.")
    raise RuntimeError("No upload accounts available - cannot start application")

logger.info(f"✅ Initialized {len(UPLOAD_ACCOUNT_POOL)} upload accounts: {[acc.session_name for acc in UPLOAD_ACCOUNT_POOL]}")

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
        logger.debug("🔄 No active uploads to wait for")
        return True
    
    logger.info(f"⏳ Waiting for {len(_active_uploads)} ongoing uploads to complete...")
    logger.debug(f"   Active uploads: {list(_active_uploads)}")
    
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

async def initialize_all_accounts_in_db(db: AsyncSession):
    """Initialize all upload accounts in the database to ensure proper load balancing"""
    logger.info(f"🔧 Initializing {len(UPLOAD_ACCOUNT_POOL)} accounts in database...")
    
    initialized_count = 0
    for account in UPLOAD_ACCOUNT_POOL:
        try:
            stats = await create_or_get_account_stats(db, account.session_name)
            if stats:
                logger.info(f"✅ Account {account.session_name} initialized in database")
                initialized_count += 1
            else:
                logger.error(f"❌ Failed to initialize account {account.session_name} in database")
        except Exception as e:
            logger.error(f"❌ Error initializing account {account.session_name}: {e}")
    
    logger.info(f"🎯 Database initialization complete: {initialized_count}/{len(UPLOAD_ACCOUNT_POOL)} accounts initialized")
    return initialized_count

async def diagnose_account_distribution(db: AsyncSession):
    """Diagnose the current distribution of accounts in the database"""
    logger.debug("🔍 Diagnosing account distribution in database...")
    
    try:
        # Get all accounts from database
        db_accounts = await get_all_stats(db)
        db_account_names = {acc.session_name for acc in db_accounts}
        
        # Get all configured accounts
        configured_account_names = {acc.session_name for acc in UPLOAD_ACCOUNT_POOL}
        
        # Find missing accounts
        missing_accounts = configured_account_names - db_account_names
        extra_accounts = db_account_names - configured_account_names
        
        logger.debug(f"📊 Account Distribution Analysis:")
        logger.info(f"   Configured accounts: {len(configured_account_names)}")
        logger.debug(f"   Database accounts: {len(db_account_names)}")
        logger.debug(f"   Missing from DB: {len(missing_accounts)}")
        logger.debug(f"   Extra in DB: {len(extra_accounts)}")
        
        if missing_accounts:
            logger.warning(f"⚠️ Missing accounts in database: {list(missing_accounts)}")
        
        if extra_accounts:
            logger.warning(f"⚠️ Extra accounts in database: {list(extra_accounts)}")
        
        # Show usage statistics
        if db_accounts:
            logger.info(f"📈 Current usage statistics:")
            for acc in sorted(db_accounts, key=lambda x: getattr(x, 'today_uploads', 0)):
                today_uploads = getattr(acc, 'today_uploads', 0) or 0
                total_uploads = getattr(acc, 'total_uploads', 0) or 0
                last_upload_date = getattr(acc, 'last_upload_date', 'Never')
                logger.debug(f"   {acc.session_name}: {today_uploads} today, {total_uploads} total, last: {last_upload_date}")
        
        return {
            "configured_count": len(configured_account_names),
            "database_count": len(db_account_names),
            "missing_accounts": list(missing_accounts),
            "extra_accounts": list(extra_accounts),
            "needs_initialization": len(missing_accounts) > 0
        }
        
    except Exception as e:
        logger.error(f"❌ Error diagnosing account distribution: {e}")
        return {
            "error": str(e),
            "needs_initialization": True
        }

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
    max_retries = 3
    for attempt in range(max_retries):
        try:
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
            
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"Database error in select_upload_account (attempt {attempt + 1}): {e}")
                await asyncio.sleep(1 * (attempt + 1))  # Exponential backoff
                continue
            else:
                logger.error(f"Database error in select_upload_account after {max_retries} attempts: {e}")
                # Fallback to first account
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

    # Set rotation flag to prevent new uploads
    _rotation_in_progress = True

    try:
        # Wait for ongoing uploads to complete
        all_completed = await wait_for_ongoing_uploads()
        
        if not all_completed:
            logger.warning("⚠️ Some uploads didn't complete before timeout, proceeding with rotation anyway")
        
        # Perform the actual IP rotation
        async with aiohttp.ClientSession() as session:
            if PROXY_CONFIG["rotation_method"].upper() == "POST":
                async with session.post(
                    PROXY_CONFIG["rotation_url"],
                    headers=PROXY_CONFIG["rotation_headers"],
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        logger.debug("✅ Proxy rotation request successful")
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
                        logger.debug("✅ Proxy rotation request successful")
                        _last_ip_rotation = current_time
                    else:
                        logger.warning(f"⚠️ Proxy rotation failed with status {response.status}")
                        logger.warning(f"   Response: {await response.text()}")
        
        # Wait a moment for the new IP to be active
        await asyncio.sleep(5)
        
        # Get new IP after rotation
        new_ip = await get_current_ip()
        
        # Log IP change details
        await log_ip_change(old_ip, new_ip)
        
        # Update global IP tracker
        _current_ip = new_ip
        
        # Clear rate limit events after successful rotation
        clear_rate_limit_events()
        
    except Exception as e:
        logger.error(f"❌ Proxy rotation error: {e}")
        logger.error(f"   Error type: {type(e).__name__}")
    finally:
        # Clear rotation flag to allow new uploads
        _rotation_in_progress = False

async def rotate_proxy_ip_immediate(reason: str = "emergency"):
    """Rotate the proxy IP address immediately without waiting for uploads to complete"""
    global _last_ip_rotation, _current_ip, _rotation_lock
    
    if not PROXY_CONFIG["enabled"] or not PROXY_CONFIG["rotation_url"]:
        logger.info("🔄 Immediate proxy rotation skipped - proxy not enabled or no rotation URL")
        return
    
    current_time = time.time()
    # Prevent too frequent rotations (use configurable cooldown)
    cooldown_seconds = PROXY_CONFIG.get("immediate_rotation_cooldown", 30)
    if current_time - _last_ip_rotation < cooldown_seconds:
        await asyncio.sleep(current_time - _last_ip_rotation)
        logger.info(f"🔄Sleeping for {current_time - _last_ip_rotation}sec. Frequent rotation detected")

    if _rotation_lock.locked():
        logger.debug("🔄 Immediate proxy rotation already in progress (locked)")
        return
    
    async with _rotation_lock:
        # Get current IP before rotation
        old_ip = await get_current_ip()

        logger.warning(f"🚨 EMERGENCY: Immediate proxy rotation triggered due to: {reason}")
        logger.warning(f"   Bypassing upload wait - rotation will proceed immediately")

        try:
            # Perform the actual IP rotation immediately
            async with aiohttp.ClientSession() as session:
                if PROXY_CONFIG["rotation_method"].upper() == "POST":
                    async with session.post(
                        PROXY_CONFIG["rotation_url"],
                        headers=PROXY_CONFIG["rotation_headers"],
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as response:
                        if response.status == 200:
                            logger.debug("✅ Immediate proxy rotation request successful")
                            _last_ip_rotation = current_time
                        elif response.status == 429:
                            logger.error(f"❌ Proxy rotation rate limited (429) - rotation service overloaded")
                            logger.error(f"   Response: {await response.text()}")
                            # Don't update _last_ip_rotation to allow retry after cooldown
                            return
                        else:
                            logger.warning(f"⚠️ Immediate proxy rotation failed with status {response.status}")
                            logger.warning(f"   Response: {await response.text()}")
                            # Don't update _last_ip_rotation for non-429 errors
                            return
                else:
                    async with session.get(
                        PROXY_CONFIG["rotation_url"],
                        headers=PROXY_CONFIG["rotation_headers"],
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as response:
                        if response.status == 200:
                            logger.debug("✅ Immediate proxy rotation request successful")
                            _last_ip_rotation = current_time
                        elif response.status == 429:
                            logger.error(f"❌ Proxy rotation rate limited (429) - rotation service overloaded")
                            logger.error(f"   Response: {await response.text()}")
                            # Don't update _last_ip_rotation to allow retry after cooldown
                            return
                        else:
                            logger.warning(f"⚠️ Immediate proxy rotation failed with status {response.status}")
                            logger.warning(f"   Response: {await response.text()}")
                            # Don't update _last_ip_rotation for non-429 errors
                            return

            # Wait a moment for the new IP to be active
            await asyncio.sleep(5)

            # Get new IP after rotation
            new_ip = await get_current_ip()

            # Log IP change details
            await log_ip_change(old_ip, new_ip)

            # Update global IP tracker
            _current_ip = new_ip

            # Clear rate limit events after successful rotation
            clear_rate_limit_events()

            logger.info(f"✅ Immediate proxy rotation completed successfully due to: {reason}")

        except Exception as e:
            logger.error(f"❌ Immediate proxy rotation error: {e}")
            logger.error(f"   Error type: {type(e).__name__}")
            logger.error(f"   Reason: {reason}")
            # Don't update _last_ip_rotation on exceptions to allow retry

def should_rotate_ip():
    """Check if we should rotate IP based on upload count or rate limiting signals"""
    global _upload_counter
    
    if not PROXY_CONFIG["enabled"]:
        return False
    
    # Check smart rotation first (if enabled)
    if PROXY_CONFIG.get("smart_rotation_enabled", True):
        rate_limit_stats = get_rate_limit_stats()
        significant_events = rate_limit_stats["significant_events"]
        
        if significant_events >= _max_rate_limit_events:
            logger.warning(f"🚨 Smart IP rotation triggered: {significant_events} significant rate limit events")
            return True
    
    # Fallback to upload counter-based rotation
    should_rotate = _upload_counter >= PROXY_CONFIG["rotation_interval"]
    
    if should_rotate:
        logger.info(f"🔄 IP rotation triggered after {PROXY_CONFIG['rotation_interval']} uploads")
        logger.info(f"   Upload counter reset to 0")
    else:
        # Log current status for debugging
        rate_limit_stats = get_rate_limit_stats()
        logger.debug(f"📊 Upload counter: {_upload_counter}/{PROXY_CONFIG['rotation_interval']} (rotation at {PROXY_CONFIG['rotation_interval']})")
        if rate_limit_stats["total_events"] > 0:
            logger.debug(f"📊 Rate limit events: {rate_limit_stats['significant_events']}/{_max_rate_limit_events} significant")
    
    return should_rotate

def increment_upload_counter():
    """Increment upload counter - call this once per actual upload"""
    global _upload_counter
    
    if not PROXY_CONFIG["enabled"]:
        return
    
    _upload_counter += 1
    logger.debug(f"📊 Upload counter incremented to: {_upload_counter}/{PROXY_CONFIG['rotation_interval']}")
    
    # Check if we should rotate after incrementing
    if _upload_counter >= PROXY_CONFIG["rotation_interval"]:
        _upload_counter = 0
        logger.info(f"🔄 Upload counter reset to 0 after reaching rotation threshold")

def clear_rate_limit_events():
    """Clear rate limit events after successful IP rotation"""
    global _rate_limit_events
    
    if _rate_limit_events:
        logger.info(f"🧹 Clearing {len(_rate_limit_events)} rate limit events after IP rotation")
        _rate_limit_events.clear()

def track_rate_limit_event(wait_seconds: int):
    """Track a rate limiting event from Telegram"""
    global _rate_limit_events
    
    if not PROXY_CONFIG["enabled"] or not PROXY_CONFIG.get("smart_rotation_enabled", True):
        return
    
    current_time = time.time()
    
    # Add the rate limit event
    _rate_limit_events.append({
        "timestamp": current_time,
        "wait_seconds": wait_seconds
    })
    
    # Keep only events within the detection window
    cutoff_time = current_time - (_rate_limit_detection_window * 60)  # Convert to seconds
    _rate_limit_events = [event for event in _rate_limit_events if event["timestamp"] > cutoff_time]
    
    # Log rate limit event
    logger.info(f"⏰ Rate limit event detected: {wait_seconds}s wait")
    logger.info(f"   Recent rate limit events: {len(_rate_limit_events)} in last {_rate_limit_detection_window} minutes")
    
    # Check if we should trigger rotation
    significant_events = [event for event in _rate_limit_events if event["wait_seconds"] >= _rate_limit_wait_threshold]
    
    if len(significant_events) >= _max_rate_limit_events:
        logger.warning(f"🚨 Smart IP rotation triggered: {len(significant_events)} significant rate limit events detected")
        return True
    
    return False

def get_rate_limit_stats():
    """Get current rate limiting statistics"""
    global _rate_limit_events
    
    if not _rate_limit_events:
        return {
            "total_events": 0,
            "significant_events": 0,
            "max_wait_time": 0,
            "average_wait_time": 0,
            "events_in_window": 0
        }
    
    significant_events = [event for event in _rate_limit_events if event["wait_seconds"] >= _rate_limit_wait_threshold]
    wait_times = [event["wait_seconds"] for event in _rate_limit_events]
    
    return {
        "total_events": len(_rate_limit_events),
        "significant_events": len(significant_events),
        "max_wait_time": max(wait_times) if wait_times else 0,
        "average_wait_time": sum(wait_times) / len(wait_times) if wait_times else 0,
        "events_in_window": len(_rate_limit_events)
    }

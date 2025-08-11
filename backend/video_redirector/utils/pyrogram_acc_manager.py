import os
import json
import asyncio
import time
from pathlib import Path
import sqlite3
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
from backend.video_redirector.utils.notify_admin import notify_admin

async def notify_admin_async(message: str):
    """Non-blocking notification with error handling"""
    try:
        await notify_admin(message)
    except Exception as e:
        logger.error(f"Failed to send admin notification: {e}")

logger = logging.getLogger(__name__)

MULTI_ACCOUNT_CONFIG_PATH = Path('/app/backend/video_redirector/utils/upload_accounts.json')
SESSION_DIR = "/app/backend/session_files"

# Per-account rate limit tracking
_account_rate_limit_events = {}  # Track per account instead of global

# Global upload management
_active_uploads = set()  # Track active upload task IDs
_account_upload_counters = {}  # Track concurrent uploads per account
MAX_CONCURRENT_UPLOADS_PER_ACCOUNT = 1  # Maximum concurrent uploads per account

# Quarantine configuration for session DB issues
ACCOUNT_QUARANTINE_SECONDS = 5 * 60  # 5 minutes

# 🔒 Global lock for account selection to prevent race conditions
# This ensures that only one task can select an account at a time,
# preventing race conditions where multiple tasks could select the same account
_account_selection_lock = asyncio.Lock()

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

class AllProxiesExhaustedError(Exception):
    """Raised when all proxies in an account's pool have failed"""
    pass

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
        self.last_client_creation = 0
        self.client_creation_cooldown = 15
        # Account-level quarantine for session file issues (e.g., SQLite locked)
        self.quarantine_until = 0.0
        
        # New proxy pool management
        self.proxy_pool = config.get("proxy_pool", [])
        self.proxy_usage_count = {i: 0 for i in range(len(self.proxy_pool))}
        self.proxy_success_count = {i: 0 for i in range(len(self.proxy_pool))}
        self.proxy_failure_count = {i: 0 for i in range(len(self.proxy_pool))}
        self.proxy_consecutive_failures = {i: 0 for i in range(len(self.proxy_pool))}  # Track consecutive failures
        self.proxy_cooldowns = {}  # Temporary cooldowns
        self.blacklisted_proxies = set()  # Permanent blacklist
        self.current_proxy_index = 0
        self.connection_attempts = 0  # Track connection attempts for current proxy
        
        # Configurable settings
        proxy_settings = config.get("proxy_settings", {})
        self.cooldown_hours = proxy_settings.get("cooldown_hours", 2)
        self.max_consecutive_failures = proxy_settings.get("max_consecutive_failures", 3)
        self.connection_retry_limit = proxy_settings.get("connection_retry_limit", 3)
        
        logger.info(f"🔧 [{self.session_name}] Initialized with {len(self.proxy_pool)} proxies")

    def is_quarantined(self) -> bool:
        return time.time() < self.quarantine_until

    def quarantine(self, reason: str, seconds: int = ACCOUNT_QUARANTINE_SECONDS):
        self.quarantine_until = time.time() + seconds
        cooldown_until = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.quarantine_until))
        logger.warning(f"🚧 [{self.session_name}] Account quarantined for {seconds}s (until {cooldown_until}) due to: {reason}")
        asyncio.create_task(notify_admin_async(
            f"🚧 Account {self.session_name} quarantined for {seconds}s due to: {reason}\n"
            f"Action: investigate or regenerate session file"
        ))

    def select_best_proxy(self) -> int:
        """Select proxy with lowest usage count, then highest success rate"""
        available_proxies = []
        
        for i in range(len(self.proxy_pool)):
            # Skip blacklisted proxies
            if i in self.blacklisted_proxies:
                continue
                
            # Skip proxies in cooldown
            if i in self.proxy_cooldowns:
                cooldown_until = self.proxy_cooldowns[i]
                if time.time() < cooldown_until:
                    continue
                else:
                    del self.proxy_cooldowns[i]
                    logger.info(f"🔄 [{self.session_name}] Proxy {i} cooldown expired")
            
            # Calculate success rate
            total_attempts = self.proxy_success_count[i] + self.proxy_failure_count[i]
            success_rate = self.proxy_success_count[i] / total_attempts if total_attempts > 0 else 0.5
            
            available_proxies.append({
                'index': i,
                'usage_count': self.proxy_usage_count[i],
                'success_rate': success_rate,
                'total_attempts': total_attempts
            })
        
        if not available_proxies:
            raise AllProxiesExhaustedError(f"Account {self.session_name}: All proxies unavailable")
        
        # Sort by usage count first, then by success rate
        available_proxies.sort(key=lambda x: (x['usage_count'], -x['success_rate']))
        selected = available_proxies[0]
        
        proxy_key = f"{self.proxy_pool[selected['index']]['ip']}:{self.proxy_pool[selected['index']]['port']}"
        logger.info(f"🎯 [{self.session_name}] Selected proxy: {proxy_key}")
        logger.info(f"   Usage: {selected['usage_count']}, Success rate: {selected['success_rate']:.1%}")
        
        return selected['index']

    def mark_proxy_success(self, proxy_index: int):
        """Mark proxy as successful - reset consecutive failures"""
        self.proxy_success_count[proxy_index] += 1
        self.proxy_usage_count[proxy_index] += 1
        self.proxy_consecutive_failures[proxy_index] = 0  # Reset consecutive failures
        self.connection_attempts = 0  # Reset connection attempts
        
        proxy_key = f"{self.proxy_pool[proxy_index]['ip']}:{self.proxy_pool[proxy_index]['port']}"
        logger.info(f"🟢 [{self.session_name}] Proxy {proxy_key} successful (consecutive failures reset)")

    def mark_proxy_failure(self, proxy_index: int, reason: str, is_significant_event: bool = False):
        """Mark proxy as failed - handle cooldown/blacklist logic"""
        self.proxy_failure_count[proxy_index] += 1
        self.proxy_consecutive_failures[proxy_index] += 1  # Increment consecutive failures
        proxy_key = f"{self.proxy_pool[proxy_index]['ip']}:{self.proxy_pool[proxy_index]['port']}"
        
        # Check if this is a significant event (rate limit, network issue, timeout)
        if is_significant_event:
            # Immediate cooldown for significant events
            self._put_proxy_in_cooldown(proxy_index, reason, "significant_event")
            logger.warning(f"🔄 [{self.session_name}] Proxy {proxy_key} in cooldown: {reason}")
            # Notify admin about proxy rotation
            asyncio.create_task(notify_admin(f"🔄 [{self.session_name}] Proxy {proxy_key} rotated due to: {reason}"))
        else:
            # Increment connection attempts for regular failures
            self.connection_attempts += 1
            
            if self.connection_attempts >= self.connection_retry_limit:
                # Max connection attempts reached
                self._put_proxy_in_cooldown(proxy_index, reason, "connection_failure")
                logger.warning(f"🔄 [{self.session_name}] Proxy {proxy_key} in cooldown after {self.connection_retry_limit} connection failures")
                # Notify admin about proxy rotation
                asyncio.create_task(notify_admin(f"🔄 [{self.session_name}] Proxy {proxy_key} rotated due to connection failures"))
                self.connection_attempts = 0
            else:
                logger.warning(f"⚠️ [{self.session_name}] Proxy {proxy_key} connection attempt {self.connection_attempts}/{self.connection_retry_limit}")
        
        # Check for permanent blacklist using ACTUAL consecutive failures
        consecutive_failures = self.proxy_consecutive_failures[proxy_index]
        
        if consecutive_failures >= self.max_consecutive_failures:
            self._blacklist_proxy(proxy_index, reason)

    def _put_proxy_in_cooldown(self, proxy_index: int, reason: str, failure_type: str):
        """Put proxy in temporary cooldown"""
        # Don't put already blacklisted proxies in cooldown
        if proxy_index in self.blacklisted_proxies:
            return
            
        cooldown_until = time.time() + (self.cooldown_hours * 3600)
        self.proxy_cooldowns[proxy_index] = cooldown_until
        
        # Check if we need to notify admin about low proxy count
        # Count proxies that are neither blacklisted nor in cooldown
        unavailable_proxies = self.blacklisted_proxies.union(set(self.proxy_cooldowns.keys()))
        available_count = len(self.proxy_pool) - len(unavailable_proxies)
        if available_count <= 1:
            self.notify_admin_low_proxy_count(available_count, reason)

    def _blacklist_proxy(self, proxy_index: int, reason: str):
        """Permanently blacklist a proxy"""
        # Check if already blacklisted to prevent duplicate notifications
        if proxy_index in self.blacklisted_proxies:
            logger.debug(f"⏭️ [{self.session_name}] Proxy index {proxy_index} already blacklisted, skipping")
            return
            
        self.blacklisted_proxies.add(proxy_index)
        
        # Remove from cooldowns if present (blacklisted proxies don't need cooldowns)
        if proxy_index in self.proxy_cooldowns:
            del self.proxy_cooldowns[proxy_index]
        
        proxy_key = f"{self.proxy_pool[proxy_index]['ip']}:{self.proxy_pool[proxy_index]['port']}"
        logger.error(f"🔴 [{self.session_name}] Proxy {proxy_key} permanently blacklisted: {reason}")
        
        # Notify admin with full details
        self.notify_admin_proxy_blacklisted(proxy_index, reason)
        
        # Check if all proxies are now blacklisted
        if len(self.blacklisted_proxies) >= len(self.proxy_pool):
            raise AllProxiesExhaustedError(f"Account {self.session_name}: All proxies blacklisted")

    def notify_admin_proxy_blacklisted(self, proxy_index: int, reason: str):
        """Notify admin about blacklisted proxy with full details"""
        proxy = self.proxy_pool[proxy_index]
        proxy_key = f"{proxy['ip']}:{proxy['port']}"
        
        total_attempts = self.proxy_success_count[proxy_index] + self.proxy_failure_count[proxy_index]
        success_rate = self.proxy_success_count[proxy_index] / total_attempts if total_attempts > 0 else 0
        
        message = f"""
‼️‼️‼️ Proxy Blacklisted Alert:
Account: {self.session_name}
Proxy: {proxy_key}
Reason: {reason}
Total attempts: {total_attempts}
Success rate: {success_rate:.1%}
Usage count: {self.proxy_usage_count[proxy_index]}
Total failure count: {self.proxy_failure_count[proxy_index]}
Consecutive failures: {self.proxy_consecutive_failures[proxy_index]}

Action required: Investigate proxy or replace with new one‼️‼️‼️
        """
        logger.error(message)
        asyncio.create_task(notify_admin_async(message))

    def notify_admin_low_proxy_count(self, available_count: int, reason: str):
        """Notify admin when proxy pool is running low"""
        message = f"""
⚠️ Low Proxy Count Alert:
Account: {self.session_name}
Available proxies: {available_count}/{len(self.proxy_pool)}
Last rotation reason: {reason}
Action: Consider adding more proxies or investigating issues
        """
        logger.warning(message)
        asyncio.create_task(notify_admin_async(message))

    async def stop_client(self):
        # Serialize stop to avoid races with start
        async with self.lock:
            if self.client is not None:
                try:
                    await self.client.stop()
                    logger.info(f"Stopped client for account {self.session_name}")
                except Exception as e:
                    logger.warning(f"Error stopping client for {self.session_name}: {e}")
                finally:
                    self.client = None

    async def is_client_healthy(self):
        """Check if the client is healthy and can be used"""
        if self.client is None:
            return False
        try:
            await self.client.get_me()
            return True
        except Exception as e:
            logger.debug(f"Client health check failed for {self.session_name}: {type(e).__name__}: {e}")
            return False
    
    def has_available_proxies(self) -> bool:
        """Check if this account has any available proxies"""
        if not self.proxy_pool:
            return False
        
        current_time = time.time()
        for i in range(len(self.proxy_pool)):
            # Skip blacklisted proxies
            if i in self.blacklisted_proxies:
                continue
                
            # Skip proxies in cooldown
            if i in self.proxy_cooldowns:
                cooldown_until = self.proxy_cooldowns[i]
                if current_time < cooldown_until:
                    continue
            
            # Found at least one available proxy
            return True
        
        return False

    async def ensure_client_ready_with_retry(self):
        """Ensure client is ready with connection retry logic"""
        rotation_done = False
        while True:
            for attempt in range(self.connection_retry_limit):
                try:
                    client = await self.ensure_client_ready()
                    if client is not None:
                        # Connection successful
                        self.connection_attempts = 0
                        return client
                    else:
                        # Client creation failed
                        self.mark_proxy_failure(self.current_proxy_index, "Client creation failed", is_significant_event=False)
                except Exception as e:
                    # Connection error
                    self.mark_proxy_failure(self.current_proxy_index, f"Connection error: {type(e).__name__}", is_significant_event=False)
                    if attempt < self.connection_retry_limit - 1:
                        logger.warning(f"⚠️ [{self.session_name}] Connection attempt {attempt + 1} failed, retrying...")
                        await asyncio.sleep(2)
                    else:
                        logger.error(f"❌ [{self.session_name}] All connection attempts failed")

            # If we've already rotated once, break and decide based on availability
            if rotation_done:
                break

            # Try a single proxy rotation, then attempt again
            try:
                await self.rotate_proxy("Connection retry limit exceeded")
                rotation_done = True
                continue
            except AllProxiesExhaustedError:
                logger.error(f"❌ [{self.session_name}] All proxies exhausted after connection retries")
                raise AllProxiesExhaustedError(f"Account {self.session_name}: All proxies exhausted")

        # After retries (and at most one rotation), if no client, decide outcome
        if not self.has_available_proxies():
            logger.error(f"❌ [{self.session_name}] No available proxies after retries")
            raise AllProxiesExhaustedError(f"Account {self.session_name}: All proxies exhausted")
        return None

    async def ensure_client_ready(self):
        """Ensure client is ready for use, start if needed"""
        async with self.lock:
            current_time = time.time()

            # Quarantine check
            if self.is_quarantined():
                remaining = int(self.quarantine_until - current_time)
                logger.warning(f"🚧 [{self.session_name}] In quarantine for {remaining}s, skipping client creation")
                return None

            # First check if we have any available proxies at all
            if not self.has_available_proxies():
                logger.error(f"❌ [{self.session_name}] No available proxies for client creation")
                raise AllProxiesExhaustedError(f"Account {self.session_name}: No available proxies")

            # Check if we're in cooldown period
            if (self.client is None and 
                current_time - self.last_client_creation < self.client_creation_cooldown):
                remaining_cooldown = self.client_creation_cooldown - (current_time - self.last_client_creation)
                logger.warning(f"Account {self.session_name} in cooldown, waiting {remaining_cooldown:.1f}s...")
                await asyncio.sleep(remaining_cooldown)

            if self.client is None:
                session_path = os.path.join(str(SESSION_DIR), str(self.session_name))

                # Check session file
                session_file = f"{session_path}.session"
                logger.info(f"🔍 [{self.session_name}] Checking session file: {session_file}")

                if not os.path.exists(session_file):
                    logger.error(f"❌ [{self.session_name}] Session file not found: {session_file}")
                    return None

                # Check session file size
                try:
                    session_size = os.path.getsize(session_file)
                    if session_size == 0:
                        logger.error(f"❌ [{self.session_name}] Session file is empty: {session_file}")
                        return None
                except Exception as e:
                    logger.error(f"❌ [{self.session_name}] Error checking session file: {e}")
                    return None

                # Select best proxy for this account
                try:
                    self.current_proxy_index = self.select_best_proxy()
                except AllProxiesExhaustedError as e:
                    logger.error(f"❌ [{self.session_name}] {e}")
                    return None

                # Configure proxy
                proxy_config = None
                if self.proxy_pool:
                    proxy_info = self.proxy_pool[self.current_proxy_index]
                    proxy_config = {
                        "scheme": proxy_info.get("type", "socks5"),
                        "hostname": proxy_info["ip"],
                        "port": proxy_info["port"],
                        "username": proxy_info["username"],
                        "password": proxy_info["password"],
                    }

                    logger.info(f"🌐 [{self.session_name}] Using proxy: {proxy_info['ip']}:{proxy_info['port']}")

                # Create client
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
                        return None

                    # Prevent indefinite hang on bad proxies during client start
                    try:
                        await asyncio.wait_for(self.client.start(), timeout=30)
                    except asyncio.TimeoutError:
                        self.client = None
                        logger.error(f"❌ [{self.session_name}] Client.start() timed out")
                        return None
                    logger.info(f"✅ [{self.session_name}] Client started successfully")

                    self.last_client_creation = current_time

                    # Reset rate-limit tracking when (re)starting a client with a freshly
                    # selected proxy so previous proxy's events don't spill over
                    try:
                        reset_rate_limit_events_for_account(self.session_name)
                    except Exception as _e:
                        logger.debug(f"Failed to reset rate-limit events for {self.session_name}: {_e}")

                except sqlite3.OperationalError as e:
                    # Session SQLite contention — quarantine account, do not penalize proxy
                    if "locked" in str(e).lower():
                        self.client = None
                        self.quarantine("Session DB is locked")
                        return None
                    logger.error(f"❌ [{self.session_name}] sqlite3 OperationalError: {e}")
                    self.client = None
                    return None
                except Exception as e:
                    err_text = f"{type(e).__name__}: {e}"
                    if "OperationalError" in err_text and "locked" in err_text.lower():
                        # Handle wrapped OperationalError
                        self.client = None
                        self.quarantine("Session DB is locked (wrapped)")
                        return None
                    logger.error(f"❌ [{self.session_name}] Failed to create/start client: {err_text}")
                    self.client = None
                    return None

            self.last_used = time.time()
            return self.client

    async def rotate_proxy(self, reason: str) -> bool:
        """Rotate to next available proxy"""
        try:
            # 1. Mark current proxy as failed
            self.mark_proxy_failure(self.current_proxy_index, reason, is_significant_event=True)
            
            # 2. Stop current client FIRST to prevent reuse of old client
            await self.stop_client()
            
            # 3. Select new proxy (this can raise AllProxiesExhaustedError)
            try:
                self.current_proxy_index = self.select_best_proxy()
            except AllProxiesExhaustedError:
                # No proxies available - raise immediately
                raise
            
            # 4. Create client with new proxy
            client = await self.ensure_client_ready()
            
            if client is not None:
                # Success - reset events and return True
                reset_rate_limit_events_for_account(self.session_name)
                logger.info(f"✅ [{self.session_name}] Successfully rotated to new proxy")
                return True
            else:
                # Client creation failed - mark proxy as failed and raise exception
                self.mark_proxy_failure(self.current_proxy_index, "Client creation failed", is_significant_event=True)
                raise AllProxiesExhaustedError(f"Account {self.session_name}: All proxies unavailable")
            
        except AllProxiesExhaustedError:
            await self.notify_admin_all_proxies_failed(reason)
            raise

    async def notify_admin_all_proxies_failed(self, reason: str):
        """Notify admin when all proxies for an account are exhausted"""
        message = f"""
🔴 CRITICAL: All Proxies Exhausted
Account: {self.session_name}
Total proxies: {len(self.proxy_pool)}
Final reason: {reason}
Action required: Add new proxies or investigate account issues
        """
        logger.error(message)
        await notify_admin(message)

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

def release_account_reservation(account_session_name: str):
    """Release the account reservation (decrement counter)"""
    global _account_upload_counters
    
    try:
        if account_session_name in _account_upload_counters:
            _account_upload_counters[account_session_name] = max(0, _account_upload_counters[account_session_name] - 1)
            logger.info(f"🔓 [{account_session_name}] Released account reservation (active: {_account_upload_counters[account_session_name]})")
        else:
            logger.warning(f"⚠️ [{account_session_name}] Attempted to release reservation for account not in counters")
    except Exception as e:
        logger.error(f"❌ [{account_session_name}] Error releasing account reservation: {e}")

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
    """
    Select the best available upload account with atomic reservation to prevent race conditions.
    
    This function:
    1. Uses a global lock to prevent race conditions during account selection
    2. Atomically reserves the selected account by incrementing its counter
    3. Returns the account index and account object
    4. Ensures truly non-blocking concurrent uploads across different accounts
    
    The caller is responsible for calling release_account_reservation() when done.
    """
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # 🔒 Global lock prevents selection race conditions
            async with _account_selection_lock:
                # First try to get least used accounts
                least_used = await get_least_used_accounts(db)
                
                # Check least used accounts first - prioritize non-uploading accounts
                for idx in least_used:
                    acc = UPLOAD_ACCOUNT_POOL[idx]
                    
                    # Skip accounts without available proxies
                    if not acc.has_available_proxies():
                        logger.debug(f"⏭️ Skipping account {acc.session_name}: no available proxies")
                        continue
                    
                    # Check if account is currently uploading using the counter system
                    is_currently_uploading = _account_upload_counters.get(acc.session_name, 0) > 0
                    
                    if not is_currently_uploading:
                        # Check if account was recently used (within last 30 seconds)
                        if time.time() - acc.last_used > 30:
                            # Only check health if client exists, don't create new connections
                            if acc.client is None or await acc.is_client_healthy():
                                # 🔒 ATOMICALLY reserve this account
                                _account_upload_counters[acc.session_name] = _account_upload_counters.get(acc.session_name, 0) + 1
                                logger.info(f"✅ Selected least used account {acc.session_name} (not currently uploading)")
                                return idx, acc
                            else:
                                # Client is unhealthy, stop it and continue
                                logger.warning(f"Account {acc.session_name} has unhealthy client, stopping it")
                                await acc.stop_client()
                
                # If no non-uploading least used accounts available, try any non-uploading account
                for idx, acc in enumerate(UPLOAD_ACCOUNT_POOL):
                    # Skip accounts without available proxies
                    if not acc.has_available_proxies():
                        logger.debug(f"⏭️ Skipping account {acc.session_name}: no available proxies")
                        continue
                    
                    # Check if account is currently uploading using the counter system
                    is_currently_uploading = _account_upload_counters.get(acc.session_name, 0) > 0
                    
                    if not is_currently_uploading:
                        # Check if account was recently used (within last 30 seconds)
                        if time.time() - acc.last_used > 30:
                            # Only check health if client exists, don't create new connections
                            if acc.client is None or await acc.is_client_healthy():
                                # 🔒 ATOMICALLY reserve this account
                                _account_upload_counters[acc.session_name] = _account_upload_counters.get(acc.session_name, 0) + 1
                                logger.info(f"✅ Selected available account {acc.session_name} (not currently uploading)")
                                return idx, acc
                            else:
                                # Client is unhealthy, stop it and continue
                                logger.warning(f"Account {acc.session_name} has unhealthy client, stopping it")
                                await acc.stop_client()
                
                # Before queuing, try any non-uploading account (even if recently used) to maximize parallelism
                logger.info("No non-uploading accounts after cooldown available, trying any non-uploading account...")
                for idx, acc in enumerate(UPLOAD_ACCOUNT_POOL):
                    # Check if account is currently uploading using the counter system
                    is_currently_uploading = _account_upload_counters.get(acc.session_name, 0) > 0
                    
                    if not is_currently_uploading:
                        # Skip the 30-second cooldown check - use any non-uploading account
                        # Only check health if client exists, don't create new connections
                        if acc.client is None or await acc.is_client_healthy():
                            # 🔒 ATOMICALLY reserve this account
                            _account_upload_counters[acc.session_name] = _account_upload_counters.get(acc.session_name, 0) + 1
                            logger.info(f"✅ Selected non-uploading account {acc.session_name} (bypassing cooldown)")
                            return idx, acc
                        else:
                            # Client is unhealthy, stop it and continue
                            logger.warning(f"Account {acc.session_name} has unhealthy client, stopping it")
                            await acc.stop_client()
                
                # If all accounts are currently uploading, find the one with least uploads and queue there
                logger.warning("All upload accounts are currently uploading, selecting least used for queuing...")
                
                # Among currently uploading accounts, select the one with least uploads
                for idx in least_used:
                    acc = UPLOAD_ACCOUNT_POOL[idx]
                    # Check if account was recently used (within last 30 seconds)
                    if time.time() - acc.last_used > 30:
                        # Only check health if client exists, don't create new connections
                        if acc.client is None or await acc.is_client_healthy():
                            # 🔒 ATOMICALLY reserve this account
                            _account_upload_counters[acc.session_name] = _account_upload_counters.get(acc.session_name, 0) + 1
                            logger.info(f"⏳ Selected least used account {acc.session_name} for queuing (currently uploading)")
                            return idx, acc
                        else:
                            # Client is unhealthy, stop it and continue
                            logger.warning(f"Account {acc.session_name} has unhealthy client, stopping it")
                            await acc.stop_client()
                
                # If all least used accounts are unhealthy, try any account
                for idx, acc in enumerate(UPLOAD_ACCOUNT_POOL):
                    # Check if account was recently used (within last 30 seconds)
                    if time.time() - acc.last_used > 30:
                        # Only check health if client exists, don't create new connections
                        if acc.client is None or await acc.is_client_healthy():
                            # 🔒 ATOMICALLY reserve this account
                            _account_upload_counters[acc.session_name] = _account_upload_counters.get(acc.session_name, 0) + 1
                            logger.info(f"⏳ Selected available account {acc.session_name} for queuing (currently uploading)")
                            return idx, acc
                        else:
                            # Client is unhealthy, stop it and continue
                            logger.warning(f"Account {acc.session_name} has unhealthy client, stopping it")
                            await acc.stop_client()
                
                # If all accounts are unhealthy or recently used, wait a bit and return the first one
                logger.warning("All upload accounts are unhealthy or recently used, waiting...")
                await asyncio.sleep(10)  # Wait 10 seconds
                # 🔒 ATOMICALLY reserve the first account
                _account_upload_counters[UPLOAD_ACCOUNT_POOL[0].session_name] = _account_upload_counters.get(UPLOAD_ACCOUNT_POOL[0].session_name, 0) + 1
                return 0, UPLOAD_ACCOUNT_POOL[0]
            
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"Database error in select_upload_account (attempt {attempt + 1}): {e}")
                await asyncio.sleep(1 * (attempt + 1))  # Exponential backoff
                continue
            else:
                 logger.error(f"Database error in select_upload_account after {max_retries} attempts: {e}")
                 raise Exception(f"Failed to select upload account after {max_retries} attempts: {e}")

async def idle_client_cleanup():
    while True:
        now = time.time()
        for account in UPLOAD_ACCOUNT_POOL:
            if account.client is not None and (now - account.last_used) > IDLE_TIMEOUT_SECONDS:
                await account.stop_client()
        await asyncio.sleep(300)  # Check every 5 minutes

# --- Per-account rate limit tracking functions ---

def reset_rate_limit_events_for_account(account_session_name: str):
    """Reset rate limit event counter after successful proxy rotation"""
    if account_session_name in _account_rate_limit_events:
        old_count = len(_account_rate_limit_events[account_session_name])
        _account_rate_limit_events[account_session_name] = []
        logger.info(f"🔄 [{account_session_name}] Rate limit events reset after proxy rotation (cleared {old_count} events)")
    else:
        logger.info(f"🔄 [{account_session_name}] Rate limit events reset (no events to clear)")

def track_rate_limit_event_per_account(account_session_name: str, wait_seconds: int):
    """Track rate limit events per account (adapted from current global tracking)"""
    if account_session_name not in _account_rate_limit_events:
        _account_rate_limit_events[account_session_name] = []
    
    current_time = time.time()
    
    # Add the rate limit event
    _account_rate_limit_events[account_session_name].append({
        "timestamp": current_time,
        "wait_seconds": wait_seconds
    })
    
    # Keep only events within detection window
    cutoff_time = current_time - (PROXY_CONFIG.get("rate_limit_detection_window", 10) * 60)
    _account_rate_limit_events[account_session_name] = [
        event for event in _account_rate_limit_events[account_session_name] 
        if event["timestamp"] > cutoff_time
    ]
    
    # Check if we should trigger rotation for this specific account
    significant_events = [
        event for event in _account_rate_limit_events[account_session_name]
        if event["wait_seconds"] >= PROXY_CONFIG.get("rate_limit_wait_threshold", 7)
    ]
    
    if len(significant_events) >= PROXY_CONFIG.get("max_rate_limit_events", 3):
        logger.warning(f"🚨 [{account_session_name}] Smart rotation triggered: {len(significant_events)} significant events")
        return True
    
    return False

def get_rate_limit_stats_per_account(account_session_name: str):
    """Get current rate limiting statistics for specific account"""
    if account_session_name not in _account_rate_limit_events:
        return {
            "total_events": 0,
            "significant_events": 0,
            "max_wait_time": 0,
            "average_wait_time": 0,
            "events_in_window": 0
        }
    
    events = _account_rate_limit_events[account_session_name]
    significant_events = [
        event for event in events 
        if event["wait_seconds"] >= PROXY_CONFIG.get("rate_limit_wait_threshold", 7)
    ]
    wait_times = [event["wait_seconds"] for event in events]
    
    return {
        "total_events": len(events),
        "significant_events": len(significant_events),
        "max_wait_time": max(wait_times) if wait_times else 0,
        "average_wait_time": sum(wait_times) / len(wait_times) if wait_times else 0,
        "events_in_window": len(events)
    }

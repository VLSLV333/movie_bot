import re
import logging
import asyncio
import time
from backend.video_redirector.utils.pyrogram_acc_manager import (
    track_rate_limit_event_per_account, 
    UPLOAD_ACCOUNT_POOL,
    get_rate_limit_stats_per_account
)
from backend.video_redirector.utils.notify_admin import notify_admin

logger = logging.getLogger(__name__)

# Regex patterns to match Pyrogram messages
RATE_LIMIT_PATTERN = re.compile(
    r'Waiting for (\d+) seconds before continuing \(required by "upload\.SaveBigFilePart"\)'
)

# Network issues and timeouts patterns
NETWORK_ISSUE_PATTERN = re.compile(
    r'Unable to connect due to network issues: Socket error'
)

REQUEST_TIMEOUT_PATTERN = re.compile(
    r'Retrying "upload\.SaveBigFilePart" due to: Request timed out'
)

# Track which account is currently uploading (will be set by upload process)
_upload_contexts = {}

# Track recent events to avoid duplicate handling
_recent_events = {}  # account_name -> {event_type: timestamp}
EVENT_DEDUPLICATION_WINDOW = 10  # seconds

# Track network/timeout failures for threshold-based rotation
_network_failure_counts = {}  # account_name -> {event_type: count}
_network_failure_timestamps = {}  # account_name -> {event_type: [timestamps]}
NETWORK_FAILURE_THRESHOLD = 2  # Failures before rotation
NETWORK_FAILURE_WINDOW = 60   # seconds to track failures

class RateLimitLogHandler(logging.Handler):
    """Enhanced log handler for Pyrogram rate limiting, network issues, and timeout detection"""
    
    def emit(self, record):
        try:
            message = record.getMessage()
            
            # Check for rate limiting (primary mechanism)
            if (
                record.name == "pyrogram.session.session"
                and "Waiting for" in message
                and "upload.SaveBigFilePart" in message
            ):
                match = re.search(r'Waiting for (\d+) seconds', message)
                if match:
                    wait_seconds = int(match.group(1))
                    # Use asyncio to avoid blocking
                    asyncio.create_task(self._handle_rate_limit(wait_seconds))
            
            # Check for network issues (proactive handling)
            elif (
                record.name == "pyrogram.connection.connection"
                and NETWORK_ISSUE_PATTERN.search(message)
            ):
                asyncio.create_task(self._handle_network_issue())
            
            # Check for request timeouts (proactive handling)
            elif (
                record.name == "pyrogram.session.session"
                and REQUEST_TIMEOUT_PATTERN.search(message)
            ):
                asyncio.create_task(self._handle_request_timeout())

        except Exception as e:
            logger.debug(f"Error in log handler: {e}")
    
    async def _handle_rate_limit(self, wait_seconds: int):
        """Handle rate limiting events proactively"""
        try:
            current_accounts = list(_upload_contexts.values())
            
            if not current_accounts:
                logger.warning("⚠️ Rate limit event detected but no account context available")
                return
            
            # Handle all current accounts (since we can't determine which one triggered it)
            for account_session_name in current_accounts:
                if self._is_duplicate_event(account_session_name, "rate_limit"):
                    logger.debug(f"⏭️ Skipping duplicate rate limit event for {account_session_name}")
                    continue
                
                # Track rate limit event for the specific account
                should_rotate = track_rate_limit_event_per_account(account_session_name, wait_seconds)
                
                if should_rotate:
                    logger.warning(f"🚨 [{account_session_name}] Rate limit threshold exceeded, triggering proxy rotation")
                    await self._trigger_proxy_rotation(account_session_name, f"Rate limit: {wait_seconds}s wait", is_significant_event=True)
                else:
                    logger.info(f"⏰ [{account_session_name}] Rate limit event: {wait_seconds}s wait")
                
                # Mark event as handled
                self._mark_event_handled(account_session_name, "rate_limit")
                
        except Exception as e:
            logger.error(f"Error handling rate limit: {e}")
    
    async def _handle_network_issue(self):
        """Handle network connectivity issues proactively with threshold-based rotation"""
        try:
            current_accounts = list(_upload_contexts.values())
            
            if not current_accounts:
                logger.warning("⚠️ Network issue detected but no account context available")
                return
            
            for account_session_name in current_accounts:
                if self._is_duplicate_event(account_session_name, "network_issue"):
                    logger.debug(f"⏭️ Skipping duplicate network issue for {account_session_name}")
                    continue
                
                # Track failure count
                failure_count = self._track_network_failure(account_session_name, "network_issue")
                
                if failure_count >= NETWORK_FAILURE_THRESHOLD:
                    logger.warning(f"🚨 [{account_session_name}] Network failure threshold exceeded ({failure_count}/{NETWORK_FAILURE_THRESHOLD}), triggering rotation")
                    await self._trigger_proxy_rotation(account_session_name, "Network connectivity issue", is_significant_event=False)
                    # Reset failure count after rotation
                    self._reset_network_failures(account_session_name, "network_issue")
                else:
                    logger.info(f"🌐 [{account_session_name}] Network issue detected ({failure_count}/{NETWORK_FAILURE_THRESHOLD}) - giving proxy a chance")
                
                self._mark_event_handled(account_session_name, "network_issue")
                
        except Exception as e:
            logger.error(f"Error handling network issue: {e}")
    
    async def _handle_request_timeout(self):
        """Handle request timeout issues proactively with threshold-based rotation"""
        try:
            current_accounts = list(_upload_contexts.values())
            
            if not current_accounts:
                logger.warning("⚠️ Request timeout detected but no account context available")
                return
            
            for account_session_name in current_accounts:
                if self._is_duplicate_event(account_session_name, "timeout"):
                    logger.debug(f"⏭️ Skipping duplicate timeout for {account_session_name}")
                    continue
                
                # Track failure count
                failure_count = self._track_network_failure(account_session_name, "timeout")
                
                if failure_count >= NETWORK_FAILURE_THRESHOLD:
                    logger.warning(f"🚨 [{account_session_name}] Timeout failure threshold exceeded ({failure_count}/{NETWORK_FAILURE_THRESHOLD}), triggering rotation")
                    await self._trigger_proxy_rotation(account_session_name, "Request timeout", is_significant_event=False)
                    # Reset failure count after rotation
                    self._reset_network_failures(account_session_name, "timeout")
                else:
                    logger.info(f"⏰ [{account_session_name}] Request timeout detected ({failure_count}/{NETWORK_FAILURE_THRESHOLD}) - giving proxy a chance")
                
                self._mark_event_handled(account_session_name, "timeout")
                
        except Exception as e:
            logger.error(f"Error handling request timeout: {e}")
    
    async def _trigger_proxy_rotation(self, account_session_name: str, reason: str, is_significant_event: bool = False):
        """Trigger proxy rotation for the specified account"""
        try:
            # Find the account in the pool
            account = None
            for acc in UPLOAD_ACCOUNT_POOL:
                if acc.session_name == account_session_name:
                    account = acc
                    break
            
            if not account:
                logger.error(f"❌ Account {account_session_name} not found in pool")
                return
            
            # Get current proxy key for logging
            current_proxy_key = f"{account.proxy_pool[account.current_proxy_index]['ip']}:{account.proxy_pool[account.current_proxy_index]['port']}"
            
            # Trigger proxy rotation
            logger.info(f"🔄 [{account_session_name}] Triggering proxy rotation from {current_proxy_key}: {reason}")
            
            # Immediately rotate to a new proxy (this also marks the current one as failed)
            try:
                await account.rotate_proxy(reason)
                
                # Get new proxy key for logging
                new_proxy_key = f"{account.proxy_pool[account.current_proxy_index]['ip']}:{account.proxy_pool[account.current_proxy_index]['port']}"
                logger.info(f"✅ [{account_session_name}] Successfully rotated from {current_proxy_key} to {new_proxy_key}")
                
                # Notify admin about the successful rotation
                await notify_admin(f"🔄 [{account_session_name}] Proxy rotation: {current_proxy_key} → {new_proxy_key} (reason: {reason})")
                
            except Exception as rotation_error:
                logger.error(f"❌ [{account_session_name}] Failed to rotate proxy {current_proxy_key}: {rotation_error}")
                # Fallback: just mark the current proxy as failed
                account.mark_proxy_failure(account.current_proxy_index, reason, is_significant_event=is_significant_event)
                
                # Notify admin about the failed rotation
                await notify_admin(f"❌ [{account_session_name}] Proxy rotation failed for {current_proxy_key}: {rotation_error}")
            
        except Exception as e:
            logger.error(f"❌ Error triggering proxy rotation for {account_session_name}: {e}")
    
    def _is_duplicate_event(self, account_name: str, event_type: str) -> bool:
        """Check if this event is a duplicate within the deduplication window"""
        current_time = time.time()
        
        if account_name not in _recent_events:
            return False
        
        account_events = _recent_events[account_name]
        if event_type not in account_events:
            return False
        
        time_since_last = current_time - account_events[event_type]
        
        # Clean up expired events immediately
        if time_since_last >= EVENT_DEDUPLICATION_WINDOW:
            del account_events[event_type]
            return False
        
        return True
    
    def _mark_event_handled(self, account_name: str, event_type: str):
        """Mark an event as handled to prevent duplicates"""
        if account_name not in _recent_events:
            _recent_events[account_name] = {}
        
        _recent_events[account_name][event_type] = time.time()

    def _track_network_failure(self, account_name: str, event_type: str) -> int:
        """Track network/timeout failures and return current count within window"""
        current_time = time.time()
        
        # Initialize tracking for this account if needed
        if account_name not in _network_failure_counts:
            _network_failure_counts[account_name] = {}
            _network_failure_timestamps[account_name] = {}
        
        if event_type not in _network_failure_counts[account_name]:
            _network_failure_counts[account_name][event_type] = 0
            _network_failure_timestamps[account_name][event_type] = []
        
        # Add current failure
        _network_failure_timestamps[account_name][event_type].append(current_time)
        _network_failure_counts[account_name][event_type] += 1
        
        # Clean up old failures outside the window
        cutoff_time = current_time - NETWORK_FAILURE_WINDOW
        _network_failure_timestamps[account_name][event_type] = [
            ts for ts in _network_failure_timestamps[account_name][event_type]
            if ts > cutoff_time
        ]
        
        # Update count to reflect only failures within window
        _network_failure_counts[account_name][event_type] = len(_network_failure_timestamps[account_name][event_type])
        
        return _network_failure_counts[account_name][event_type]

    def _reset_network_failures(self, account_name: str, event_type: str):
        """Reset failure count for an account/event type (called on successful operations)"""
        if account_name in _network_failure_counts and event_type in _network_failure_counts[account_name]:
            _network_failure_counts[account_name][event_type] = 0
            _network_failure_timestamps[account_name][event_type] = []
            logger.debug(f"🔄 [{account_name}] Reset {event_type} failure count")

def set_current_uploading_account(task_id: str, account_session_name: str):
    """Set the account that is currently uploading for rate limit tracking"""
    global _upload_contexts
    _upload_contexts[task_id] = account_session_name
    logger.debug(f"📤 [{task_id}] Set account {account_session_name} as current uploading account")

def clear_current_uploading_account(task_id: str):
    """Clear the current uploading account for specific task"""
    global _upload_contexts
    if task_id in _upload_contexts:
        account_name = _upload_contexts[task_id]
        del _upload_contexts[task_id]
        logger.debug(f"📤 [{task_id}] Cleared current uploading account: {account_name}")
    else:
        logger.debug(f"📤 [{task_id}] No upload context found to clear")

def reset_network_failures_for_account(account_name: str):
    """Reset network failure counts for an account (called on successful uploads)"""
    global _network_failure_counts, _network_failure_timestamps
    
    if account_name in _network_failure_counts:
        for event_type in _network_failure_counts[account_name]:
            _network_failure_counts[account_name][event_type] = 0
            _network_failure_timestamps[account_name][event_type] = []
        logger.info(f"🔄 [{account_name}] Reset all network failure counts after successful upload")

def get_current_uploading_account(task_id: str):
    """Get the current uploading account for specific task"""
    return _upload_contexts.get(task_id)

def get_all_current_uploading_accounts():
    """Get all currently uploading accounts (for debugging)"""
    return _upload_contexts.copy()

def setup_pyrogram_rate_limit_monitoring():
    """Attach the custom handler to Pyrogram's loggers (safe, idempotent)"""
    # Setup for session logger (existing)
    pyrogram_session_logger = logging.getLogger("pyrogram.session.session")
    session_handler_exists = any(isinstance(h, RateLimitLogHandler) for h in pyrogram_session_logger.handlers)
    
    # Setup for connection logger (new)
    pyrogram_connection_logger = logging.getLogger("pyrogram.connection.connection")
    connection_handler_exists = any(isinstance(h, RateLimitLogHandler) for h in pyrogram_connection_logger.handlers)
    
    # Create handler if it doesn't exist
    if not session_handler_exists or not connection_handler_exists:
        handler = RateLimitLogHandler()
        
        # Add to session logger if not already present
        if not session_handler_exists:
            pyrogram_session_logger.addHandler(handler)
            logger.info("✅ Pyrogram session rate limit monitoring enabled")
        
        # Add to connection logger if not already present
        if not connection_handler_exists:
            pyrogram_connection_logger.addHandler(handler)
            logger.info("✅ Pyrogram connection monitoring enabled")
        
        return handler
    
    # Return existing handler
    for handler in pyrogram_session_logger.handlers:
        if isinstance(handler, RateLimitLogHandler):
            return handler
    
    return None

def get_rate_limit_summary():
    """Get a summary of current rate limiting status for all accounts"""
    summary = {}
    
    for account in UPLOAD_ACCOUNT_POOL:
        stats = get_rate_limit_stats_per_account(account.session_name)
        summary[account.session_name] = {
            "total_rate_limit_events": stats["total_events"],
            "significant_events": stats["significant_events"],
            "max_wait_time": stats["max_wait_time"],
            "average_wait_time": stats["average_wait_time"],
            "events_in_window": stats["events_in_window"]
        }
    
    # Log summary
    logger.info(f"📊 Rate Limit Summary for {len(summary)} accounts:")
    for account_name, stats in summary.items():
        if stats["total_rate_limit_events"] > 0:
            logger.info(f"   {account_name}: {stats['significant_events']} significant events, avg wait: {stats['average_wait_time']:.1f}s")
    
    # Log current upload contexts
    current_contexts = get_all_current_uploading_accounts()
    if current_contexts:
        logger.info(f"📤 Current upload contexts ({len(current_contexts)} active):")
        for task_id, account_name in current_contexts.items():
            logger.info(f"   {task_id}: {account_name}")
    else:
        logger.info("📤 No active upload contexts")
    
    return summary

def get_network_failure_summary():
    """Get a summary of current network failure status for all accounts"""
    summary = {}
    
    for account in UPLOAD_ACCOUNT_POOL:
        account_name = account.session_name
        if account_name in _network_failure_counts:
            summary[account_name] = {}
            for event_type, count in _network_failure_counts[account_name].items():
                summary[account_name][event_type] = {
                    "current_count": count,
                    "threshold": NETWORK_FAILURE_THRESHOLD,
                    "window_seconds": NETWORK_FAILURE_WINDOW
                }
        else:
            summary[account_name] = {"no_failures": True}
    
    # Log summary
    logger.info(f"🌐 Network Failure Summary for {len(summary)} accounts:")
    for account_name, stats in summary.items():
        if "no_failures" not in stats:
            for event_type, event_stats in stats.items():
                if event_stats["current_count"] > 0:
                    logger.info(f"   {account_name} {event_type}: {event_stats['current_count']}/{event_stats['threshold']}")
        else:
            logger.debug(f"   {account_name}: No network failures")
    
    return summary



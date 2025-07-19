import re
import logging
import asyncio
import time
from backend.video_redirector.utils.upload_video_to_tg import report_rate_limit_event
from backend.video_redirector.config import PROXY_CONFIG

logger = logging.getLogger(__name__)

# Regex patterns to match Pyrogram messages
RATE_LIMIT_PATTERN = re.compile(
    r'Waiting for (\d+) seconds before continuing \(required by "upload\.SaveBigFilePart"\)'
)

# New patterns for network issues and timeouts
NETWORK_ISSUE_PATTERN = re.compile(
    r'Unable to connect due to network issues: Socket error'
)

REQUEST_TIMEOUT_PATTERN = re.compile(
    r'Retrying "upload\.SaveBigFilePart" due to: Request timed out'
)

# Deduplication and rate limiting for immediate rotations
_last_rotation_attempt = 0
_rotation_task_running = False
_rotation_lock = asyncio.Lock()

# Get cooldown from config
_rotation_cooldown = PROXY_CONFIG.get("immediate_rotation_cooldown", 30)  # Default 30 seconds

class RateLimitLogHandler(logging.Handler):
    """Custom log handler for Pyrogram rate limiting detection (safe)"""
    def emit(self, record):
        try:
            message = record.getMessage()
            
            # Check for rate limiting (existing logic)
            if (
                record.name == "pyrogram.session.session"
                and "Waiting for" in message
                and "upload.SaveBigFilePart" in message
            ):
                match = re.search(r'Waiting for (\d+) seconds', message)
                if match:
                    wait_seconds = int(match.group(1))
                    # Use asyncio to avoid blocking
                    asyncio.create_task(self._report_rate_limit(wait_seconds))
            
            # Check for network issues (new logic) - with deduplication
            elif (
                record.name == "pyrogram.connection.connection"
                and NETWORK_ISSUE_PATTERN.search(message)
            ):
                logger.warning("🌐 Network issue detected: Network unreachable")
                # Use asyncio to avoid blocking, with deduplication
                asyncio.create_task(self._report_network_issue_deduplicated())
            
            # Check for request timeouts (new logic) - with deduplication
            elif (
                record.name == "pyrogram.session.session"
                and REQUEST_TIMEOUT_PATTERN.search(message)
            ):
                logger.warning("⏰ Request timeout detected: upload.SaveBigFilePart")
                # Use asyncio to avoid blocking, with deduplication
                asyncio.create_task(self._report_request_timeout_deduplicated())
                
        except Exception as e:
            logger.debug(f"Error in log handler: {e}")
    
    async def _report_rate_limit(self, wait_seconds):
        """Report rate limiting event (existing logic)"""
        try:
            report_rate_limit_event(wait_seconds, "pyrogram_handler")
        except Exception as e:
            logger.debug(f"Error reporting rate limit: {e}")
    
    async def _report_network_issue_deduplicated(self):
        """Report network issue with deduplication to prevent cascade"""
        global _last_rotation_attempt, _rotation_task_running
        
        current_time = time.time()
        
        # Check if we're in cooldown period
        if current_time - _last_rotation_attempt < _rotation_cooldown:
            logger.debug(f"🌐 Network issue detected but rotation in cooldown ({(current_time - _last_rotation_attempt):.1f}s remaining)")
            return
        
        # Check if rotation task is already running
        if _rotation_task_running:
            logger.debug("🌐 Network issue detected but rotation already in progress")
            return

        if _rotation_lock.locked():
            logger.debug("🌐 Network issue detected but rotation already in progress (locked)")
            return

        # Acquire lock to prevent multiple simultaneous rotations
        async with _rotation_lock:

            _rotation_task_running = True
            _last_rotation_attempt = current_time

            try:
                logger.warning("🚨 Network issue detected - triggering immediate proxy rotation")
                await self._trigger_immediate_proxy_rotation("network_issue")
            except Exception as e:
                logger.error(f"Error handling network issue: {e}")
            finally:
                _rotation_task_running = False

    async def _report_request_timeout_deduplicated(self):
        """Report request timeout with deduplication to prevent cascade"""
        global _last_rotation_attempt, _rotation_task_running
        
        current_time = time.time()
        
        # Check if we're in cooldown period
        if current_time - _last_rotation_attempt < _rotation_cooldown:
            logger.debug(f"⏰ Request timeout detected but rotation in cooldown ({(current_time - _last_rotation_attempt):.1f}s remaining)")
            return
        
        # Check if rotation task is already running
        if _rotation_task_running:
            logger.debug("⏰ Request timeout detected but rotation already in progress")
            return

        if _rotation_lock.locked():
            logger.debug("⏰ Request timeout detected but rotation already in progress (locked)")
            return
        
        # Acquire lock to prevent multiple simultaneous rotations
        async with _rotation_lock:

            _rotation_task_running = True
            _last_rotation_attempt = current_time

            try:
                logger.warning("🚨 Request timeout detected - triggering immediate proxy rotation")
                await self._trigger_immediate_proxy_rotation("request_timeout")
            except Exception as e:
                logger.error(f"Error handling request timeout: {e}")
            finally:
                _rotation_task_running = False

    
    async def _trigger_immediate_proxy_rotation(self, reason: str):
        """Trigger immediate proxy rotation without waiting for uploads to complete"""
        try:
            from backend.video_redirector.utils.pyrogram_acc_manager import rotate_proxy_ip_immediate
            await rotate_proxy_ip_immediate(reason)
        except Exception as e:
            logger.error(f"Error triggering immediate proxy rotation: {e}")

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
    """Get a summary of current rate limiting status"""
    from backend.video_redirector.utils.pyrogram_acc_manager import get_rate_limit_stats
    
    stats = get_rate_limit_stats()
    
    summary = {
        "total_rate_limit_events": stats["total_events"],
        "significant_events": stats["significant_events"],
        "max_wait_time": stats["max_wait_time"],
        "average_wait_time": stats["average_wait_time"],
        "events_in_window": stats["events_in_window"]
    }
    
    logger.info(f"📊 Rate Limit Summary:")
    logger.info(f"   Total events: {summary['total_rate_limit_events']}")
    logger.info(f"   Significant events: {summary['significant_events']}")
    logger.info(f"   Max wait time: {summary['max_wait_time']}s")
    logger.info(f"   Average wait time: {summary['average_wait_time']:.1f}s")
    logger.info(f"   Events in window: {summary['events_in_window']}")
    
    return summary 
import re
import logging
import asyncio
from backend.video_redirector.utils.upload_video_to_tg import report_rate_limit_event

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
            
            # Check for network issues (new logic)
            elif (
                record.name == "pyrogram.connection.connection"
                and NETWORK_ISSUE_PATTERN.search(message)
            ):
                logger.warning("🌐 Network issue detected: Network unreachable")
                # Use asyncio to avoid blocking
                asyncio.create_task(self._report_network_issue())
            
            # Check for request timeouts (new logic)
            elif (
                record.name == "pyrogram.session.session"
                and REQUEST_TIMEOUT_PATTERN.search(message)
            ):
                logger.warning("⏰ Request timeout detected: upload.SaveBigFilePart")
                # Use asyncio to avoid blocking
                asyncio.create_task(self._report_request_timeout())
                
        except Exception as e:
            logger.debug(f"Error in log handler: {e}")
    
    async def _report_rate_limit(self, wait_seconds):
        """Report rate limiting event (existing logic)"""
        try:
            report_rate_limit_event(wait_seconds, "pyrogram_handler")
        except Exception as e:
            logger.debug(f"Error reporting rate limit: {e}")
    
    async def _report_network_issue(self):
        """Report network issue and trigger immediate proxy rotation"""
        try:
            logger.warning("🚨 Network issue detected - triggering immediate proxy rotation")
            await self._trigger_immediate_proxy_rotation("network_issue")
        except Exception as e:
            logger.error(f"Error handling network issue: {e}")
    
    async def _report_request_timeout(self):
        """Report request timeout and trigger immediate proxy rotation"""
        try:
            logger.warning("🚨 Request timeout detected - triggering immediate proxy rotation")
            await self._trigger_immediate_proxy_rotation("request_timeout")
        except Exception as e:
            logger.error(f"Error handling request timeout: {e}")
    
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
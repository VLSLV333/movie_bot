import re
import logging
import asyncio
from backend.video_redirector.utils.upload_video_to_tg import report_rate_limit_event

logger = logging.getLogger(__name__)

# Regex pattern to match Pyrogram rate limiting messages
RATE_LIMIT_PATTERN = re.compile(
    r'Waiting for (\d+) seconds before continuing \(required by "upload\.SaveBigFilePart"\)'
)

class RateLimitLogHandler(logging.Handler):
    """Custom log handler for Pyrogram rate limiting detection (safe)"""
    def emit(self, record):
        try:
            if (
                record.name == "pyrogram.session.session"
                and "Waiting for" in record.getMessage()
                and "upload.SaveBigFilePart" in record.getMessage()
            ):
                match = re.search(r'Waiting for (\d+) seconds', record.getMessage())
                if match:
                    wait_seconds = int(match.group(1))
                    # Use asyncio to avoid blocking
                    asyncio.create_task(self._report(wait_seconds))
        except Exception:
            pass
    async def _report(self, wait_seconds):
        try:
            report_rate_limit_event(wait_seconds, "pyrogram_handler")
        except Exception:
            pass

def setup_pyrogram_rate_limit_monitoring():
    """Attach the custom handler to Pyrogram's session logger (safe, idempotent)"""
    pyrogram_logger = logging.getLogger("pyrogram.session.session")
    for handler in pyrogram_logger.handlers:
        if isinstance(handler, RateLimitLogHandler):
            return handler
    handler = RateLimitLogHandler()
    pyrogram_logger.addHandler(handler)
    logger.info("✅ Pyrogram rate limit monitoring enabled via log handler.")
    return handler

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
#!/usr/bin/env python3
"""
Test script to verify rotation deduplication is working properly.
This simulates the cascade of immediate rotation calls that was causing log spam.
"""

import asyncio
import time
import logging
from backend.video_redirector.utils.rate_limit_monitor import RateLimitLogHandler
from backend.video_redirector.utils.pyrogram_acc_manager import rotate_proxy_ip_immediate

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)

async def simulate_network_issues():
    """Simulate multiple network issues in quick succession"""
    logger.info("🧪 Starting simulation of network issues...")
    
    # Create the rate limit handler
    handler = RateLimitLogHandler()
    
    # Simulate multiple network issue log messages in quick succession
    for i in range(10):
        # Create a mock log record
        record = logging.LogRecord(
            name="pyrogram.connection.connection",
            level=logging.WARNING,
            pathname="test.py",
            lineno=1,
            msg="Unable to connect due to network issues: Socket error: 0x03: Network unreachable",
            args=(),
            exc_info=None
        )
        
        # Emit the record (this should trigger rotation)
        handler.emit(record)
        
        # Small delay between messages
        await asyncio.sleep(0.1)
    
    logger.info("🧪 Network issue simulation complete")

async def simulate_request_timeouts():
    """Simulate multiple request timeouts in quick succession"""
    logger.info("🧪 Starting simulation of request timeouts...")
    
    # Create the rate limit handler
    handler = RateLimitLogHandler()
    
    # Simulate multiple timeout log messages in quick succession
    for i in range(10):
        # Create a mock log record
        record = logging.LogRecord(
            name="pyrogram.session.session",
            level=logging.WARNING,
            pathname="test.py",
            lineno=1,
            msg="Retrying \"upload.SaveBigFilePart\" due to: Request timed out",
            args=(),
            exc_info=None
        )
        
        # Emit the record (this should trigger rotation)
        handler.emit(record)
        
        # Small delay between messages
        await asyncio.sleep(0.1)
    
    logger.info("🧪 Request timeout simulation complete")

async def test_direct_rotation_calls():
    """Test direct calls to rotate_proxy_ip_immediate"""
    logger.info("🧪 Testing direct rotation calls...")
    
    # Simulate multiple direct calls in quick succession
    tasks = []
    for i in range(5):
        task = asyncio.create_task(rotate_proxy_ip_immediate(f"test_call_{i}"))
        tasks.append(task)
    
    # Wait for all tasks to complete
    await asyncio.gather(*tasks, return_exceptions=True)
    
    logger.info("🧪 Direct rotation calls test complete")

async def main():
    """Main test function"""
    logger.info("🚀 Starting rotation deduplication tests...")
    
    # Test 1: Network issues simulation
    await simulate_network_issues()
    await asyncio.sleep(2)
    
    # Test 2: Request timeouts simulation
    await simulate_request_timeouts()
    await asyncio.sleep(2)
    
    # Test 3: Direct rotation calls
    await test_direct_rotation_calls()
    
    logger.info("✅ All tests completed!")

if __name__ == "__main__":
    asyncio.run(main()) 
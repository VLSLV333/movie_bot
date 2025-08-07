from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
import os
import time
from dotenv import load_dotenv
from typing import AsyncGenerator
import logging

logger = logging.getLogger(__name__)

load_dotenv()

DATABASE_URL = os.getenv("MOVIE_MIRRORS_DB_URL")
if not DATABASE_URL:
    raise ValueError("MOVIE_MIRRORS_DB_URL environment variable is required")

# Convert to async URL
DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

engine = create_async_engine(
    DATABASE_URL, 
    echo=False,
    pool_size=10,  # Limit concurrent connections
    max_overflow=20,  # Allow some overflow
    pool_timeout=30,  # Timeout for getting connection from pool
    pool_recycle=3600,  # Recycle connections every hour
    pool_pre_ping=True,  # Verify connections before use
    # PostgreSQL uses UTF-8 by default, no need for additional encoding settings
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# Database monitoring variables
_db_operation_count = 0
_db_error_count = 0
_db_lock_count = 0
_last_pool_status_log = 0

async def log_database_pool_status():
    """Log detailed database pool status for debugging"""
    global _last_pool_status_log
    
    current_time = time.time()
    if current_time - _last_pool_status_log < 300:  # Log every 5 minutes
        return
    
    try:
        pool = engine.pool
        logger.info(f"📊 Database Pool Status:")
        logger.info(f"   Pool Size: {pool.size()}")
        logger.info(f"   Checked Out: {pool.checkedout()}")
        logger.info(f"   Checked In: {pool.checkedin()}")
        logger.info(f"   Overflow: {pool.overflow()}")
        logger.info(f"   Total Operations: {_db_operation_count}")
        logger.info(f"   Total Errors: {_db_error_count}")
        logger.info(f"   Lock Errors: {_db_lock_count}")
        
        # Calculate error rates
        if _db_operation_count > 0:
            error_rate = (_db_error_count / _db_operation_count) * 100
            lock_rate = (_db_lock_count / _db_operation_count) * 100
            logger.info(f"   Error Rate: {error_rate:.2f}%")
            logger.info(f"   Lock Rate: {lock_rate:.2f}%")
            
            # Warning thresholds
            if error_rate > 10:
                logger.warning(f"⚠️ High database error rate: {error_rate:.2f}%")
            if lock_rate > 5:
                logger.warning(f"⚠️ High database lock rate: {lock_rate:.2f}%")
            if pool.checkedout() > pool.size() * 0.8:
                logger.warning(f"⚠️ High connection usage: {pool.checkedout()}/{pool.size()}")
        
        _last_pool_status_log = current_time
        
    except Exception as e:
        logger.error(f"❌ Error logging database pool status: {e}")

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    global _db_operation_count
    
    _db_operation_count += 1
    
    # Log pool status periodically
    await log_database_pool_status()
    
    try:
        async with AsyncSessionLocal() as session:
            # Add session ID for debugging
            session_id = id(session)
            logger.info(f"🔗 Database session {session_id} created")
            yield session
            logger.info(f"🔗 Database session {session_id} closed")
    except Exception as e:
        global _db_error_count, _db_lock_count
        
        _db_error_count += 1
        error_str = str(e).lower()
        
        # Categorize errors
        if ("database is locked" in error_str or 
            "operationalerror" in str(type(e).__name__).lower() or
            "illegalstatechangeerror" in error_str):
            _db_lock_count += 1
            logger.error(f"🔒 Database session state error in get_db: {type(e).__name__}: {e}")
            try:
                pool = engine.pool
                logger.error(f"   Pool status - Checked out: {pool.checkedout()}, Size: {pool.size()}")
            except Exception as pool_error:
                logger.error(f"   Could not get pool status: {pool_error}")
        else:
            logger.error(f"❌ Database error in get_db: {type(e).__name__}: {e}")
        
        raise

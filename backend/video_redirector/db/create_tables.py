import asyncio
import logging
from sqlalchemy import create_engine, text
from backend.video_redirector.db.models import Base
import os
from dotenv import load_dotenv
from backend.video_redirector.db.session import get_db

load_dotenv()
DATABASE_URL = os.getenv("MOVIE_MIRRORS_DB_URL")

logger = logging.getLogger(__name__)

def create_all_tables():
    """Create all database tables from scratch"""
    logger.info("🔧 Creating all database tables...")
    
    engine = create_engine(DATABASE_URL)
    Base.metadata.create_all(bind=engine)
    logger.info("✅ All tables created")

async def create_indexes():
    """Create database indexes for performance optimization"""
    logger.info("🔧 Creating database indexes...")
    
    async for db in get_db():
        try:
            # Indexes for downloaded_files table
            await db.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_created_at 
                ON downloaded_files (created_at)
            """))
            
            await db.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_tmdb_id 
                ON downloaded_files (tmdb_id)
            """))
            
            await db.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_session_name 
                ON downloaded_files (session_name)
            """))
            
            # Indexes for downloaded_file_parts table
            await db.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_telegram_file_id 
                ON downloaded_file_parts (telegram_file_id)
            """))
            
            await db.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_downloaded_file_id 
                ON downloaded_file_parts (downloaded_file_id)
            """))
            
            await db.commit()
            logger.info("✅ Database indexes created successfully")
            
        except Exception as e:
            logger.error(f"❌ Error creating indexes: {e}")
            await db.rollback()
            raise
        finally:
            await db.close()

def create_tables_and_indexes():
    """Create tables and indexes in one go"""
    create_all_tables()
    asyncio.run(create_indexes())
    logger.info("✅ Tables and indexes created successfully")

if __name__ == "__main__":
    create_tables_and_indexes()
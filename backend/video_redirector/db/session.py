from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
import os
from dotenv import load_dotenv
from typing import AsyncGenerator

load_dotenv()

DATABASE_URL = os.getenv("MOVIE_MIRRORS_DB_URL")
if not DATABASE_URL:
    raise ValueError("MOVIE_MIRRORS_DB_URL environment variable is required")

# Convert to async URL
DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

# Add UTF-8 encoding parameters to ensure proper handling of international characters
if "?" not in DATABASE_URL:
    DATABASE_URL += "?charset=utf8"
else:
    DATABASE_URL += "&charset=utf8"

engine = create_async_engine(
    DATABASE_URL, 
    echo=False,
    # Additional parameters for better Unicode support
    connect_args={
        "server_settings": {
            "client_encoding": "utf8"
        }
    }
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session

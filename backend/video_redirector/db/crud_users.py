from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from backend.video_redirector.db.models import User
from typing import Optional
from datetime import datetime, timezone

async def create_user(
    session: AsyncSession,
    telegram_id: int,
    user_tg_lang:str,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    custom_name: Optional[str] = None,
    is_onboarded: bool = False,
    is_premium: bool = False,
    movies_lang: Optional[str] = None,
    bot_lang: Optional[str] = None
) -> User:
    """Create a new user in the database"""
    # Use preferred_language as default for new columns if not provided
    movies_lang = movies_lang or user_tg_lang
    bot_lang = bot_lang or user_tg_lang
    
    user = User(
        telegram_id=telegram_id,
        first_name=first_name,
        last_name=last_name,
        custom_name=custom_name,
        user_tg_lang=user_tg_lang,
        movies_lang=movies_lang,
        bot_lang=bot_lang,
        is_onboarded=is_onboarded,
        is_premium=is_premium
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user

async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> Optional[User]:
    """Get user by Telegram ID"""
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()

async def update_user_onboarding(
    session: AsyncSession,
    telegram_id: int,
    custom_name: Optional[str] = None,
    is_onboarded: bool = True,
    is_premium: Optional[bool] = None,
    bot_lang: Optional[str] = None
) -> Optional[User]:
    """Update user's onboarding information"""
    update_data = {
        "is_onboarded": is_onboarded,
        "updated_at": datetime.now(timezone.utc)
    }
    
    if custom_name is not None:
        update_data["custom_name"] = custom_name
    if is_premium is not None:
        update_data["is_premium"] = is_premium
    if bot_lang is not None:
        update_data["bot_lang"] = bot_lang
    
    result = await session.execute(
        update(User)
        .where(User.telegram_id == telegram_id)
        .values(**update_data)
        .returning(User)
    )
    await session.commit()
    return result.scalar_one_or_none()

async def update_user_movies_lang(
    session: AsyncSession,
    telegram_id: int,
    movies_lang: str
) -> Optional[User]:
    """Update user's preferred language for movie content"""
    result = await session.execute(
        update(User)
        .where(User.telegram_id == telegram_id)
        .values(
            movies_lang=movies_lang,
            updated_at=datetime.now(timezone.utc)
        )
        .returning(User)
    )
    await session.commit()
    return result.scalar_one_or_none()

async def update_user_bot_lang(
    session: AsyncSession,
    telegram_id: int,
    bot_lang: str
) -> Optional[User]:
    """Update user's preferred language for bot interface"""
    result = await session.execute(
        update(User)
        .where(User.telegram_id == telegram_id)
        .values(
            bot_lang=bot_lang,
            updated_at=datetime.now(timezone.utc)
        )
        .returning(User)
    )
    await session.commit()
    return result.scalar_one_or_none()

async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    user_tg_lang: str,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    is_premium: bool = False,
    movies_lang: Optional[str] = None,
    bot_lang: Optional[str] = None
) -> User:
    """Get existing user or create new one"""
    user = await get_user_by_telegram_id(session, telegram_id)
    if user is None:
        user = await create_user(
            session=session,
            telegram_id=telegram_id,
            first_name=first_name,
            last_name=last_name,
            is_premium=is_premium,
            user_tg_lang=user_tg_lang,
            movies_lang=movies_lang,
            bot_lang=bot_lang
        )
    return user 
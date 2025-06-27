from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from backend.video_redirector.db.models import User
from typing import Optional
from datetime import datetime, timezone

async def create_user(
    session: AsyncSession,
    telegram_id: int,
    preferred_language: str,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    custom_name: Optional[str] = None,
    is_onboarded: bool = False,
    is_premium: bool = False
) -> User:
    """Create a new user in the database"""
    user = User(
        telegram_id=telegram_id,
        first_name=first_name,
        last_name=last_name,
        custom_name=custom_name,
        preferred_language=preferred_language,
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
    preferred_language: Optional[str] = None,
    is_onboarded: bool = True,
    is_premium: Optional[bool] = None
) -> Optional[User]:
    """Update user's onboarding information"""
    update_data = {
        "is_onboarded": is_onboarded,
        "updated_at": datetime.now(timezone.utc)
    }
    
    if custom_name is not None:
        update_data["custom_name"] = custom_name
    if preferred_language is not None:
        update_data["preferred_language"] = preferred_language
    if is_premium is not None:
        update_data["is_premium"] = is_premium
    
    result = await session.execute(
        update(User)
        .where(User.telegram_id == telegram_id)
        .values(**update_data)
        .returning(User)
    )
    await session.commit()
    return result.scalar_one_or_none()

async def update_user_language(
    session: AsyncSession,
    telegram_id: int,
    preferred_language: str
) -> Optional[User]:
    """Update user's preferred language"""
    result = await session.execute(
        update(User)
        .where(User.telegram_id == telegram_id)
        .values(
            preferred_language=preferred_language,
            updated_at=datetime.now(timezone.utc)
        )
        .returning(User)
    )
    await session.commit()
    return result.scalar_one_or_none()

async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    preferred_language: str,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    is_premium: bool = False
) -> User:
    """Get existing user or create new one"""
    user = await get_user_by_telegram_id(session, telegram_id)
    if user is None:
        user = await create_user(
            session=session,
            telegram_id=telegram_id,
            first_name=first_name,
            last_name=last_name,
            preferred_language=preferred_language,
            is_premium=is_premium
        )
    return user 
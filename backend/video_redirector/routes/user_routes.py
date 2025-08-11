from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from backend.video_redirector.db.session import get_db_dep
from backend.video_redirector.db.crud_users import (
    get_user_by_telegram_id,
    create_user,
    update_user_onboarding,
    update_user_movies_lang,
    update_user_bot_lang,
    get_or_create_user
)
from typing import Optional
import re

import logging
logger = logging.getLogger(__name__)

router = APIRouter()

class UserCreateRequest(BaseModel):
    telegram_id: int
    user_tg_lang: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    custom_name: Optional[str] = None
    is_premium: Optional[bool] = False
    movies_lang: Optional[str] = None
    bot_lang: Optional[str] = None

    @field_validator('user_tg_lang', 'movies_lang', 'bot_lang')
    @classmethod
    def validate_language_codes(cls, v):
        if v is not None:
            # Allow common language codes: en, ru, uk, and other 2-3 letter codes
            if not re.match(r'^[a-z]{2,3}$', v):
                raise ValueError('Invalid language code. Must be 2-3 lowercase letters.')
        return v
    @field_validator('first_name', 'last_name', 'custom_name')
    @classmethod
    def validate_name_fields(cls, v):
        if v is not None:
            # Only check for empty/whitespace-only names and length
            # Database handles Unicode characters including emojis and Cyrillic
            if len(v.strip()) == 0:
                raise ValueError('Name cannot be empty or only whitespace.')
            if len(v) > 100:
                raise ValueError('Name is too long. Maximum 100 characters allowed.')
        return v.strip() if v else v

class UserOnboardingRequest(BaseModel):
    telegram_id: int
    user_tg_lang: str
    custom_name: Optional[str] = None
    is_premium: Optional[bool] = None
    bot_lang: Optional[str] = None

    @field_validator('user_tg_lang', 'bot_lang')
    @classmethod
    def validate_language_codes(cls, v):
        if v is not None:
            # Allow common language codes: en, ru, uk, and other 2-3 letter codes
            if not re.match(r'^[a-z]{2,3}$', v):
                raise ValueError('Invalid language code. Must be 2-3 lowercase letters.')
        return v

    @field_validator('custom_name')
    @classmethod
    def validate_custom_name(cls, v):
        if v is not None:
            # Only check for empty/whitespace-only names and length
            # Database handles Unicode characters including emojis and Cyrillic
            if len(v.strip()) == 0:
                raise ValueError('Name cannot be empty or only whitespace.')
            if len(v) > 100:
                raise ValueError('Name is too long. Maximum 100 characters allowed.')
        return v.strip() if v else v

class UserLanguageRequest(BaseModel):
    telegram_id: int
    user_tg_lang: str

    @field_validator('user_tg_lang')
    @classmethod
    def validate_language_code(cls, v):
        if not re.match(r'^[a-z]{2,3}$', v):
            raise ValueError('Invalid language code. Must be 2-3 lowercase letters.')
        return v

class UserMoviesLanguageRequest(BaseModel):
    telegram_id: int
    movies_lang: str

    @field_validator('movies_lang')
    @classmethod
    def validate_language_code(cls, v):
        if not re.match(r'^[a-z]{2,3}$', v):
            raise ValueError('Invalid language code. Must be 2-3 lowercase letters.')
        return v

class UserBotLanguageRequest(BaseModel):
    telegram_id: int
    bot_lang: str

    @field_validator('bot_lang')
    @classmethod
    def validate_language_code(cls, v):
        if not re.match(r'^[a-z]{2,3}$', v):
            raise ValueError('Invalid language code. Must be 2-3 lowercase letters.')
        return v

@router.get("/users/{telegram_id}")
async def get_user(telegram_id: int, db: AsyncSession = Depends(get_db_dep)):
    """Get user by Telegram ID"""
    try:
        user = await get_user_by_telegram_id(db, telegram_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "custom_name": user.custom_name,
            "user_tg_lang": user.user_tg_lang,
            "movies_lang": user.movies_lang,
            "bot_lang": user.bot_lang,
            "is_onboarded": user.is_onboarded,
            "is_premium": user.is_premium,
            "created_at": user.created_at,
            "updated_at": user.updated_at
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[UserRoutes] Failed to get user {telegram_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get user: {str(e)}")

@router.post("/users")
async def create_new_user(req: UserCreateRequest, db: AsyncSession = Depends(get_db_dep)):
    """Create a new user"""
    try:
        user = await create_user(
            session=db,
            telegram_id=req.telegram_id,
            first_name=req.first_name,
            last_name=req.last_name,
            custom_name=req.custom_name,
            is_premium=req.is_premium or False,
            user_tg_lang=req.user_tg_lang,
            movies_lang=req.movies_lang,
            bot_lang=req.bot_lang
        )
        
        return {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "custom_name": user.custom_name,
            "user_tg_lang": user.user_tg_lang,
            "movies_lang": user.movies_lang,
            "bot_lang": user.bot_lang,
            "is_onboarded": user.is_onboarded,
            "is_premium": user.is_premium,
            "created_at": user.created_at,
            "updated_at": user.updated_at
        }
    except Exception as e:
        logger.exception(f"[UserRoutes] Failed to create user {req.telegram_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create user: {str(e)}")

@router.post("/users/onboarding")
async def complete_onboarding(req: UserOnboardingRequest, db: AsyncSession = Depends(get_db_dep)):
    """Complete user onboarding"""
    try:
        user = await update_user_onboarding(
            session=db,
            telegram_id=req.telegram_id,
            custom_name=req.custom_name,
            is_onboarded=True,
            is_premium=req.is_premium,
            bot_lang=req.bot_lang
        )
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "custom_name": user.custom_name,
            "user_tg_lang": user.user_tg_lang,
            "movies_lang": user.movies_lang,
            "bot_lang": user.bot_lang,
            "is_onboarded": user.is_onboarded,
            "is_premium": user.is_premium,
            "updated_at": user.updated_at
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[UserRoutes] Failed to complete onboarding for user {req.telegram_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to complete onboarding: {str(e)}")

@router.put("/users/movies-language")
async def update_movies_language(req: UserMoviesLanguageRequest, db: AsyncSession = Depends(get_db_dep)):
    """Update user's preferred language for movie content"""
    try:
        user = await update_user_movies_lang(
            session=db,
            telegram_id=req.telegram_id,
            movies_lang=req.movies_lang
        )
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "movies_lang": user.movies_lang,
            "updated_at": user.updated_at
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[UserRoutes] Failed to update movies language for user {req.telegram_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update movies language: {str(e)}")

@router.put("/users/bot-language")
async def update_bot_language(req: UserBotLanguageRequest, db: AsyncSession = Depends(get_db_dep)):
    """Update user's preferred language for bot interface"""
    try:
        user = await update_user_bot_lang(
            session=db,
            telegram_id=req.telegram_id,
            bot_lang=req.bot_lang
        )
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "bot_lang": user.bot_lang,
            "updated_at": user.updated_at
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[UserRoutes] Failed to update bot language for user {req.telegram_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update bot language: {str(e)}")

@router.post("/users/get-or-create")
async def get_or_create_new_user(req: UserCreateRequest, db: AsyncSession = Depends(get_db_dep)):
    """Get existing user or create new one"""
    try:
        user = await get_or_create_user(
            session=db,
            telegram_id=req.telegram_id,
            first_name=req.first_name,
            last_name=req.last_name,
            is_premium=req.is_premium or False,
            user_tg_lang=req.user_tg_lang,
            movies_lang=req.movies_lang,
            bot_lang=req.bot_lang
        )
        
        return {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "custom_name": user.custom_name,
            "user_tg_lang": user.user_tg_lang,
            "movies_lang": user.movies_lang,
            "bot_lang": user.bot_lang,
            "is_onboarded": user.is_onboarded,
            "is_premium": user.is_premium,
            "created_at": user.created_at,
            "updated_at": user.updated_at
        }
    except Exception as e:
        logger.exception(f"[UserRoutes] Failed to get or create user {req.telegram_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get or create user: {str(e)}") 
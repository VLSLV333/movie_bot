from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from backend.video_redirector.db.session import get_db
from backend.video_redirector.db.crud_users import (
    get_user_by_telegram_id,
    create_user,
    update_user_onboarding,
    update_user_movies_lang,
    update_user_bot_lang,
    get_or_create_user
)
from typing import Optional

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

class UserOnboardingRequest(BaseModel):
    telegram_id: int
    user_tg_lang: str
    custom_name: Optional[str] = None
    is_premium: Optional[bool] = None
    bot_lang: Optional[str] = None

class UserLanguageRequest(BaseModel):
    telegram_id: int
    user_tg_lang: str

class UserMoviesLanguageRequest(BaseModel):
    telegram_id: int
    movies_lang: str

class UserBotLanguageRequest(BaseModel):
    telegram_id: int
    bot_lang: str

@router.get("/users/{telegram_id}")
async def get_user(telegram_id: int, db: AsyncSession = Depends(get_db)):
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
async def create_new_user(req: UserCreateRequest, db: AsyncSession = Depends(get_db)):
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
async def complete_onboarding(req: UserOnboardingRequest, db: AsyncSession = Depends(get_db)):
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
async def update_movies_language(req: UserMoviesLanguageRequest, db: AsyncSession = Depends(get_db)):
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
async def update_bot_language(req: UserBotLanguageRequest, db: AsyncSession = Depends(get_db)):
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
async def get_or_create_new_user(req: UserCreateRequest, db: AsyncSession = Depends(get_db)):
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
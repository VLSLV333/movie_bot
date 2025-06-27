from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from backend.video_redirector.db.session import get_db
from backend.video_redirector.db.crud_users import (
    get_user_by_telegram_id,
    create_user,
    update_user_onboarding,
    update_user_language,
    get_or_create_user
)
from typing import Optional

import logging
logger = logging.getLogger(__name__)

router = APIRouter()

class UserCreateRequest(BaseModel):
    telegram_id: int
    preferred_language: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    custom_name: Optional[str] = None
    is_premium: Optional[bool] = False

class UserOnboardingRequest(BaseModel):
    telegram_id: int
    preferred_language: str
    custom_name: Optional[str] = None
    is_premium: Optional[bool] = None

class UserLanguageRequest(BaseModel):
    telegram_id: int
    preferred_language: str

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
            "preferred_language": user.preferred_language,
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
            preferred_language=req.preferred_language,
            is_premium=req.is_premium or False
        )
        
        return {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "custom_name": user.custom_name,
            "preferred_language": user.preferred_language,
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
            preferred_language=req.preferred_language,
            is_onboarded=True,
            is_premium=req.is_premium
        )
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "custom_name": user.custom_name,
            "preferred_language": user.preferred_language,
            "is_onboarded": user.is_onboarded,
            "is_premium": user.is_premium,
            "updated_at": user.updated_at
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[UserRoutes] Failed to complete onboarding for user {req.telegram_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to complete onboarding: {str(e)}")

@router.put("/users/language")
async def update_language(req: UserLanguageRequest, db: AsyncSession = Depends(get_db)):
    """Update user's preferred language"""
    try:
        user = await update_user_language(
            session=db,
            telegram_id=req.telegram_id,
            preferred_language=req.preferred_language
        )
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "preferred_language": user.preferred_language,
            "updated_at": user.updated_at
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[UserRoutes] Failed to update language for user {req.telegram_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update language: {str(e)}")

@router.post("/users/get-or-create")
async def get_or_create_new_user(req: UserCreateRequest, db: AsyncSession = Depends(get_db)):
    """Get existing user or create new one"""
    try:
        user = await get_or_create_user(
            session=db,
            telegram_id=req.telegram_id,
            first_name=req.first_name,
            last_name=req.last_name,
            preferred_language=req.preferred_language,
            is_premium=req.is_premium or False
        )
        
        return {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "custom_name": user.custom_name,
            "preferred_language": user.preferred_language,
            "is_onboarded": user.is_onboarded,
            "is_premium": user.is_premium,
            "created_at": user.created_at,
            "updated_at": user.updated_at
        }
    except Exception as e:
        logger.exception(f"[UserRoutes] Failed to get or create user {req.telegram_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get or create user: {str(e)}") 
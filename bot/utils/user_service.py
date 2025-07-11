import aiohttp
from typing import Optional, Dict, Any
from bot.utils.logger import Logger
from bot.utils.notify_admin import notify_admin

logger = Logger().get_logger()

# Backend API URL
BACKEND_API_URL = "https://moviebot.click"

class UserService:
    """Service for managing user data from backend"""
    
    @staticmethod
    async def get_user_info(user_id: int) -> Optional[Dict[str, Any]]:
        """
        Get complete user information from backend
        
        Returns:
            Dict with user data or None if failed
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{BACKEND_API_URL}/users/{user_id}") as resp:
                    if resp.status == 200:
                        user_data = await resp.json()
                        logger.debug(f"[UserService] Retrieved user data for {user_id}")
                        return user_data
                    else:
                        logger.warning(f"[UserService] Failed to get user {user_id}: {resp.status}")
                        return None
        except Exception as e:
            logger.error(f"[UserService] Error getting user {user_id}: {e}")
            return None
    
    @staticmethod
    async def get_user_is_premium(user_id: int) -> bool:
        user_data = await UserService.get_user_info(user_id)
        if user_data:
            return user_data.get("is_premium", False)
        return False
    
    @staticmethod
    async def get_user_bot_language(user_id: int, default: str = "en") -> str:
        """
        Get user's preferred language for bot interface
        
        Args:
            user_id: Telegram user ID
            default: Default language if user not found or error
            
        Returns:
            User's bot language or default
        """
        user_data = await UserService.get_user_info(user_id)
        if user_data and user_data.get("bot_lang"):
            return user_data.get("bot_lang", default)
        
        await notify_admin(f'tried to get user info for id:{user_id} to get bot language but was not found and provided default lang')
        return default

    @staticmethod
    async def get_user_movies_language(user_id: int, default: str = "en") -> str:
        """
        Get user's preferred language for movie content
        
        Args:
            user_id: Telegram user ID
            default: Default language if user not found or error
            
        Returns:
            User's movies language or default
        """
        user_data = await UserService.get_user_info(user_id)
        if user_data and user_data.get("movies_lang"):
            return user_data.get("movies_lang", default)

        await notify_admin(f'tried to get user info for id:{user_id} to get movies language but was not found and provided default lang')
        return default

    @staticmethod
    async def get_user_telegram_language(user_id: int, default: str = "en") -> str:
        """
        Get user's original Telegram language
        
        Args:
            user_id: Telegram user ID
            default: Default language if user not found or error
            
        Returns:
            User's Telegram language or default
        """
        user_data = await UserService.get_user_info(user_id)
        if user_data and user_data.get("user_tg_lang"):
            return user_data.get("user_tg_lang", default)
        
        await notify_admin(f'tried to get user info for id:{user_id} to get telegram language but was not found and provided default lang')
        return default

    @staticmethod
    async def get_user_custom_name(user_id: int) -> Optional[str]:
        """
        Get user's custom name
        
        Returns:
            Custom name or None if not set
        """
        user_data = await UserService.get_user_info(user_id)
        if user_data:
            return user_data.get("custom_name")
        return None
    
    @staticmethod
    async def get_user_onboarding_status(user_id: int) -> bool:
        """
        Get user's onboarding status
        
        Returns:
            True if user completed onboarding, False otherwise
        """
        user_data = await UserService.get_user_info(user_id)
        if user_data:
            return user_data.get("is_onboarded", False)
        return False

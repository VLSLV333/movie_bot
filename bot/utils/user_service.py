import aiohttp
from typing import Optional, Dict, Any
from bot.utils.logger import Logger
from bot.utils.notify_admin import notify_admin
from bot.config import BACKEND_API_URL

logger = Logger().get_logger()


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
            logger.info(f"[UserService] Making request to get user info for {user_id}")
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{BACKEND_API_URL}/users/{user_id}") as resp:
                    logger.info(f"[UserService] Backend response status for user {user_id}: {resp.status}")
                    if resp.status == 200:
                        user_data = await resp.json()
                        logger.info(f"[UserService] Retrieved user data for {user_id}: {user_data}")
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
        logger.info(f"[UserService] Getting bot language for user {user_id}")
        user_data = await UserService.get_user_info(user_id)
        if user_data:
            bot_lang = user_data.get("bot_lang")
            logger.info(f"[UserService] User {user_id} data contains bot_lang: {bot_lang}")
            if bot_lang:
                logger.info(f"[UserService] Returning bot_lang: {bot_lang} for user {user_id}")
                return bot_lang
            else:
                logger.warning(f"[UserService] User {user_id} has no bot_lang set, using default: {default}")
        else:
            logger.warning(f"[UserService] No user data found for user {user_id}")
        
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

    @staticmethod
    async def set_user_bot_language(user_id: int, bot_lang: str) -> bool:
        """
        Set user's bot interface language
        
        Args:
            user_id: Telegram user ID
            bot_lang: Language code ('en', 'uk', 'ru')
            
        Returns:
            True if successful, False otherwise
        """
        if bot_lang not in ['en', 'uk', 'ru']:
            logger.warning(f"Invalid bot language: {bot_lang}")
            return False
        
        # Get current user data to preserve existing values
        user_data = await UserService.get_user_info(user_id)
        if not user_data:
            logger.error(f"User {user_id} not found, cannot update bot language")
            return False
        
        # Prepare update data with preserved values
        update_data = {
            "telegram_id": user_id,
            "user_tg_lang": user_data.get("user_tg_lang", "en"),  # Preserve existing
            "custom_name": user_data.get("custom_name"),          # Preserve existing
            "bot_lang": bot_lang,                                 # Update this
            "is_premium": user_data.get("is_premium", False)      # Preserve existing
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{BACKEND_API_URL}/users/onboarding", json=update_data) as response:
                    if response.status == 200:
                        logger.info(f"Successfully updated user {user_id} bot language to: {bot_lang}")
                        return True
                    else:
                        logger.error(f"Failed to update user {user_id} bot language: {response.status}")
                        return False
        except Exception as e:
            logger.error(f"Error updating user {user_id} bot language: {e}")
            return False

    @staticmethod
    async def set_user_movies_language(user_id: int, movies_lang: str) -> bool:
        """
        Set user's preferred language for movies
        Args:
            user_id: Telegram user ID
            movies_lang: Language code ('en', 'uk', 'ru')
        Returns:
            True if successful, False otherwise
        """
        if movies_lang not in ['en', 'uk', 'ru']:
            logger.warning(f"Invalid movies language: {movies_lang}")
            return False
        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(
                    f"{BACKEND_API_URL}/users/movies-language",
                    json={
                        "telegram_id": user_id,
                        "movies_lang": movies_lang
                    }
                ) as response:
                    if response.status == 200:
                        logger.info(f"Successfully updated user {user_id} movies language to: {movies_lang}")
                        return True
                    else:
                        logger.error(f"Failed to update user {user_id} movies language: {response.status}")
                        return False
        except Exception as e:
            logger.error(f"Error updating user {user_id} movies language: {e}")
            return False

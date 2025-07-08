"""
User language service for communicating with backend API.
This module provides functions to get user's preferred language from the backend.
"""

import aiohttp
from typing import Optional
from bot.config import BOT_TOKEN
from bot.utils.logger import Logger

logger = Logger().get_logger()

# Backend API URL - you can make this configurable
BACKEND_API_URL = "https://moviebot.click"


async def get_user_language_from_backend(telegram_id: int) -> Optional[str]:
    """
    Get user's preferred language from backend API.
    
    Args:
        telegram_id: Telegram user ID
        
    Returns:
        User's preferred language code ('en', 'uk', 'ru') or None if not found
    """
    try:
        async with aiohttp.ClientSession() as session:
            # Use the same endpoint pattern as in your onboarding handler
            url = f"{BACKEND_API_URL}/users/{telegram_id}"
            
            async with session.get(url) as response:
                if response.status == 200:
                    user_data = await response.json()
                    preferred_lang = user_data.get("preferred_language")
                    
                    if preferred_lang and preferred_lang in ['en', 'uk', 'ru']:
                        logger.debug(f"Retrieved language '{preferred_lang}' for user {telegram_id}")
                        return preferred_lang
                    else:
                        logger.debug(f"User {telegram_id} has invalid/missing language: {preferred_lang}")
                        return None
                        
                elif response.status == 404:
                    logger.debug(f"User {telegram_id} not found in backend")
                    return None
                    
                else:
                    logger.warning(f"Backend API error for user {telegram_id}: {response.status}")
                    return None
                    
    except aiohttp.ClientError as e:
        logger.warning(f"Network error getting language for user {telegram_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error getting language for user {telegram_id}: {e}")
        return None


async def update_user_language_in_backend(telegram_id: int, language: str) -> bool:
    """
    Update user's preferred language in backend API.
    
    Args:
        telegram_id: Telegram user ID
        language: New preferred language code ('en', 'uk', 'ru')
        
    Returns:
        True if successful, False otherwise
    """
    if language not in ['en', 'uk', 'ru']:
        logger.error(f"Invalid language code: {language}")
        return False
        
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{BACKEND_API_URL}/users/language"
            data = {
                "telegram_id": telegram_id,
                "preferred_language": language
            }
            
            async with session.post(url, json=data) as response:
                if response.status == 200:
                    logger.info(f"Updated language to '{language}' for user {telegram_id}")
                    return True
                else:
                    logger.warning(f"Failed to update language for user {telegram_id}: {response.status}")
                    return False
                    
    except aiohttp.ClientError as e:
        logger.warning(f"Network error updating language for user {telegram_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error updating language for user {telegram_id}: {e}")
        return False

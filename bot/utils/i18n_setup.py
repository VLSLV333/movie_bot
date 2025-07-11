"""
I18n setup and configuration for the movie bot.
This module provides the aiogram-i18n middleware setup and user locale detection.
"""

from typing import Any, Dict
from aiogram import types
from aiogram.utils.i18n import I18n, SimpleI18nMiddleware
from bot.utils.user_service import UserService
from bot.utils.logger import Logger

logger = Logger().get_logger()


class MovieBotI18nMiddleware(SimpleI18nMiddleware):
    """
    Custom I18n middleware that extends SimpleI18nMiddleware
    with backend integration for user language preferences.
    """
    
    async def get_locale(self, event: types.TelegramObject, data: Dict[str, Any]) -> str:
        """
        Get user's preferred language for i18n (bot interface language).
        
        Args:
            event: Telegram event object (message, callback_query, etc.)
            data: Additional data from middleware
            
        Returns:
            User's preferred language code ('en', 'uk', 'ru')
        """
        # Extract user from different event types
        user = None
        
        if hasattr(event, 'from_user') and getattr(event, 'from_user', None):
            user = getattr(event, 'from_user')
        elif hasattr(event, 'message') and getattr(event, 'message', None):
            message = getattr(event, 'message')
            if hasattr(message, 'from_user') and getattr(message, 'from_user', None):
                user = getattr(message, 'from_user')
        elif hasattr(event, 'callback_query') and getattr(event, 'callback_query', None):
            callback_query = getattr(event, 'callback_query')
            if hasattr(callback_query, 'from_user') and getattr(callback_query, 'from_user', None):
                user = getattr(callback_query, 'from_user')
        
        if not user:
            logger.warning("Could not extract user from event, defaulting to English")
            return "en"
        
        # Try to get user's preferred bot language from backend
        try:
            bot_lang = await UserService.get_user_bot_language(user.id)
            if bot_lang and bot_lang in ['en', 'uk', 'ru']:
                logger.debug(f"User {user.id} bot language from backend: {bot_lang}")
                return bot_lang
        except Exception as e:
            logger.warning(f"Failed to get user bot language from backend: {e}")
        
        # Fallback to Telegram user language
        telegram_lang = getattr(user, 'language_code', None)
        if telegram_lang:
            # Map common language codes to our supported languages
            lang_mapping = {
                'en': 'en',
                'uk': 'uk', 
                'ua': 'uk',  # Ukrainian alternative code
                'ru': 'ru',
                'by': 'ru',  # Belarusian -> Russian
                'kk': 'ru',  # Kazakh -> Russian
            }
            mapped_lang = lang_mapping.get(telegram_lang.lower(), 'en')
            logger.debug(f"User {user.id} language from Telegram: {telegram_lang} -> {mapped_lang}")
            return mapped_lang
        
        # Ultimate fallback
        logger.debug(f"User {user.id} using default language: en")
        return "en"


def setup_i18n() -> MovieBotI18nMiddleware:
    """
    Setup and return configured I18n middleware.
    
    Returns:
        Configured MovieBotI18nMiddleware instance
    """
    try:
        # Create I18n instance for gettext (.po/.mo files)
        i18n = I18n(
            path="bot/locales", 
            default_locale="en", 
            domain="messages"
        )
        
        # Create our custom middleware
        middleware = MovieBotI18nMiddleware(i18n)
        
        logger.info("I18n middleware configured successfully")
        return middleware
    except Exception as e:
        logger.error(f"Failed to setup I18n middleware: {e}")
        raise


# Supported languages list
SUPPORTED_LANGUAGES = ['en', 'uk', 'ru']

# Language display names for UI
LANGUAGE_NAMES = {
    'en': '🇺🇸 English',
    'uk': '🇺🇦 Ukrainian', 
    'ru': '🇷🇺 Russian'
}


def get_supported_languages() -> list[str]:
    """Get list of supported language codes."""
    return SUPPORTED_LANGUAGES.copy()


def get_language_display_name(lang_code: str) -> str:
    """Get display name for language code."""
    return LANGUAGE_NAMES.get(lang_code, f"Unknown ({lang_code})")


# Set user language function for external use
async def set_user_language(user_id: int, locale: str) -> bool:
    """
    Set user's bot language preference
    
    Args:
        user_id: Telegram user ID
        locale: Language code ('en', 'uk', 'ru')
        
    Returns:
        True if successful, False otherwise
    """
    if locale not in SUPPORTED_LANGUAGES:
        logger.warning(f"Invalid locale '{locale}', ignoring")
        return False
        
    try:
        success = await UserService.set_user_bot_language(user_id, locale)
        if success:
            logger.info(f"Successfully updated user {user_id} bot language to: {locale}")
            return True
        else:
            logger.error(f"Failed to update user {user_id} bot language to: {locale}")
            return False
    except Exception as e:
        logger.error(f"Error setting locale for user {user_id}: {e}")
        return False

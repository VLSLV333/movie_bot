"""
I18n setup and configuration for the movie bot.
This module provides the aiogram-i18n middleware setup and user locale detection.
"""

from typing import Any, Dict
from aiogram import types
from aiogram_i18n import I18nMiddleware
from aiogram_i18n.cores import FluentRuntimeCore
from aiogram_i18n.managers import BaseManager
from bot.utils.user_service import UserService
from bot.utils.logger import Logger

logger = Logger().get_logger()


class MovieBotLocaleManager(BaseManager):
    """
    Custom locale manager for the movie bot.
    This class extends BaseManager to provide proper type safety.
    """
    
    async def get_locale(self, event: types.TelegramObject, data: Dict[str, Any]) -> str:
        """
        Get user's preferred language for i18n (bot interface language).
        This method is called by aiogram-i18n middleware.
        
        Args:
            event: Telegram event object (message, callback_query, etc.)
            data: Additional data from middleware
            
        Returns:
            User's preferred language code ('en', 'uk', 'ru')
        """
        # Extract user from different event types
        user = None
        
        if hasattr(event, 'from_user') and event.from_user:
            user = event.from_user
        elif hasattr(event, 'message') and event.message and event.message.from_user:
            user = event.message.from_user
        elif hasattr(event, 'callback_query') and event.callback_query and event.callback_query.from_user:
            user = event.callback_query.from_user
        
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
        telegram_lang = user.language_code
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


def setup_i18n() -> I18nMiddleware:
    """
    Setup and return configured I18n middleware.
    
    Returns:
        Configured I18nMiddleware instance
    """
    try:
        # Create an instance of our custom locale manager
        locale_manager = MovieBotLocaleManager()
        
        middleware = I18nMiddleware(
            core=FluentRuntimeCore(
                path="bot/locales/{locale}/LC_MESSAGES/messages"
            ),
            manager=locale_manager,
            default_locale="en"
        )
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


# Legacy function for backward compatibility
async def get_user_locale(event: types.TelegramObject, data: Dict[str, Any]) -> str:
    """
    Legacy function - use MovieBotLocaleManager.get_locale() instead.
    Kept for backward compatibility.
    """
    manager = MovieBotLocaleManager()
    return await manager.get_locale(event, data)
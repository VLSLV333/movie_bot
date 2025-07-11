"""
I18n setup and configuration for the movie bot using aiogram_i18n.
This module provides Fluent-based internationalization with custom locale detection.
"""

from typing import Any, Dict
from aiogram import types
from aiogram_i18n import I18nMiddleware
from aiogram_i18n.cores.fluent_runtime_core import FluentRuntimeCore
from bot.utils.user_service import UserService
from bot.utils.logger import Logger

logger = Logger().get_logger()


class MovieBotI18nMiddleware(I18nMiddleware):
    """
    Custom I18n middleware that extends aiogram_i18n I18nMiddleware
    with backend integration and custom locale detection.
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
    import os
    from pathlib import Path
    
    try:
        # Debug: Show current working directory and expected paths
        current_dir = os.getcwd()
        logger.info(f"Current working directory: {current_dir}")
        
        # Test various possible paths
        test_paths = [
            "locales/{locale}/messages.ftl",
            "bot/locales/{locale}/messages.ftl",
            "/app/bot/locales/{locale}/messages.ftl",
            "./locales/{locale}/messages.ftl",
            "../locales/{locale}/messages.ftl"
        ]
        
        for test_path in test_paths:
            # Check for English locale as example
            resolved_path = test_path.replace("{locale}", "en")
            full_path = Path(resolved_path)
            exists = full_path.exists()
            logger.info(f"Testing path: {resolved_path} -> exists: {exists}")
            if exists:
                logger.info(f"  -> Full path: {full_path.absolute()}")
        
        # Check what's in the locales directory
        locales_paths = [
            Path("locales"),
            Path("bot/locales"),
            Path("/app/bot/locales")
        ]
        
        for locales_path in locales_paths:
            if locales_path.exists():
                logger.info(f"Found locales directory: {locales_path.absolute()}")
                try:
                    contents = list(locales_path.iterdir())
                    logger.info(f"  -> Contents: {[str(c.name) for c in contents]}")
                    
                    # Check each locale subdirectory
                    for locale_dir in contents:
                        if locale_dir.is_dir():
                            locale_contents = list(locale_dir.iterdir())
                            logger.info(f"  -> {locale_dir.name} contents: {[str(c.name) for c in locale_contents]}")
                except Exception as e:
                    logger.warning(f"  -> Error reading contents: {e}")
        
        # Create FluentRuntimeCore for .ftl files
        # The aiogram_i18n library expects LC_MESSAGES directory structure
        path_pattern = "locales/{locale}/LC_MESSAGES"
        logger.info(f"Using path pattern: {path_pattern}")
        
        # Check what's in LC_MESSAGES directories
        for locale in ["en", "uk", "ru"]:
            lc_messages_path = Path(f"locales/{locale}/LC_MESSAGES")
            if lc_messages_path.exists() and lc_messages_path.is_dir():
                try:
                    contents = list(lc_messages_path.iterdir())
                    logger.info(f"LC_MESSAGES/{locale} contents: {[str(c.name) for c in contents]}")
                    
                    # Look for .ftl files in LC_MESSAGES
                    for item in contents:
                        if item.name.endswith('.ftl'):
                            logger.info(f"Found .ftl file in LC_MESSAGES: {item}")
                        
                except Exception as e:
                    logger.error(f"Error reading LC_MESSAGES/{locale}: {e}")
            
            # Check if .ftl file exists in parent directory
            file_path = Path(f"locales/{locale}/messages.ftl")
            if file_path.exists():
                stat = file_path.stat()
                logger.info(f"File {file_path}: size={stat.st_size}, mode={oct(stat.st_mode)}")
                
                # Try to read a small portion to ensure it's readable
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        first_line = f.readline().strip()
                        logger.info(f"  -> First line: {first_line[:50]}...")
                except Exception as e:
                    logger.error(f"  -> Error reading file: {e}")
        
        # Try different path patterns
        path_patterns_to_try = [
            "locales/{locale}/LC_MESSAGES",
            "locales/{locale}/messages.ftl", 
            "locales/{locale}",
        ]
        
        core = None
        for pattern in path_patterns_to_try:
            logger.info(f"Trying path pattern: {pattern}")
            try:
                core = FluentRuntimeCore(path=pattern)
                logger.info(f"Successfully created FluentRuntimeCore with pattern: {pattern}")
                break
            except Exception as e:
                logger.error(f"Failed with pattern {pattern}: {e}")
                continue
        
        if core is None:
            logger.error("All path patterns failed, using default pattern")
            core = FluentRuntimeCore(path="locales/{locale}/messages.ftl")
        
        # Create our custom middleware with FluentRuntimeCore
        middleware = MovieBotI18nMiddleware(
            core=core,
            default_locale="en"
        )
        
        logger.info("I18n middleware configured successfully with Fluent support")
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

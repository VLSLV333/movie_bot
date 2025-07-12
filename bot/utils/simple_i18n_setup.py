"""
Simple i18n setup for aiogram 3.x
This is the most straightforward approach that works out of the box.
"""

from pathlib import Path
from aiogram import Dispatcher
from aiogram.utils.i18n import I18n, FSMI18nMiddleware

# Supported languages
SUPPORTED_LANGUAGES = ['en', 'uk', 'ru']
DEFAULT_LANGUAGE = 'en'

def setup_simple_i18n(dp: Dispatcher) -> FSMI18nMiddleware:
    """
    Setup simple i18n using aiogram 3.x built-in support.
    This is the most straightforward approach that works out of the box.
    
    Args:
        dp: The dispatcher instance
        
    Returns:
        The configured i18n middleware
    """
    # Find the locales directory
    locales_base = "locales"  # Docker environment
    if not Path(locales_base).exists():
        locales_base = "bot/locales"  # Local development
    
    if not Path(locales_base).exists():
        raise FileNotFoundError(f"Could not find locales directory at {locales_base}")
    
    # Create i18n instance
    i18n = I18n(
        path=Path(locales_base),
        default_locale=DEFAULT_LANGUAGE,
        domain="messages"
    )
    
    # Create middleware
    i18n_middleware = FSMI18nMiddleware(i18n=i18n)
    
    # Register middleware using the correct aiogram 3.x approach
    dp.message.middleware(i18n_middleware)
    dp.callback_query.middleware(i18n_middleware)
    
    return i18n_middleware

def get_supported_languages():
    """Get list of supported languages."""
    return SUPPORTED_LANGUAGES

def get_default_language():
    """Get default language."""
    return DEFAULT_LANGUAGE 
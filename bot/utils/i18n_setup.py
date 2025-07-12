"""
I18n setup and configuration for the movie bot using aiogram_i18n.
This module provides Fluent-based internationalization with FSM-based locale detection.
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram_i18n import I18nMiddleware, I18nContext
from aiogram_i18n.cores.fluent_runtime_core import FluentRuntimeCore
from bot.utils.user_service import UserService
from bot.utils.logger import Logger

logger = Logger().get_logger()

# Supported languages list
SUPPORTED_LANGUAGES = ['en', 'uk', 'ru']

# Language display names for UI
LANGUAGE_NAMES = {
    'en': '🇺🇸 English',
    'uk': '🇺🇦 Ukrainian', 
    'ru': '🇷🇺 Russian'
}

# Default language
DEFAULT_LANGUAGE = 'en'


# Removed custom middleware class - using standard I18nMiddleware


# I18n middleware instance (will be initialized in setup_i18n)
i18n_middleware: Optional[I18nMiddleware] = None


def setup_i18n() -> I18nMiddleware:
    """
    Setup and return the simplest possible I18n middleware.
    Just detects Telegram language and uses it for translations.
    """
    global i18n_middleware
    
    try:
        # Find locales directory
        current_dir = os.getcwd()
        logger.info(f"Current working directory: {current_dir}")
        
        # Simple path detection
        locales_base = "locales"  # Docker environment
        if not Path(locales_base).exists():
            locales_base = "bot/locales"  # Local development
        
        if not Path(locales_base).exists():
            raise FileNotFoundError(f"Could not find locales directory")
        
        logger.info(f"Found locales directory at: {Path(locales_base).absolute()}")
        
        # Clean up ONLY the problematic __pycache__ directory that causes aiogram_i18n issues
        # This is safe because __pycache__ only contains compiled Python files that are regenerated automatically
        import shutil
        locales_path = Path(locales_base)
        pycache_path = locales_path / "__pycache__"
        if pycache_path.exists():
            try:
                shutil.rmtree(pycache_path)
                logger.info(f"Removed problematic __pycache__ directory: {pycache_path}")
            except Exception as e:
                logger.warning(f"Failed to remove __pycache__ directory: {e}")
        else:
            logger.info("No __pycache__ directory found - no cleanup needed")
        
        # Create the simplest possible FluentRuntimeCore
        core = FluentRuntimeCore(path=f"{locales_base}/{{locale}}/LC_MESSAGES")
        logger.info("Successfully created FluentRuntimeCore")
        
        # Create the simplest possible I18nMiddleware
        # This should automatically detect Telegram language
        i18n_middleware = I18nMiddleware(
            core=core,
            default_locale=DEFAULT_LANGUAGE
        )
        
        logger.info("Simple I18n middleware configured successfully")
        return i18n_middleware
        
    except Exception as e:
        logger.error(f"Failed to setup I18n middleware: {e}")
        raise


# Removed all helper functions - using standard I18nMiddleware behavior

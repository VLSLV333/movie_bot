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


class DebugI18nMiddleware(I18nMiddleware):
    """
    Debug I18n middleware that logs all calls to get_locale and __call__, including arguments and return values.
    This will help us understand if the standard middleware is working.
    """
    
    def __init__(self, core: FluentRuntimeCore, default_locale: str = DEFAULT_LANGUAGE):
        logger.info(f"[DebugI18n] __init__ called with core={core}, default_locale={default_locale}")
        super().__init__(core=core, default_locale=default_locale)
        self._default_locale = default_locale
        logger.info(f"[DebugI18n] Debug middleware initialized with default_locale: {default_locale}")
        
        # Test the core to make sure it's working
        try:
            test_result = core.get("test_key", locale=default_locale)
            logger.info(f"[DebugI18n] Core test successful, test result: {test_result}")
        except Exception as e:
            logger.error(f"[DebugI18n] Core test failed: {e}")
    
    async def get_locale(self, event: types.TelegramObject, data: Dict[str, Any]) -> str:
        logger.info(f"[DebugI18n] get_locale() CALLED with event type: {type(event).__name__}, event={str(event)[:500]}, data={str(data)[:500]}")
        try:
            # Log more details about the event
            if hasattr(event, 'from_user') and getattr(event, 'from_user', None):
                user = getattr(event, 'from_user')
                if hasattr(user, 'id'):
                    user_id = user.id
                    telegram_lang = getattr(user, 'language_code', 'NOT_SET')
                    logger.info(f"[DebugI18n] Event from user {user_id}, Telegram language: {telegram_lang}")
            logger.info(f"[DebugI18n] Returning default locale: {self._default_locale}")
            return self._default_locale
        except Exception as e:
            logger.error(f"[DebugI18n] Exception in get_locale: {e}")
            return self._default_locale
    
    async def __call__(self, handler, event, data):
        logger.info(f"[DebugI18n] Middleware __call__ invoked for event type: {type(event).__name__}, event={str(event)[:500]}, data={str(data)[:500]}, handler={handler}")
        try:
            result = await super().__call__(handler, event, data)
            logger.info(f"[DebugI18n] Middleware __call__ completed for event type: {type(event).__name__}, result={str(result)[:500]}")
            return result
        except Exception as e:
            logger.error(f"[DebugI18n] Exception in __call__: {e}")
            raise


# I18n middleware instance (will be initialized in setup_i18n)
i18n_middleware: Optional[I18nMiddleware] = None


def setup_i18n() -> I18nMiddleware:
    """
    Setup and return debug I18n middleware to diagnose the issue.
    """
    global i18n_middleware
    
    try:
        current_dir = os.getcwd()
        logger.info(f"[DebugI18n] setup_i18n called. Current working directory: {current_dir}")
        
        locales_base = "locales"  # Docker environment
        if not Path(locales_base).exists():
            locales_base = "bot/locales"  # Local development
        logger.info(f"[DebugI18n] Checking locales_base: {locales_base}")
        if not Path(locales_base).exists():
            logger.error(f"[DebugI18n] Could not find locales directory at {locales_base}")
            raise FileNotFoundError(f"Could not find locales directory")
        logger.info(f"[DebugI18n] Found locales directory at: {Path(locales_base).absolute()}")
        
        import shutil
        locales_path = Path(locales_base)
        pycache_path = locales_path / "__pycache__"
        if pycache_path.exists():
            try:
                shutil.rmtree(pycache_path)
                logger.info(f"[DebugI18n] Removed problematic __pycache__ directory: {pycache_path}")
            except Exception as e:
                logger.warning(f"[DebugI18n] Failed to remove __pycache__ directory: {e}")
        else:
            logger.info("[DebugI18n] No __pycache__ directory found - no cleanup needed")
        
        core_path = f"{locales_base}/{{locale}}/LC_MESSAGES"
        logger.info(f"[DebugI18n] Creating FluentRuntimeCore with path: {core_path}")
        for locale in SUPPORTED_LANGUAGES:
            test_path = Path(core_path.replace("{locale}", locale))
            if test_path.exists():
                logger.info(f"[DebugI18n] Path exists for locale {locale}: {test_path}")
            else:
                logger.warning(f"[DebugI18n] Path does not exist for locale {locale}: {test_path}")
        core = FluentRuntimeCore(path=core_path)
        logger.info("[DebugI18n] Successfully created FluentRuntimeCore")
        
        i18n_middleware = DebugI18nMiddleware(
            core=core,
            default_locale=DEFAULT_LANGUAGE
        )
        logger.info("[DebugI18n] Debug I18n middleware configured successfully")
        return i18n_middleware
        
    except Exception as e:
        logger.error(f"[DebugI18n] Failed to setup I18n middleware: {e}")
        raise


# Removed all helper functions - using standard I18nMiddleware behavior

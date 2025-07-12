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


class MovieBotFSMI18nMiddleware(I18nMiddleware):
    """
    Custom FSM-based I18n middleware that integrates with aiogram's FSM
    for storing user language preferences.
    """
    
    def __init__(self, core: FluentRuntimeCore, default_locale: str = DEFAULT_LANGUAGE):
        """Initialize the middleware with core and default locale."""
        super().__init__(core=core, default_locale=default_locale)
        self.fsm_key = "user_locale"
        self._default_locale = default_locale
        logger.info(f"[I18n] Initialized MovieBotFSMI18nMiddleware with default_locale: {default_locale}")
        logger.info(f"[I18n] FSM key set to: {self.fsm_key}")
    
    async def get_locale(self, event: types.TelegramObject, data: Dict[str, Any]) -> str:
        """
        Get user's preferred language from FSM, with fallback to Telegram and backend.
        
        Args:
            event: Telegram event object
            data: Additional data from middleware
            
        Returns:
            User's preferred language code
        """
        logger.info(f"[I18n] get_locale() called with event type: {type(event).__name__}")
        logger.info(f"[I18n] Event object: {event}")
        logger.info(f"[I18n] Middleware data keys: {list(data.keys()) if data else 'None'}")
        
        # Extract user from different event types
        user = None
        
        if hasattr(event, 'from_user') and getattr(event, 'from_user', None):
            user = getattr(event, 'from_user')
            logger.info(f"[I18n] Found user directly in event: {user.id}")
        elif hasattr(event, 'message') and getattr(event, 'message', None):
            message = getattr(event, 'message')
            if hasattr(message, 'from_user') and getattr(message, 'from_user', None):
                user = getattr(message, 'from_user')
                logger.info(f"[I18n] Found user in message: {user.id}")
        elif hasattr(event, 'callback_query') and getattr(event, 'callback_query', None):
            callback_query = getattr(event, 'callback_query')
            if hasattr(callback_query, 'from_user') and getattr(callback_query, 'from_user', None):
                user = getattr(callback_query, 'from_user')
                logger.info(f"[I18n] Found user in callback_query: {user.id}")
        
        if not user:
            logger.warning(f"[I18n] Could not extract user from event {type(event).__name__}, defaulting to default language")
            return self._default_locale
        
        user_id = user.id
        logger.info(f"[I18n] Processing locale for user {user_id}, event: {type(event).__name__}")
        
        # Log available middleware data keys
        available_keys = list(data.keys())
        logger.info(f"[I18n] Available middleware data keys: {available_keys}")
        
        # In aiogram 3, FSM context should be available in middleware data
        # Look for FSM context in the data
        fsm_context = data.get("state")
        
        if not fsm_context:
            # Try alternative keys that might contain FSM context
            for key in ["fsm_context", "context", "state_context"]:
                if key in data:
                    fsm_context = data[key]
                    logger.info(f"[I18n] Found FSM context in key: {key}")
                    break
        
        if fsm_context:
            logger.info(f"[I18n] FSM context found for user {user_id}: {type(fsm_context).__name__}")
        else:
            logger.warning(f"[I18n] No FSM context available for user {user_id} in middleware data")
        
        # Try to get language from FSM first
        if fsm_context:
            try:
                fsm_data = await fsm_context.get_data()
                logger.info(f"[I18n] FSM data for user {user_id}: {fsm_data}")
                fsm_lang = fsm_data.get(self.fsm_key)
                if fsm_lang and fsm_lang in SUPPORTED_LANGUAGES:
                    logger.info(f"[I18n] User {user_id} language from FSM: {fsm_lang}")
                    return fsm_lang
                else:
                    logger.warning(f"[I18n] No valid language in FSM for user {user_id}: {fsm_lang}")
            except Exception as e:
                logger.error(f"[I18n] Failed to get language from FSM for user {user_id}: {e}")
        
        # Fallback to Telegram user language (PRIORITIZED for new users)
        telegram_lang = getattr(user, 'language_code', None)
        if telegram_lang:
            lang_mapping = {
                'en': 'en',
                'uk': 'uk', 
                'ua': 'uk',  # Ukrainian alternative code
                'ru': 'ru',
                'by': 'ru',  # Belarusian -> Russian
                'kk': 'ru',  # Kazakh -> Russian
            }
            mapped_lang = lang_mapping.get(telegram_lang.lower(), self._default_locale)
            logger.info(f"[I18n] User {user_id} language from Telegram: {telegram_lang} -> {mapped_lang}")
            
            # Try to sync to FSM if available
            if fsm_context:
                try:
                    current_data = await fsm_context.get_data()
                    current_data[self.fsm_key] = mapped_lang
                    await fsm_context.set_data(current_data)
                    logger.info(f"[I18n] Synced Telegram language to FSM for user {user_id}")
                except Exception as e:
                    logger.error(f"[I18n] Failed to sync language to FSM for user {user_id}: {e}")
            
            return mapped_lang
        
        # Fallback to backend (for existing users)
        try:
            logger.info(f"[I18n] Falling back to backend for user {user_id}")
            bot_lang = await UserService.get_user_bot_language(user_id)
            if bot_lang and bot_lang in SUPPORTED_LANGUAGES:
                logger.info(f"[I18n] User {user_id} language from backend: {bot_lang}")
                # Try to sync to FSM if available
                if fsm_context:
                    try:
                        current_data = await fsm_context.get_data()
                        current_data[self.fsm_key] = bot_lang
                        await fsm_context.set_data(current_data)
                        logger.info(f"[I18n] Synced backend language to FSM for user {user_id}")
                    except Exception as e:
                        logger.error(f"[I18n] Failed to sync language to FSM for user {user_id}: {e}")
                return bot_lang
            else:
                logger.warning(f"[I18n] Backend returned invalid language for user {user_id}: {bot_lang}")
        except Exception as e:
            logger.error(f"[I18n] Failed to get language from backend for user {user_id}: {e}")
        
        # Ultimate fallback
        logger.warning(f"[I18n] User {user_id} using default language: {self._default_locale}")
        return self._default_locale


# I18n middleware instance (will be initialized in setup_i18n)
i18n_middleware: Optional[MovieBotFSMI18nMiddleware] = None


def setup_i18n() -> MovieBotFSMI18nMiddleware:
    """
    Setup and return configured FSM I18n middleware.
    
    Returns:
        Configured MovieBotFSMI18nMiddleware instance
    """
    global i18n_middleware
    
    try:
        # Debug: Show current working directory and expected paths
        current_dir = os.getcwd()
        logger.info(f"Current working directory: {current_dir}")
        
        # Dynamic path detection based on environment
        # Docker: working_dir is /app/bot, so locales/ is correct
        # Local: working_dir is project root, so bot/locales/ is correct
        possible_locales_bases = [
            "locales",           # Docker environment (/app/bot -> locales)
            "bot/locales",       # Local development (project_root -> bot/locales)
            "/app/bot/locales"   # Docker fallback (absolute path)
        ]
        
        # Find the correct locales base path
        locales_base = None
        for base in possible_locales_bases:
            test_path = Path(base)
            if test_path.exists() and test_path.is_dir():
                locales_base = base
                logger.info(f"Found locales directory at: {test_path.absolute()}")
                break
        
        if not locales_base:
            raise FileNotFoundError(f"Could not find locales directory in any of: {possible_locales_bases}")
        
        # Runtime cleanup: Remove problematic files/directories that cause aiogram_i18n scanning issues
        # This runs every time the bot starts to ensure clean locales directory
        logger.info("Performing runtime cleanup of locales directory")
        
        import shutil
        locales_path = Path(locales_base)
        cleanup_items = []
        
        for item in locales_path.iterdir():
            # Keep only valid locale directories and keys.py
            if item.name in SUPPORTED_LANGUAGES or item.name == "keys.py":
                continue
            
            # Mark for cleanup
            cleanup_items.append(item)
        
        # Remove problematic items
        for item in cleanup_items:
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                    logger.info(f"Removed directory: {item}")
                else:
                    item.unlink()
                    logger.info(f"Removed file: {item}")
            except Exception as e:
                logger.warning(f"Failed to remove {item}: {e}")
        
        logger.info(f"Runtime cleanup complete. Remaining locales contents: {[p.name for p in locales_path.iterdir()]}")
        
        # Now create FluentRuntimeCore with clean directory
        try:
            # Validate that all required .ftl files exist
            missing_files = []
            for locale in SUPPORTED_LANGUAGES:
                ftl_path = Path(f"{locales_base}/{locale}/LC_MESSAGES/messages.ftl")
                if not ftl_path.exists():
                    missing_files.append(str(ftl_path))
            
            if missing_files:
                logger.error(f"Missing .ftl files: {missing_files}")
                raise FileNotFoundError(f"Missing .ftl files: {missing_files}")
            
            # Create the core with clean directory structure
            core = FluentRuntimeCore(path=f"{locales_base}/{{locale}}/LC_MESSAGES")
            logger.info("Successfully created FluentRuntimeCore after runtime cleanup")
            
        except Exception as e:
            logger.error(f"Failed to create FluentRuntimeCore even after cleanup: {e}")
            logger.info("Trying fallback pattern")
            try:
                core = FluentRuntimeCore(path=f"{locales_base}/{{locale}}/messages.ftl")
                logger.info("Successfully created FluentRuntimeCore with fallback pattern")
            except Exception as fallback_error:
                logger.error(f"Fallback also failed: {fallback_error}")
                raise fallback_error
        
        # Create our custom FSM middleware with FluentRuntimeCore
        i18n_middleware = MovieBotFSMI18nMiddleware(
            core=core,
            default_locale=DEFAULT_LANGUAGE
        )
        
        logger.info("I18n middleware configured successfully with FSM and Fluent support")
        return i18n_middleware
        
    except Exception as e:
        logger.error(f"Failed to setup I18n middleware: {e}")
        raise


async def initialize_user_language(user_id: int, fsm_context: FSMContext, fallback_lang: Optional[str] = None) -> str:
    """
    Initialize user's language from backend and sync to FSM.
    
    This function:
    1. Tries to get user language from backend
    2. Falls back to provided fallback language (usually from Telegram)
    3. Syncs the language to FSM for session storage
    4. Returns the final language that was set
    
    Args:
        user_id: Telegram user ID
        fsm_context: FSM context for the user
        fallback_lang: Fallback language (usually from Telegram user.language_code)
        
    Returns:
        The language code that was set ('en', 'uk', 'ru')
    """
    logger.info(f"[I18n] Initializing language for user {user_id}")
    
    # Try to get user's preferred bot language from backend
    try:
        logger.info(f"[I18n] Attempting to get bot language for user {user_id}")
        bot_lang = await UserService.get_user_bot_language(user_id)
        logger.info(f"[I18n] UserService returned bot_lang: {bot_lang} for user {user_id}")
        
        if bot_lang and bot_lang in SUPPORTED_LANGUAGES:
            logger.info(f"[I18n] User {user_id} bot language from backend: {bot_lang}")
            # Sync to FSM
            await fsm_context.set_data({"user_locale": bot_lang})
            return bot_lang
        else:
            logger.warning(f"[I18n] User {user_id} bot language invalid or empty: {bot_lang}")
    except Exception as e:
        logger.warning(f"[I18n] Failed to get user bot language from backend: {e}")
    
    # Fallback to provided language or Telegram language
    if fallback_lang:
        # Map common language codes to our supported languages
        lang_mapping = {
            'en': 'en',
            'uk': 'uk', 
            'ua': 'uk',  # Ukrainian alternative code
            'ru': 'ru',
            'by': 'ru',  # Belarusian -> Russian
            'kk': 'ru',  # Kazakh -> Russian
        }
        mapped_lang = lang_mapping.get(fallback_lang.lower(), DEFAULT_LANGUAGE)
        logger.info(f"[I18n] User {user_id} using fallback language: {fallback_lang} -> {mapped_lang}")
        
        # Sync to FSM
        await fsm_context.set_data({"user_locale": mapped_lang})
        return mapped_lang
    
    # Ultimate fallback
    logger.info(f"[I18n] User {user_id} using default language: {DEFAULT_LANGUAGE}")
    await fsm_context.set_data({"user_locale": DEFAULT_LANGUAGE})
    return DEFAULT_LANGUAGE


async def set_user_language(user_id: int, locale: str, fsm_context: FSMContext) -> bool:
    """
    Set user's bot language preference in both FSM and backend.
    
    This function:
    1. Validates the language code
    2. Updates the FSM with the new language
    3. Updates the backend with the new language
    4. Returns success status
    
    Args:
        user_id: Telegram user ID
        locale: Language code ('en', 'uk', 'ru')
        fsm_context: FSM context for the user
        
    Returns:
        True if successful, False otherwise
    """
    if locale not in SUPPORTED_LANGUAGES:
        logger.warning(f"Invalid locale '{locale}', ignoring")
        return False
        
    try:
        # Update FSM first (immediate effect)
        await fsm_context.set_data({"user_locale": locale})
        logger.info(f"Successfully updated FSM for user {user_id} to language: {locale}")
        
        # Update backend (persistence)
        success = await UserService.set_user_bot_language(user_id, locale)
        if success:
            logger.info(f"Successfully updated backend for user {user_id} to language: {locale}")
            return True
        else:
            logger.error(f"Failed to update backend for user {user_id} to language: {locale}")
            # FSM is already updated, so partial success
            return True
            
    except Exception as e:
        logger.error(f"Error setting locale for user {user_id}: {e}")
        return False


async def get_user_language(user_id: int, fsm_context: FSMContext) -> str:
    """
    Get user's current language from FSM.
    
    Args:
        user_id: Telegram user ID
        fsm_context: FSM context for the user
        
    Returns:
        User's current language code
    """
    try:
        data = await fsm_context.get_data()
        lang = data.get("user_locale", DEFAULT_LANGUAGE)
        
        if lang not in SUPPORTED_LANGUAGES:
            logger.warning(f"Invalid language in FSM for user {user_id}: {lang}, using default")
            return DEFAULT_LANGUAGE
            
        return lang
    except Exception as e:
        logger.error(f"Error getting language from FSM for user {user_id}: {e}")
        return DEFAULT_LANGUAGE


def get_supported_languages() -> list[str]:
    """Get list of supported language codes."""
    return SUPPORTED_LANGUAGES.copy()


def get_language_display_name(lang_code: str) -> str:
    """Get display name for language code."""
    return LANGUAGE_NAMES.get(lang_code, f"Unknown ({lang_code})")


def get_i18n_context() -> I18nContext:
    """
    Get the I18n context for use in handlers.
    
    Returns:
        I18nContext instance
    """
    # This will be injected by the middleware automatically
    # This function is mainly for type hinting purposes
    raise RuntimeError("I18n context should be injected by middleware. Use 'i18n: I18nContext' parameter in handlers.")

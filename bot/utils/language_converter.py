"""
Language code conversion utilities for the movie bot.

This module provides functions to convert between different language code formats:
- Telegram language codes: "en", "uk", "ru"
- TMDB API format (ISO 639-1 with region): "en-US", "uk-UA", "ru-RU"
"""

# Language code mapping from Telegram format to TMDB format
TELEGRAM_TO_TMDB_LANGUAGE_MAPPING = {
    "en": "en-US",  # English - United States
    "uk": "uk-UA",  # Ukrainian - Ukraine
    "ru": "ru-RU",  # Russian - Russia
    "es": "es-ES",  # Spanish - Spain
    "fr": "fr-FR",  # French - France
    "de": "de-DE",  # German - Germany
    "it": "it-IT",  # Italian - Italy
    "pt": "pt-BR",  # Portuguese - Brazil
    "pl": "pl-PL",  # Polish - Poland
    "tr": "tr-TR",  # Turkish - Turkey
    "ar": "ar-SA",  # Arabic - Saudi Arabia
    "hi": "hi-IN",  # Hindi - India
    "ja": "ja-JP",  # Japanese - Japan
    "ko": "ko-KR",  # Korean - South Korea
    "zh": "zh-CN",  # Chinese - China
}

# Reverse mapping from TMDB format to Telegram format
TMDB_TO_TELEGRAM_LANGUAGE_MAPPING = {v: k for k, v in TELEGRAM_TO_TMDB_LANGUAGE_MAPPING.items()}


def convert_telegram_to_tmdb(telegram_language: str) -> str:
    """
    Convert Telegram language code to TMDB API format.
    
    Args:
        telegram_language: Telegram language code (e.g., "en", "uk", "ru")
        
    Returns:
        TMDB-compatible language code (e.g., "en-US", "uk-UA", "ru-RU")
    """
    return TELEGRAM_TO_TMDB_LANGUAGE_MAPPING.get(telegram_language.lower(), "en-US")


def convert_tmdb_to_telegram(tmdb_language: str) -> str:
    """
    Convert TMDB API language code to Telegram format.
    
    Args:
        tmdb_language: TMDB language code (e.g., "en-US", "uk-UA", "ru-RU")
        
    Returns:
        Telegram language code (e.g., "en", "uk", "ru")
    """
    return TMDB_TO_TELEGRAM_LANGUAGE_MAPPING.get(tmdb_language, "en")


def get_supported_languages() -> list[str]:
    """
    Get list of supported language codes in Telegram format.
    
    Returns:
        List of supported language codes (e.g., ["en", "uk", "ru", ...])
    """
    return list(TELEGRAM_TO_TMDB_LANGUAGE_MAPPING.keys())


def is_supported_language(language: str) -> bool:
    """
    Check if a language code is supported.
    
    Args:
        language: Language code to check (in Telegram format)
        
    Returns:
        True if language is supported, False otherwise
    """
    return language.lower() in TELEGRAM_TO_TMDB_LANGUAGE_MAPPING 
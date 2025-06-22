#!/usr/bin/env python3
"""
Test script for language converter functionality.
Run this to verify that language code conversions work correctly.
"""

from bot.utils.language_converter import (
    convert_telegram_to_tmdb,
    convert_tmdb_to_telegram,
    get_supported_languages,
    is_supported_language
)

def test_language_conversions():
    """Test all language conversion functions"""
    print("🧪 Testing Language Converter...")
    print("=" * 50)
    
    # Test Telegram to TMDB conversion
    print("\n1. Telegram Language → TMDB Format:")
    test_cases = [
        ("en", "en-US"),
        ("uk", "uk-UA"),
        ("ru", "ru-RU"),
        ("es", "es-ES"),
        ("fr", "fr-FR"),
        ("de", "de-DE"),
        ("unknown", "en-US"),  # Should default to en-US
    ]
    
    for telegram_lang, expected_tmdb in test_cases:
        result = convert_telegram_to_tmdb(telegram_lang)
        status = "✅" if result == expected_tmdb else "❌"
        print(f"  {status} {telegram_lang} → {result} (expected: {expected_tmdb})")
    
    # Test TMDB to Telegram conversion
    print("\n2. TMDB Format → Telegram Language:")
    test_cases = [
        ("en-US", "en"),
        ("uk-UA", "uk"),
        ("ru-RU", "ru"),
        ("es-ES", "es"),
        ("fr-FR", "fr"),
        ("de-DE", "de"),
        ("unknown", "en"),  # Should default to en
    ]
    
    for tmdb_lang, expected_telegram in test_cases:
        result = convert_tmdb_to_telegram(tmdb_lang)
        status = "✅" if result == expected_telegram else "❌"
        print(f"  {status} {tmdb_lang} → {result} (expected: {expected_telegram})")
    
    # Test supported languages
    print("\n3. Supported Languages:")
    supported = get_supported_languages()
    print(f"  Supported languages: {', '.join(supported)}")
    
    # Test language validation
    print("\n4. Language Validation:")
    test_languages = ["en", "uk", "ru", "es", "fr", "de", "unknown"]
    for lang in test_languages:
        is_supported = is_supported_language(lang)
        status = "✅" if is_supported else "❌"
        print(f"  {status} {lang}: {'Supported' if is_supported else 'Not supported'}")
    
    print("\n" + "=" * 50)
    print("🎉 Language converter tests completed!")

if __name__ == "__main__":
    test_language_conversions() 
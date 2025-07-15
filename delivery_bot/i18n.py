# Simple i18n for delivery bot
from typing import Dict, Any

# Language mapping for Telegram language codes
LANG_MAPPING = {
    'uk': 'uk',  # Ukrainian
    'ru': 'ru',  # Russian
    'en': 'en',  # English
    'be': 'ru',  # Belarusian -> Russian
    'kk': 'ru',  # Kazakh -> Russian
    'ky': 'ru',  # Kyrgyz -> Russian
    'tg': 'ru',  # Tajik -> Russian
    'uz': 'ru',  # Uzbek -> Russian
    'az': 'ru',  # Azerbaijani -> Russian
    'hy': 'ru',  # Armenian -> Russian
    'ka': 'ru',  # Georgian -> Russian
    'mo': 'ru',  # Moldovan -> Russian
    'ro': 'ru',  # Romanian -> Russian
    'bg': 'ru',  # Bulgarian -> Russian
    'mk': 'ru',  # Macedonian -> Russian
    'sr': 'ru',  # Serbian -> Russian
    'hr': 'ru',  # Croatian -> Russian
    'bs': 'ru',  # Bosnian -> Russian
    'sl': 'ru',  # Slovenian -> Russian
    'cs': 'ru',  # Czech -> Russian
    'sk': 'ru',  # Slovak -> Russian
    'pl': 'ru',  # Polish -> Russian
    'lt': 'ru',  # Lithuanian -> Russian
    'lv': 'ru',  # Latvian -> Russian
    'et': 'ru',  # Estonian -> Russian
    'fi': 'ru',  # Finnish -> Russian
    'sv': 'ru',  # Swedish -> Russian
    'da': 'ru',  # Danish -> Russian
    'no': 'ru',  # Norwegian -> Russian
    'is': 'ru',  # Icelandic -> Russian
    'de': 'en',  # German -> English
    'fr': 'en',  # French -> English
    'es': 'en',  # Spanish -> English
    'pt': 'en',  # Portuguese -> English
    'it': 'en',  # Italian -> English
    'nl': 'en',  # Dutch -> English
    'tr': 'en',  # Turkish -> English
    'ar': 'en',  # Arabic -> English
    'he': 'en',  # Hebrew -> English
    'fa': 'en',  # Persian -> English
    'ur': 'en',  # Urdu -> English
    'hi': 'en',  # Hindi -> English
    'bn': 'en',  # Bengali -> English
    'th': 'en',  # Thai -> English
    'vi': 'en',  # Vietnamese -> English
    'ko': 'en',  # Korean -> English
    'ja': 'en',  # Japanese -> English
    'zh': 'en',  # Chinese -> English
}

# Text strings for all supported languages
TEXTS = {
    'en': {
        'internal_error_no_text': '😭 Internal error: no message text. Please, tap "📥 Download" again, it will work 😇',
        'internal_error_no_user_id': '😭 Internal error: no user ID found. Please, tap "📥 Download" again, it will work 😇',
        'malformed_start_link': '😭 Malformed or missing start link. Please, tap "📥 Download" again, it will work 😇',
        'internal_error_missing_secret': '😭 Internal error. Please, tap "📥 Download" again, it will work 😇',
        'invalid_download_link': '😭 Invalid or malformed download link. Please, tap "📥 Download" again, it will work 😇',
        'download_link_expired': '😭 This download link has expired or is no longer available. Please, tap "📥 Download" again, it will work 😇',
        'wrong_account': '🚫 This download link was not created for your account.',
        'download_expired': '😭 This download has expired. Please, tap"📥 Download" again, it will work 😇',
        'video_not_ready': '😭 The video is not ready yet or the link expired. Please, tap"📥 Download" again, it will work 😇',
        'enjoy_content': 'Enjoy your content❤️',
        'video_expired_retry': '😭 This video has expired. Please, tap"📥 Download" again, it will work 😇',
        'could_not_give_full_movie': '😭 I could not give you all content. Please, tap "📥 Download" again, it will work 😇',
        'delivery_error': '😭 An error occurred while delivering your video. Please, tap "📥 Download" again, it will work 😇',
        'malformed_watch_link': '😭 Malformed watch link. Please, tap "📥 Download" again, it will work 😇',
        'invalid_watch_link': '❌ Invalid or tampered watch link.',
        'watch_session_expired': '😭 Watch session expired. Please, tap "📥 Download" again, it will work 😇',
        'watch_link_expired': '😭 This link has already expired. Please, tap"📥 Download" again, it will work 😇',
        'wrong_watch_account': '🚫 This link was not created for your account.',
        'video_expired_watch': '😭 This video has expired. Please, tap"📥 Download" again, it will work 😇',
        'load_content_error': '😭 Failed to load your content. Please, tap"📥 Download" again, it will work 😇',
        'unknown_start_link': '😭 Unknown start link type. Please, tap"📥 Download" again, it will work 😇',
        'internal_error_delivery': '😭 Internal error in delivery bot. Please, tap"📥 Download" again, it will work 😇',
        'catch_all_message': 'I am just a delivery bot😁 Hope you enjoy!'
    },
    'ru': {
        'internal_error_no_text': '😭 Внутренняя ошибка: нет текста сообщения. Пожалуйста, нажмите "📥 Скачать" снова, это сработает 😇',
        'internal_error_no_user_id': '😭 Внутренняя ошибка: ID пользователя не найден. Пожалуйста, нажмите "📥 Скачать" снова, это сработает 😇',
        'malformed_start_link': '😭 Неправильная или отсутствующая ссылка для запуска. Пожалуйста, нажмите "📥 Скачать" снова, это сработает 😇',
        'internal_error_missing_secret': '😭 Внутренняя ошибка. Пожалуйста, нажмите "📥 Скачать" снова, это сработает 😇',
        'invalid_download_link': '😭 Недействительная или неправильная ссылка для загрузки. Пожалуйста, нажмите "📥 Скачать" снова, это сработает 😇',
        'download_link_expired': '😭 Эта ссылка для загрузки истекла или больше не доступна. Пожалуйста, нажмите "📥 Скачать" снова, это сработает 😇',
        'wrong_account': '🚫 Эта ссылка для загрузки не была создана для вашего аккаунта.',
        'download_expired': '😭 Эта загрузка истекла. Пожалуйста, нажмите "📥 Скачать" снова, это сработает 😇',
        'video_not_ready': '😭 Видео еще не готово или ссылка истекла. Пожалуйста, нажмите "📥 Скачать" снова, это сработает 😇',
        'enjoy_content': 'Наслаждайтесь контентом❤️',
        'video_expired_retry': '😭 Это видео истекло. Пожалуйста, нажмите "📥 Скачать" снова, это сработает 😇',
        'could_not_give_full_movie': '😭 Я не смогла дать вам весь контент. Пожалуйста, нажмите "📥 Скачать" снова, это сработает 😇',
        'delivery_error': '😭 Произошла ошибка при доставке вашего видео. Пожалуйста, нажмите "📥 Скачать" снова, это сработает 😇',
        'malformed_watch_link': '😭 Неправильная ссылка для просмотра. Пожалуйста, нажмите "📥 Скачать" снова, это сработает 😇',
        'invalid_watch_link': '❌ Недействительная или подделанная ссылка для просмотра.',
        'watch_session_expired': '😭 Сессия просмотра истекла. Пожалуйста, нажмите "📥 Скачать" снова, это сработает 😇',
        'watch_link_expired': '😭 Эта ссылка уже истекла. Пожалуйста, нажмите "📥 Скачать" снова, это сработает 😇',
        'wrong_watch_account': '🚫 Эта ссылка не была создана для вашего аккаунта.',
        'video_expired_watch': '😭 Это видео истекло. Пожалуйста, нажмите "📥 Скачать" снова, это сработает 😇',
        'load_content_error': '😭 Не удалось загрузить ваш контент. Пожалуйста, нажмите "📥 Скачать" снова, это сработает 😇',
        'unknown_start_link': '😭 Неизвестный тип ссылки для запуска. Пожалуйста, нажмите "📥 Скачать" снова, это сработает 😇',
        'internal_error_delivery': '😭 Внутренняя ошибка в боте доставки. Пожалуйста, нажмите "📥 Скачать" снова, это сработает 😇',
        'catch_all_message': 'Я просто бот доставки😁 Надеюсь, вам понравится!'
    },
    'uk': {
        'internal_error_no_text': '😭 Внутрішня помилка: немає тексту повідомлення. Будь ласка, натисніть "📥 Завантажити" знову, це спрацює 😇',
        'internal_error_no_user_id': '😭 Внутрішня помилка: ID користувача не знайдено. Будь ласка, натисніть "📥 Завантажити" знову, це спрацює 😇',
        'malformed_start_link': '😭 Неправильне або відсутнє посилання для запуску. Будь ласка, натисніть "📥 Завантажити" знову, це спрацює 😇',
        'internal_error_missing_secret': '😭 Внутрішня помилка. Будь ласка, натисніть "📥 Завантажити" знову, це спрацює 😇',
        'invalid_download_link': '😭 Недійсне або неправильне посилання для завантаження. Будь ласка, натисніть "📥 Завантажити" знову, це спрацює 😇',
        'download_link_expired': '😭 Це посилання для завантаження втрачене. Будь ласка, натисніть "📥 Завантажити" знову, це спрацює 😇',
        'wrong_account': '🚫 Це посилання для завантаження не було створено для вашого акаунту.',
        'download_expired': '😭 Це завантаження втрачене. Будь ласка, натисніть "📥 Завантажити" знову, це спрацює 😇',
        'video_not_ready': '😭 Відео ще не готове або посилання втрачене. Будь ласка, натисніть "📥 Завантажити" знову, це спрацює 😇',
        'enjoy_content': 'Насолоджуйтесь контентом❤️',
        'video_expired_retry': '😭 Це відео втрачене. Будь ласка, натисніть "📥 Завантажити" знову, це спрацює 😇',
        'could_not_give_full_movie': '😭 Я не змогла дати вам весь контент. Будь ласка, натисніть "📥 Завантажити" знову, це спрацює 😇',
        'delivery_error': '😭 Сталася помилка при доставці вашого відео. Будь ласка, натисніть "📥 Завантажити" знову, це спрацює 😇',
        'malformed_watch_link': '😭 Неправильне посилання для перегляду. Будь ласка, натисніть "📥 Завантажити" знову, це спрацює 😇',
        'invalid_watch_link': '❌ Недійсне або підроблене посилання для перегляду.',
        'watch_session_expired': '😭 Сесія перегляду закінчилася. Будь ласка, натисніть "📥 Завантажити" знову, це спрацює 😇',
        'watch_link_expired': '😭 Це посилання вже втрачене. Будь ласка, натисніть "📥 Завантажити" знову, це спрацює 😇',
        'wrong_watch_account': '🚫 Це посилання не було створено для вашого акаунту.',
        'video_expired_watch': '😭 Це відео втрачене. Будь ласка, натисніть "📥 Завантажити" знову, це спрацює 😇',
        'load_content_error': '😭 Не вдалося завантажити ваш контент. Будь ласка, натисніть "📥 Завантажити" знову, це спрацює 😇',
        'unknown_start_link': '😭 Невідомий тип посилання для запуску. Будь ласка, натисніть "📥 Завантажити" знову, це спрацює 😇',
        'internal_error_delivery': '😭 Внутрішня помилка в боті доставки. Будь ласка, натисніть "📥 Завантажити" знову, це спрацює 😇',
        'catch_all_message': 'Я просто бот доставки😁 Сподіваюся, вам сподобається!'
    }
}

def get_user_language(user_language_code: str | None) -> str:
    """
    Map Telegram language code to supported language
    Defaults to 'en' for unsupported languages
    """
    if not user_language_code:
        return 'en'
    
    return LANG_MAPPING.get(user_language_code.lower(), 'en')

def get_text(key: str, user_language_code: str | None) -> str:
    """
    Get localized text for the given key and user language
    """
    lang = get_user_language(user_language_code)
    return TEXTS[lang].get(key, TEXTS['en'].get(key, f"Missing text: {key}")) 
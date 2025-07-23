from bot.config import DUB_TRANSLATION_MAP_UA, DUB_TRANSLATION_MAP_EN

def translate_dub_to_ua(dub_name: str) -> str:
    """Translate Russian dub names to Ukrainian"""
    dub_name = dub_name.strip()
    for old, new in DUB_TRANSLATION_MAP_UA.items():
        dub_name = dub_name.replace(old, new)
    return dub_name

def translate_dub_to_en(dub_name: str) -> str:
    """Translate Russian dub names to English"""
    dub_name = dub_name.strip()
    for old, new in DUB_TRANSLATION_MAP_EN.items():
        dub_name = dub_name.replace(old, new)
    return dub_name

def translate_dub_by_language(dub_name: str, target_language: str) -> str:
    """Translate dub names based on target language"""
    if target_language == 'uk':
        return translate_dub_to_ua(dub_name)
    elif target_language == 'en':
        return translate_dub_to_en(dub_name)
    else:
        # For Russian and other languages, return as-is
        return dub_name

from bot.config import DUB_TRANSLATION_MAP

def translate_dub_to_ua(dub_name: str) -> str:
    dub_name = dub_name.strip()
    for old, new in DUB_TRANSLATION_MAP.items():
        dub_name = dub_name.replace(old, new)
    return dub_name

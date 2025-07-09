from aiogram import types

def get_name_selection_keyboard(user: types.User, i18n) -> types.InlineKeyboardMarkup:
    """Create keyboard for name selection"""
    keyboard = []
    
    # Add Telegram names if available
    if user.first_name:
        keyboard.append([types.InlineKeyboardButton(
            text=user.first_name, 
            callback_data=f"select_name:{user.first_name}"
        )])
    
    if user.last_name:
        keyboard.append([types.InlineKeyboardButton(
            text=user.last_name, 
            callback_data=f"select_name:{user.last_name}"
        )])
    
    keyboard.append([types.InlineKeyboardButton(
        text="✏️ Custom name", 
        callback_data="custom_name"
    )])
    
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_language_selection_keyboard(user_lang: str, i18n) -> types.InlineKeyboardMarkup:
    """Create keyboard for language selection"""
    # Map language codes to display names
    lang_names = {
        "uk": "🇺🇦 Ukrainian",
        "en": "🇺🇸 English", 
        "ru": "🇷🇺 Russian",
        # "es": "🇪🇸 Spanish",
        # "fr": "🇫🇷 French",
        # "de": "🇩🇪 German"
    }
    
    keyboard = []
    
    # Show user's Telegram language first if it's supported
    if user_lang in lang_names:
        keyboard.append([types.InlineKeyboardButton(
            text=f"{lang_names[user_lang]}",
            callback_data=f"select_lang:{user_lang}"
        )])
    else:
        keyboard.append([types.InlineKeyboardButton(
            text=f"{lang_names['en']}",
            callback_data="select_lang:en"
        )])
    
    # Add other supported languages
    for lang_code, lang_name in lang_names.items():
        if lang_code != user_lang:
            keyboard.append([types.InlineKeyboardButton(
                text=lang_name, 
                callback_data=f"select_lang:{lang_code}"
            )])
    
    # Add "Other" option for future expansion
    # keyboard.append([types.InlineKeyboardButton(
    #     text="🌍 Other languages",
    #     callback_data="other_lang"
    # )])
    
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard) 
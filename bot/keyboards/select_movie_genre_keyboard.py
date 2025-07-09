from aiogram import types
from bot.helpers.back_button import add_back_button
from aiogram_i18n import I18nContext

# ✅ List of genres with TMDB IDs — we use this for both buttons and API later
GENRES = [
    {"id": 28, "name": "🔫 Action"},
    {"id": 35, "name": "😂 Comedy"},
    {"id": 12, "name": "😎 Adventure"},
    {"id": 53, "name": "🤯 Thriller"},
    {"id": 10749, "name": "❤️ Romance"},
    {"id": 18, "name": "😭 Drama"},
    {"id": 14, "name": "🧙 Fantasy"},
    {"id": 9648, "name": "😱 Mystery"},
    {"id": 10751, "name": "🤗 Family"},
    {"id": 16, "name": "🌞 Animation"},
    {"id": 80, "name": "🕵️ Crime"},
    {"id": 99, "name": "📚 Documentary"},
    {"id": 36, "name": "🏰 History"},
    {"id": 27, "name": "👻 Horror"},
    {"id": 878, "name": "🚀 Sci-Fi"},
    {"id": 10752, "name": "⚔️ War"},
    {"id": 10770, "name": "📺 TV Movie"},
    {"id": 10402, "name": "🎵 Music"},
]


def get_movie_genre_keyboard(selected_genres: list[int], i18n: I18nContext) -> types.InlineKeyboardMarkup:
    """
    Returns an inline keyboard with selectable genres. Selected genres are visually highlighted.
    """
    keyboard = []
    row = []

    for idx, genre in enumerate(GENRES):
        genre_id = genre["id"]
        name = genre["name"]

        is_selected = genre_id in selected_genres
        display = f"✅ {name}" if is_selected else name

        row.append(types.InlineKeyboardButton(
            text=display,
            callback_data=f"toggle_genre:{genre_id}"
        ))

        if (idx + 1) % 2 == 0:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    # Confirm button at the top
    if selected_genres:
        keyboard.append(
            [types.InlineKeyboardButton(text="✅ Confirm", callback_data="confirm_genres")]
        )

    return add_back_button(types.InlineKeyboardMarkup(inline_keyboard=keyboard),source='search',index=0)

from aiogram import types
from bot.helpers.back_button import add_back_button
from aiogram.utils.i18n import gettext
from bot.locales.keys import (
    CONFIRM_BTN, GENRE_ACTION, GENRE_COMEDY, GENRE_ADVENTURE, GENRE_THRILLER,
    GENRE_ROMANCE, GENRE_DRAMA, GENRE_FANTASY, GENRE_MYSTERY, GENRE_FAMILY,
    GENRE_ANIMATION, GENRE_CRIME, GENRE_DOCUMENTARY, GENRE_HISTORY,
    GENRE_HORROR, GENRE_SCIFI, GENRE_WAR, GENRE_TV_MOVIE, GENRE_MUSIC
)

# ✅ List of genres with TMDB IDs mapped to translation keys — we use this for both buttons and API later
GENRES = [
    {"id": 28, "key": GENRE_ACTION},
    {"id": 35, "key": GENRE_COMEDY},
    {"id": 12, "key": GENRE_ADVENTURE},
    {"id": 53, "key": GENRE_THRILLER},
    {"id": 10749, "key": GENRE_ROMANCE},
    {"id": 18, "key": GENRE_DRAMA},
    {"id": 14, "key": GENRE_FANTASY},
    {"id": 9648, "key": GENRE_MYSTERY},
    {"id": 10751, "key": GENRE_FAMILY},
    {"id": 16, "key": GENRE_ANIMATION},
    {"id": 80, "key": GENRE_CRIME},
    {"id": 99, "key": GENRE_DOCUMENTARY},
    {"id": 36, "key": GENRE_HISTORY},
    {"id": 27, "key": GENRE_HORROR},
    {"id": 878, "key": GENRE_SCIFI},
    {"id": 10752, "key": GENRE_WAR},
    {"id": 10770, "key": GENRE_TV_MOVIE},
    {"id": 10402, "key": GENRE_MUSIC},
]


def get_movie_genre_keyboard(selected_genres: list[int]) -> types.InlineKeyboardMarkup:
    """
    Returns an inline keyboard with selectable genres. Selected genres are visually highlighted.
    """
    keyboard = []
    row = []

    for idx, genre in enumerate(GENRES):
        genre_id = genre["id"]
        name = gettext(genre["key"])

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
            [types.InlineKeyboardButton(text=gettext(CONFIRM_BTN), callback_data="confirm_genres")]
        )

    return add_back_button(types.InlineKeyboardMarkup(inline_keyboard=keyboard),source='search',index=0)

import os
from dotenv import load_dotenv

load_dotenv()

TMDB_API_KEY = os.getenv("TMDB_API_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
SESSION_EXPIRATION_SECONDS = 3600  # time to expire redis session if user is inactive
STATE_EXPIRATION_SECONDS = 1800  # time to expire redis session if user is inactive
BATCH_SIZE = 5 # number of movies to show at one time when user is searching by movie title
MINIMUM_NUM_OF_VOTES_FOR_MOVIE_TO_GET_INTO_SUGGESTIONS = 100
SORT_MOVIES_IN_TMDB_RESPONSE_BY = "vote_average.desc"

# Ukrainian translations
DUB_TRANSLATION_MAP_UA = {
    "Украинский": "Український",
    "украинский": "український",
    "одноголосый":"одноголосий",
    "двухголосый":"двоголосий",
    "многоголосый":"багатоголосий",
    "оригинал":"оригінал",
    "субтитры":"субтитри",
    "версия":"версія",
    "Одноголосый":"Одноголосий",
    "Двухголосый":"Двоголосий",
    "Многоголосый":"Багатоголосий",
    "Оригинал":"Оригінал",
    "Субтитры":"Субтитри",
    "Версия":"Версія",
}

# English translations
DUB_TRANSLATION_MAP_EN = {
    "оригинал": "original",
    "Оригинал": "Original",
    "субтитры": "subtitles",
    "Субтитры": "Subtitles",
    "одноголосый": "single voice",
    "Одноголосый": "Single Voice",
    "двухголосый": "dual voice",
    "Двухголосый": "Dual Voice",
    "многоголосый": "multi voice",
    "Многоголосый": "Multi Voice",
    "версия": "version",
    "Версия": "Version",
    "режиссерская": "director's cut",
    "Режиссерская": "Director's Cut",
    "режиссерский": "director's cut",
    "Режиссерский": "Director's Cut",
    "реж": "dir",
    "реж.": "dir.",
    "Реж": "Dir",
    "Реж.": "Dir.",
}
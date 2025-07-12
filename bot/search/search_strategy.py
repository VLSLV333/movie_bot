from typing import List
from bot.services.tmdb_service import TMDBService
from abc import ABC, abstractmethod
from bot.keyboards.select_movie_genre_keyboard import GENRES
from bot.locales.keys import (
    EXPLORING_MOVIES_DEFAULT, SEARCH_CONTEXT_LOOKING_FOR_NAME,
    SEARCH_CONTEXT_SEARCHING_BY_GENRE, SEARCH_CONTEXT_LOOKING_FOR_GENRES
)
from aiogram.utils.i18n import gettext
import logging

logger = logging.getLogger(__name__)

# Create a mapping from genre ID to translation key
GENRE_ID_TO_KEY = {genre["id"]: genre["key"] for genre in GENRES}

class SearchStrategy(ABC):
    """
    Abstract base class for all search strategies.
    Each strategy must implement methods to fetch movies and serialize/deserialize its parameters.
    """

    @abstractmethod
    def get_search_id(self) -> str:
        """Returns a unique identifier string for logging/debugging."""
        pass

    @abstractmethod
    async def get_movies(self, tmdb: TMDBService, page: int) -> dict:
        """Returns a TMDB response (with keys like 'results', 'total_results', etc.)"""
        pass

    @abstractmethod
    def to_dict(self) -> dict:
        """Serialize strategy parameters to store in Redis."""
        pass

    @abstractmethod
    def get_context_text(self) -> str:
        """Returns a short string that describes the user's search intent."""
        return gettext(EXPLORING_MOVIES_DEFAULT)

class SearchByNameStrategy(SearchStrategy):
    def __init__(self, query: str, language: str):
        self.query = query
        self.language = language

    def get_search_id(self) -> str:
        return f"SearchByName: {self.query} ({self.language})"

    async def get_movies(self, tmdb: TMDBService, page: int) -> dict:
        return await tmdb.search_movie(query=self.query, language=self.language, page=page)

    def to_dict(self) -> dict:
        return {
            "type": "search_by_name",
            "query": self.query,
            "language": self.language
        }

    def get_context_text(self) -> str:
        return gettext(SEARCH_CONTEXT_LOOKING_FOR_NAME).format(self.query)

    @staticmethod
    def from_dict(data: dict) -> 'SearchByNameStrategy':
        return SearchByNameStrategy(
            query=data["query"],
            language=data["language"]
        )


class SearchByGenreStrategy(SearchStrategy):
    def __init__(self, genres: List[int], years: List[int], language: str):
        self.genres = genres
        self.years = years
        self.language = language

    def get_search_id(self) -> str:
        return f"SearchByGenre: genres={self.genres}, years={self.years}, lang={self.language}"

    async def get_movies(self, tmdb: TMDBService, page: int) -> dict:
        return await tmdb.discover_movies(
            genres=self.genres,
            years=self.years,
            language=self.language,
            page=page
        )

    def to_dict(self) -> dict:
        return {
            "type": "search_by_genre",
            "genres": self.genres,
            "years": self.years,
            "language": self.language
        }

    def get_context_text(self) -> str:
        if not self.genres:
            return gettext(SEARCH_CONTEXT_SEARCHING_BY_GENRE)

        # Get translated genre names
        genre_names = []
        for gid in self.genres:
            if gid in GENRE_ID_TO_KEY:
                genre_key = GENRE_ID_TO_KEY[gid]
                # Extract just the name part without emoji (split after first space)
                full_name = gettext(genre_key)
                name_part = full_name.split(" ", 1)[-1] if " " in full_name else full_name
                genre_names.append(name_part)
            else:
                genre_names.append(f"Genre {gid}")

        return gettext(SEARCH_CONTEXT_LOOKING_FOR_GENRES).format(', '.join(genre_names))

    @staticmethod
    def from_dict(data: dict) -> 'SearchByGenreStrategy':
        return SearchByGenreStrategy(
            genres=data["genres"],
            years=data["years"],
            language=data["language"]
        )


def strategy_from_dict(data: dict) -> SearchStrategy | None:
    """Factory function to create strategy instances from serialized data."""
    if not data:
        logger.warning("strategy_from_dict called with None or empty data")
        return None
    
    if "type" not in data:
        logger.warning(f"strategy_from_dict called with data missing 'type' field: {data}")
        return None

    try:
        match data["type"]:
            case "search_by_name":
                if "query" not in data or "language" not in data:
                    logger.error(f"SearchByNameStrategy missing required fields: {data}")
                    return None
                return SearchByNameStrategy.from_dict(data)
            case "search_by_genre":
                if "genres" not in data or "years" not in data or "language" not in data:
                    logger.error(f"SearchByGenreStrategy missing required fields: {data}")
                    return None
                return SearchByGenreStrategy.from_dict(data)
            # Add future strategies here
            case _:
                logger.warning(f"Unknown strategy type: {data['type']}")
                return None
    except Exception as e:
        logger.error(f"Error deserializing strategy {data.get('type', 'unknown')}: {e}")
        return None
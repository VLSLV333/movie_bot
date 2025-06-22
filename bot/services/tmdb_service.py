import aiohttp
from bot.config import TMDB_API_KEY
from bot.utils.logger import Logger
from bot.config import SORT_MOVIES_IN_TMDB_RESPONSE_BY, MINIMUM_NUM_OF_VOTES_FOR_MOVIE_TO_GET_INTO_SUGGESTIONS
from bot.utils.language_converter import convert_telegram_to_tmdb

logger = Logger().get_logger()


class TMDBService:
    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(self, api_key: str | None = TMDB_API_KEY):
        if api_key is None:
            raise ValueError("TMDB API key is required")
        self.api_key = api_key

    async def search_movie(self, query: str, language: str, page: int = 1):
        url = f"{self.BASE_URL}/search/movie"
        tmdb_language = convert_telegram_to_tmdb(language)
        params = {
            "api_key": self.api_key,
            "query": query,
            "language": tmdb_language,
            "page": page
        }
        return await self._make_request(url, params)

    async def discover_movies(self, genres: list[int], years: list[int], language: str, page: int = 1):
        url = f"{self.BASE_URL}/discover/movie"
        tmdb_language = convert_telegram_to_tmdb(language)

        params = {
            "api_key": self.api_key,
            "language": tmdb_language,
            "page": page,
            "sort_by": SORT_MOVIES_IN_TMDB_RESPONSE_BY,
            "vote_count.gte": MINIMUM_NUM_OF_VOTES_FOR_MOVIE_TO_GET_INTO_SUGGESTIONS,
            "with_genres": ",".join(str(g) for g in genres),
        }

        if years:
            if len(years) == 1:
                params["primary_release_year"] = years[0]
            else:
                params["primary_release_date.gte"] = f"{min(years)}-01-01"
                params["primary_release_date.lte"] = f"{max(years)}-12-31"

        return await self._make_request(url, params)

    async def _make_request(self, url, params):
        logger.info(f"TMDB API Request: {url} with params: {params}")

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"TMDB API error. Status: {resp.status}")
                    return {"results": [], "page": params.get("page", 1), "total_pages": 0, "total_results": 0}

                data = await resp.json()
                logger.info(f"TMDB API response received. Results: {len(data.get('results', []))}")
                return data
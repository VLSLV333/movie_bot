from typing import Optional, List, Dict
from bot.services.tmdb_service import TMDBService
from bot.search.search_strategy import SearchStrategy
from bot.config import BATCH_SIZE
import asyncio
from bot.utils.logger import Logger

logger = Logger().get_logger()

class UserSearchContext:
    """
     Stores the state of a user's current movie search session for pagination.
    Works dynamically with any SearchStrategy (e.g., name, genre, etc.)
    """

    def __init__(
            self,
            strategy: SearchStrategy,
            language: str = "en-US",
            current_page: int = 0,
            current_result_idx: int = 0,
            current_results: Optional[List[Dict]] = None,
            total_results: int = 0,
            preloaded_next_page: Optional[List[Dict]] = None,
            preloaded_previous_page: Optional[List[Dict]] = None
    ):
        self.strategy = strategy
        self.language = language
        self.current_page = current_page
        self.current_result_idx = current_result_idx
        self.current_results = current_results or []
        self.total_results = total_results
        self.preloaded_next_page = preloaded_next_page
        self.preloaded_previous_page = preloaded_previous_page
        self.next_preload_page_num: Optional[int] = None
        self.prev_preload_page_num: Optional[int] = None

    async def get_next_movies(self, tmdb_service: TMDBService, batch_size: int = BATCH_SIZE) -> List[Dict]:
        preload_pg = self.current_page + 1
        if (
                self.current_results
                and self.current_result_idx + batch_size >= len(self.current_results)
                and self.next_preload_page_num != preload_pg
        ):
            self.next_preload_page_num = preload_pg
            asyncio.create_task(self._preload_next_page(tmdb_service))

        if self.current_result_idx >= len(self.current_results):
            if self.preloaded_next_page is not None:
                self.current_results = self.preloaded_next_page
                self.preloaded_next_page = None
                self.current_page += 1
                self.current_result_idx = 0
                self.next_preload_page_num = None
            else:
                self.current_page += 1
                response = await self.strategy.get_movies(
                    tmdb=tmdb_service,
                    page=self.current_page
                )
                self.next_preload_page_num = None

                if not response.get('results'):
                    return []

                self.current_results = response['results']
                self.current_result_idx = 0

                if response.get("total_results") is not None:
                    self.total_results = response["total_results"]

        next_movies = self.current_results[self.current_result_idx:self.current_result_idx + batch_size]
        self.current_result_idx += len(next_movies)
        return next_movies

    async def get_previous_movies(self, tmdb_service: TMDBService, batch_size: int = BATCH_SIZE) -> List[Dict]:
        prev_pg = self.current_page - 1
        if (
                self.current_results
                and self.current_result_idx - 2 * batch_size < 0
                and prev_pg >= 1
                and prev_pg != self.prev_preload_page_num
        ):
            self.prev_preload_page_num = prev_pg
            asyncio.create_task(self._preload_previous_page(tmdb_service))

        if self.current_result_idx - BATCH_SIZE * 2 < 0:
            if self.preloaded_previous_page:
                self.current_results = self.preloaded_previous_page
                self.preloaded_previous_page = None
                self.prev_preload_page_num = None
                self.current_page -= 1
                self.current_result_idx = max(len(self.current_results) - batch_size, 0)
            else:
                if self.current_page > 1:
                    self.current_page -= 1
                    response = await self.strategy.get_movies(
                        tmdb=tmdb_service,
                        page=self.current_page
                    )
                    self.prev_preload_page_num = None
                    self.current_results = response.get("results", [])
                    self.current_result_idx = max(len(self.current_results) - batch_size, 0)

                    previous_movies = self.current_results[self.current_result_idx:self.current_result_idx + batch_size]
                    self.current_result_idx += len(previous_movies)
                    return previous_movies
                else:
                    self.current_result_idx = 0
        else:
            self.current_result_idx -= BATCH_SIZE * 2

        return await self.get_next_movies(tmdb_service)

    async def _preload_next_page(self, tmdb_service: TMDBService):
        try:
            preload_page = self.current_page + 1
            response = await self.strategy.get_movies(tmdb_service, page=preload_page)
            self.preloaded_next_page = response.get("results", [])
            if response.get("total_results") is not None:
                self.total_results = response["total_results"]
        except Exception as e:
            logger.error(f"[Preload] Error preloading next page: {e}")

    async def _preload_previous_page(self, tmdb_service: TMDBService):
        try:
            if self.current_page <= 1:
                return
            preload_page = self.current_page - 1
            response = await self.strategy.get_movies(tmdb_service, page=preload_page)
            self.preloaded_previous_page = response.get("results", [])
        except Exception as e:
            logger.error(f"[Preload] Error preloading previous page: {e}")

    def to_dict(self):
        return {
            "strategy": self.strategy.to_dict(),
            "current_page": self.current_page,
            "language":self.language,
            "current_result_idx": self.current_result_idx,
            "current_results": self.current_results,
            "total_results": self.total_results,
            "preloaded_next_page": self.preloaded_next_page,
            "preloaded_previous_page": self.preloaded_previous_page
        }

    @classmethod
    def from_dict(cls, data: dict):
        strategy = SearchStrategy.from_dict(data.get("strategy"))
        if not strategy:
            raise ValueError("No valid strategy found in session context")
        return cls(
            strategy=strategy,
            current_page=data.get("current_page", 0),
            language=data.get("language", "en-US"),
            current_result_idx=data.get("current_result_idx", 0),
            current_results=data.get("current_results", []),
            total_results=data.get("total_results", 0),
            preloaded_next_page=data.get("preloaded_next_page", []),
            preloaded_previous_page=data.get("preloaded_previous_page", [])
        )

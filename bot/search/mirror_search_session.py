from typing import List, Dict, Optional
import json

class MirrorSearchSession:
    def __init__(
        self,
        user_id: int,
        movie_id: str,
        original_query: str,
        mirrors_search_results: dict[int, dict],
        current_mirror_index: int = 0,
        current_result_index: int = 0,
        confirmed_movie: Optional[Dict] = None,
        preferred_language: Optional[str] = None,
        top_nav_message_id: Optional[int] = None,
        bottom_nav_message_id: Optional[int] = None,
        card_message_ids: Optional[List[int]] = None
    ):
        self.user_id = user_id
        self.movie_id = movie_id
        self.original_query = original_query
        self.mirrors_search_results = mirrors_search_results  # [{mirror: name, geo_priority, results: [...]}, ...]
        self.current_mirror_index = current_mirror_index
        self.current_result_index = current_result_index
        self.confirmed_movie = confirmed_movie
        self.preferred_language = preferred_language
        self.top_nav_message_id = top_nav_message_id
        self.bottom_nav_message_id = bottom_nav_message_id
        self.card_message_ids = card_message_ids or []

    def to_dict(self) -> Dict:
        return {
            "user_id": self.user_id,
            "movie_id": self.movie_id,
            "original_query": self.original_query,
            "mirrors_search_results": self.mirrors_search_results,
            "current_mirror_index": self.current_mirror_index,
            "current_result_index": self.current_result_index,
            "confirmed_movie": self.confirmed_movie,
            "preferred_language": self.preferred_language,
            "top_nav_message_id": self.top_nav_message_id,
            "bottom_nav_message_id": self.bottom_nav_message_id,
            "card_message_ids": self.card_message_ids
        }

    @staticmethod
    def from_dict(data: Dict) -> 'MirrorSearchSession':
        return MirrorSearchSession(
            user_id=data["user_id"],
            movie_id=data["movie_id"],
            original_query=data["original_query"],
            mirrors_search_results=data.get("mirrors_search_results"),
            current_mirror_index=data.get("current_mirror_index", 0),
            current_result_index=data.get("current_result_index", 0),
            confirmed_movie=data.get("confirmed_movie"),
            preferred_language=data.get("preferred_language"),
            top_nav_message_id=data.get("top_nav_message_id"),
            bottom_nav_message_id=data.get("bottom_nav_message_id"),
            card_message_ids=data.get("card_message_ids", [])
        )

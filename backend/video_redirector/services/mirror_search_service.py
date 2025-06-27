from backend.video_redirector.hdrezka.hdrezka_search_service import search_hdrezka
from fastapi import HTTPException

async def search_for_movie_on_mirror(mirror: str, query: str, fallback_query: str) -> list[dict]:
    try:
        if mirror.lower() == "hdrezka":
            return await search_hdrezka(query, fallback_query)

        raise ValueError(f"No extractor found for mirror: {mirror}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

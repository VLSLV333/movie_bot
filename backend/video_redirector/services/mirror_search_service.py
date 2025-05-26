from backend.video_redirector.hdrezka.hdrezka_search_service import search_hdrezka

async def search_mirror(mirror: str, query: str) -> list[dict]:
    if mirror == "hdrezka":
        return await search_hdrezka(query)
    print('No such mirror found')
    return []

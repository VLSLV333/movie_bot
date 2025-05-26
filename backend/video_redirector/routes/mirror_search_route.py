from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.video_redirector.services.mirror_search_service import search_mirror

router = APIRouter()

class MirrorSearchRequest(BaseModel):
    mirror: str
    query: str
    lang: str  # not used for now, but can be helpful later

@router.post("/mirror/search")
async def mirror_search(req: MirrorSearchRequest):
    try:
        results = await search_mirror(req.mirror, req.query)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

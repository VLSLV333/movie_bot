from fastapi import APIRouter, Query
from backend.video_redirector.youtube.youtube_download_setup import youtube_download_setup

router = APIRouter(prefix="/youtube", tags=["YouTube download"])

@router.get("/download")
async def youtube_download_endpoint(
    data: str = Query(..., description="Base64 encoded payload"),
    sig: str = Query(..., description="Signature for payload verification")
):
    """YouTube download endpoint - follows same pattern as HDRezka download"""
    return await youtube_download_setup(data, sig) 
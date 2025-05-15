from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()

class MirrorFailReport(BaseModel):
    movie_id: str
    mirror_url: str

@router.post("/api/report_mirror_fail")
async def report_failed_mirror(data: MirrorFailReport, request: Request):
    print(f"⚠️ Mirror failed: {data.mirror_url} (movie {data.movie_id})")
    # TODO: I WANT TO CREATE SIMPLE "ALERT BOT" IT WILL JUST SEND ME DM MESSAGE IN TG WHEN ERRORS HAPPEN OR OTHER IMPORTANT INFO
    # TODO: SO HERE I WILL DM ALL MIRROR FAILS TO ME IN TG
    return {"status": "received"}

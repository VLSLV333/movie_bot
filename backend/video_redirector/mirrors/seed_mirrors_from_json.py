from pathlib import Path
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.video_redirector.db.models import Mirror
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("MOVIE_MIRRORS_DB_URL")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

json_path = Path("video_redirector/mirrors/mirror_sources.json")
with json_path.open("r", encoding="utf-8") as f:
    mirror_data = json.load(f)

session = SessionLocal()
inserted = 0
skipped = 0

for entry in mirror_data:
    name = entry["name"]
    domains = entry["domains"]
    geo = entry["geo_priority"]
    mirror_type = entry["type"]

    if not domains:
        skipped += 1
        continue

    for domain in domains:
        mirror = Mirror(
            name=name,
            url=f"https://{domain}",
            geo=geo,
            mirror_type=mirror_type,
            is_working=True
        )
        session.add(mirror)
        inserted += 1

session.commit()
session.close()
print(f"✅ Inserted: {inserted} mirrors | ⏭️ Skipped: {skipped} mirrors with no domains")

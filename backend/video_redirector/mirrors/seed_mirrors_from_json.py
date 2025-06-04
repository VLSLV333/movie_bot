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
updated = 0
skipped = 0

for entry in mirror_data:
    name = entry["name"].lower()
    domains = entry["domains"]
    geo = entry["geo_priority"]
    lang = entry.get("lang")
    if isinstance(lang, str):
        lang = [s.strip() for s in lang.split(",")]
    mirror_type = entry["type"]

    if not domains:
        skipped += 1
        continue

    for domain in domains:
        url = f"https://{domain}"
        existing = session.query(Mirror).filter_by(url=url).first()

        if existing:
            # Update the fields
            existing.name = name.lower()
            existing.geo = geo
            if isinstance(lang, str):
                existing.lang = [s.strip() for s in lang.split(",")]
            else:
                existing.lang = lang
            existing.mirror_type = mirror_type
            updated += 1
        else:
            mirror = Mirror(
                name=name.lower(),
                url=url,
                geo=geo,
                lang=lang,
                mirror_type=mirror_type,
                is_working=True
            )
            session.add(mirror)
            inserted += 1

session.commit()
session.close()
print(f"✅ Inserted: {inserted} mirrors | 🔁 Updated: {updated} | ⏭️ Skipped: {skipped}")

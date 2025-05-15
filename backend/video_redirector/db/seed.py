from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.video_redirector.db.models import Base, MovieMirror
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("MOVIE_MIRRORS_DB_URL")
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()

# Insert test mirror
mirror = MovieMirror(
    movie_id="123",
    mirror_url="https://mirror.cineb.net/movie-123",
    type="yt-dlp",
    quality="1080p",
    geo_priority="EU",
)

session.add(mirror)
session.commit()
print("✅ Mirror added!")
from sqlalchemy import create_engine
from backend.video_redirector.db.models import Base
import os
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("MOVIE_MIRRORS_DB_URL")

engine = create_engine(DATABASE_URL)
Base.metadata.create_all(bind=engine)
print("✅ All tables created")
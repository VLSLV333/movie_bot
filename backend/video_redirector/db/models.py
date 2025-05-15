from sqlalchemy import Column, String, Boolean, DateTime, Integer
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime, timezone

Base = declarative_base()

class MovieMirror(Base):
    __tablename__ = "movie_mirrors"

    id = Column(Integer, primary_key=True, index=True)
    movie_id = Column(String, index=True) # Could be TMDB ID or internal
    mirror_url = Column(String, nullable=False)
    type = Column(String, nullable=False)  # 'yt-dlp', 'iframe', 'direct'
    quality = Column(String, nullable=True)  # '1080p', '720p', etc.
    geo_priority = Column(String, nullable=True)  # 'EU', 'US', etc.
    last_checked_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    is_working = Column(Boolean, default=True)


class Mirror(Base):
    __tablename__ = "mirrors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    geo = Column(String)
    mirror_type = Column(String)  # yt-dlp / iframe / direct
    last_checked = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    is_working = Column(Boolean, default=True)
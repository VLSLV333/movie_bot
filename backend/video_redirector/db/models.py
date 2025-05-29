from enum import Enum
from sqlalchemy import Enum as SqlEnum
from sqlalchemy import Column, String, Boolean, DateTime, Integer, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import ARRAY

Base = declarative_base()

class MirrorType(str, Enum):
    ytdlp = "yt-dlp"
    iframe = "iframe"
    direct = "direct"

class Mirror(Base):
    __tablename__ = "mirrors"
    __table_args__ = (UniqueConstraint("url", name="uq_mirror_url"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    geo = Column(String)
    lang = Column(ARRAY(String), nullable=True)
    mirror_type = Column(SqlEnum(MirrorType), nullable=False)
    last_checked = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    is_working = Column(Boolean, default=True)
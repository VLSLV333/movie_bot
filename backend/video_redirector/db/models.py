from enum import Enum
from sqlalchemy import Enum as SqlEnum
from sqlalchemy import Column, String, Boolean, DateTime, Integer, BigInteger, UniqueConstraint,Text, ForeignKey, Date
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import ARRAY

Base = declarative_base()

class MirrorType(str, Enum):
    ytdlp = "yt-dlp"
    iframe = "iframe"
    direct = "direct"

class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("telegram_id", name="uq_user_telegram_id"),)

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, nullable=False, unique=True)  # BIGINT for large Telegram IDs
    first_name = Column(String(100))
    last_name = Column(String(100))
    custom_name = Column(String(100))
    user_tg_lang = Column(String(10))  # User's default language from Telegram
    movies_lang = Column(String(10))   # Language for movie content/dubs
    bot_lang = Column(String(10))      # Language for bot interface
    is_onboarded = Column(Boolean, default=False)
    is_premium = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

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

class DownloadedFile(Base):
    __tablename__ = "downloaded_files"
    __table_args__ = (UniqueConstraint("tmdb_id", "lang", "dub", name="uq_tmdb_lang_dub"),)

    id = Column(Integer, primary_key=True)
    tmdb_id = Column(BigInteger, nullable=False)
    lang = Column(String, nullable=False)
    dub = Column(String, nullable=False)
    quality = Column(String, nullable=True)  # optional field if we track resolution
    tg_bot_token_file_owner = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    movie_title = Column(String, nullable=True)
    movie_poster = Column(String, nullable=True)
    movie_url = Column(String, nullable=True)
    checked_by_admin = Column(Boolean, default=False)
    session_name = Column(String, nullable=True)

class DownloadedFilePart(Base):
    __tablename__ = "downloaded_file_parts"

    id = Column(Integer, primary_key=True)
    downloaded_file_id = Column(Integer, ForeignKey("downloaded_files.id", ondelete="CASCADE"), nullable=False)
    part_number = Column(Integer, nullable=False)
    telegram_file_id = Column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("downloaded_file_id", "part_number", name="uq_file_part"),
    )

class UploadAccountStats(Base):
    __tablename__ = "upload_account_stats"
    id = Column(Integer, primary_key=True)
    session_name = Column(String, unique=True, nullable=False)
    total_uploads = Column(Integer, default=0)
    today_uploads = Column(Integer, default=0)
    last_error = Column(String)
    last_upload_date = Column(Date)
    last_upload_time = Column(DateTime)
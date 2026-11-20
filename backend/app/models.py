from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Integer, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

def utcnow():
    return datetime.now(timezone.utc)

class Site(Base):
    __tablename__ = "sites"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(2048), unique=True, index=True)
    run_frequency: Mapped[str] = mapped_column(String(20), default="manual")
    status: Mapped[str] = mapped_column(String(30), default="onboarding")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    fields: Mapped[list["SiteField"]] = relationship(back_populates="site", cascade="all, delete-orphan")
    captures: Mapped[list["CaptureRun"]] = relationship(back_populates="site", cascade="all, delete-orphan")

class SiteField(Base):
    __tablename__ = "site_fields"
    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    data_type: Mapped[str] = mapped_column(String(30), default="string")
    required: Mapped[int] = mapped_column(Integer, default=1)
    example_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    site: Mapped[Site] = relationship(back_populates="fields")

class CaptureRun(Base):
    __tablename__ = "capture_runs"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"), nullable=True, index=True)
    requested_url: Mapped[str] = mapped_column(String(2048))
    final_url: Mapped[str] = mapped_column(String(2048))
    page_title: Mapped[str] = mapped_column(String(500), default="")
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    load_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    html_characters: Mapped[int] = mapped_column(Integer, default=0)
    cleaned_html_characters: Mapped[int] = mapped_column(Integer, default=0)
    screenshot_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    cleaned_html_preview: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    site: Mapped[Site | None] = relationship(back_populates="captures")

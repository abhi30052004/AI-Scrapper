from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Integer, Float, Text, ForeignKey, UniqueConstraint
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

class ScraperConfig(Base):
    __tablename__ = "scraper_configs"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    site_url: Mapped[str] = mapped_column(String(2048))
    version: Mapped[int] = mapped_column(Integer)
    config_json: Mapped[str] = mapped_column(Text)
    sample_records: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class ExtractionRun(Base):
    __tablename__ = "extraction_runs"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    config_id: Mapped[int] = mapped_column(Integer)
    start_url: Mapped[str] = mapped_column(String(2048))
    pages_crawled: Mapped[int] = mapped_column(Integer)
    record_count: Mapped[int] = mapped_column(Integer)
    records_json: Mapped[str] = mapped_column(Text)
    diagnostics_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(100))

class ChangeReport(Base):
    __tablename__ = "change_reports"
    __table_args__ = (UniqueConstraint("old_run_id", "new_run_id"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    config_id: Mapped[int] = mapped_column(Integer)
    old_run_id: Mapped[int] = mapped_column(Integer)
    new_run_id: Mapped[int] = mapped_column(Integer)
    added_count: Mapped[int] = mapped_column(Integer)
    removed_count: Mapped[int] = mapped_column(Integer)
    modified_count: Mapped[int] = mapped_column(Integer)
    unchanged_count: Mapped[int] = mapped_column(Integer)
    changes_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(100))

class RepairHistory(Base):
    __tablename__ = "repair_history"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    original_config_id: Mapped[int] = mapped_column(Integer)
    site_url: Mapped[str] = mapped_column(String(2048))
    status: Mapped[str] = mapped_column(String(50))
    confidence: Mapped[float] = mapped_column(Float)
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_report_json: Mapped[str] = mapped_column(Text)
    proposed_config_json: Mapped[str] = mapped_column(Text)
    sample_records_json: Mapped[str] = mapped_column(Text)
    saved_config_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("extraction_runs.id", ondelete="CASCADE"), index=True)
    config_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"), nullable=True, index=True)
    site_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    price: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rating: Mapped[str | None] = mapped_column(String(100), nullable=True)
    availability: Mapped[str | None] = mapped_column(String(100), nullable=True)
    product_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    scraped_at: Mapped[str | None] = mapped_column(String(100), nullable=True)
    raw_data_json: Mapped[str | None] = mapped_column(Text, nullable=True)


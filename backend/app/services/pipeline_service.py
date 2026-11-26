import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models import CaptureRun, Site
from app.services.capture import capture_page
from app.services.cleaner import clean_html
from app.services.database_explorer_service import (
    initialize_database_explorer_db,
    sync_run_products,
)
from app.services.extraction_service import (
    ensure_semantic_config,
    initialize_extraction_db,
)
from app.services.extractor import extract_semantic_products
from app.services.onboarding import (
    get_database_path,
    initialize_onboarding_db,
)

logger = logging.getLogger(__name__)


def serialize_capture_record(item: CaptureRun) -> dict[str, Any]:
    screenshot_url = None
    if item.screenshot_path:
        path = Path(item.screenshot_path)
        screenshot_url = f"/artifacts/{path.parent.name}/{path.name}"

    return {
        "id": item.id,
        "site_id": item.site_id,
        "requested_url": item.requested_url,
        "final_url": item.final_url,
        "page_title": item.page_title,
        "status_code": item.status_code,
        "load_time_ms": item.load_time_ms,
        "html_characters": item.html_characters,
        "cleaned_html_characters": item.cleaned_html_characters,
        "screenshot_url": screenshot_url,
        "cleaned_html_preview": item.cleaned_html_preview,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def _persist_capture_run_sqlite(capture_result, cleaned: str, site_id: int | None) -> int:
    """Fallback insert into capture_runs when SQLAlchemy session is unavailable."""
    initialize_onboarding_db()
    db_path = get_database_path()

    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS capture_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id INTEGER,
                requested_url TEXT NOT NULL,
                final_url TEXT NOT NULL,
                page_title TEXT DEFAULT '',
                status_code INTEGER,
                load_time_ms INTEGER DEFAULT 0,
                html_characters INTEGER DEFAULT 0,
                cleaned_html_characters INTEGER DEFAULT 0,
                screenshot_path TEXT,
                cleaned_html_preview TEXT DEFAULT '',
                created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
            )
        """)
        cur = conn.execute("""
            INSERT INTO capture_runs (
                site_id, requested_url, final_url, page_title,
                status_code, load_time_ms, html_characters,
                cleaned_html_characters, screenshot_path, cleaned_html_preview,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            site_id,
            capture_result.requested_url,
            capture_result.final_url,
            capture_result.page_title or "",
            capture_result.status_code,
            capture_result.load_time_ms,
            len(capture_result.html),
            len(cleaned),
            capture_result.screenshot_path,
            cleaned[:3000],
            datetime.now(timezone.utc).isoformat(),
        ))
        return cur.lastrowid


def _save_extraction_run_sqlite(
    config_id: int,
    url: str,
    records: list,
    diagnostics: dict,
    capture_run_id: int | None,
) -> tuple[int, str]:
    """Insert into extraction_runs and return (new_run_id, created_at_iso)."""
    db_path = get_database_path()
    now_iso = datetime.now(timezone.utc).isoformat()
    diag_copy = dict(diagnostics)
    if capture_run_id is not None:
        diag_copy["capture_id"] = capture_run_id

    with sqlite3.connect(db_path, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout = 30000")
        cur = conn.execute("""
            INSERT INTO extraction_runs (
                config_id, start_url, pages_crawled,
                record_count, records_json, diagnostics_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            config_id,
            url,
            1,
            len(records),
            json.dumps(records, ensure_ascii=False, default=str),
            json.dumps(diag_copy, ensure_ascii=False, default=str),
            now_iso,
        ))
        return cur.lastrowid, now_iso


async def execute_capture_and_extract_pipeline(
    url: str,
    site_id: int | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    """
    Semantic HTML + LLM Structured Extraction pipeline:
    1. Capture rendered webpage with Playwright (SSRF validated).
    2. Save screenshot and raw HTML to disk for auditing.
    3. Save capture record to SQLite.
    4. Ensure a semantic_llm configuration exists for this URL.
    5. Run Semantic Content Extraction -> Batched Groq JSON -> Validation.
    6. Save extraction run and upsert products safely into SQLite.
    """
    initialize_onboarding_db()
    initialize_extraction_db()
    initialize_database_explorer_db()

    site = None
    if db is not None and site_id is not None:
        site = db.get(Site, site_id)

    capture_result = await capture_page(url, "data/snapshots")

    if capture_result.screenshot_path:
        try:
            folder = Path(capture_result.screenshot_path).parent
            raw_html_path = folder / "raw.html"
            raw_html_path.write_text(capture_result.html, encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning("Could not save raw.html: %s", e)

    cleaned = clean_html(capture_result.html, max_chars=settings.max_html_chars)

    capture_run_id: int | None = None
    if db is not None:
        capture_record = CaptureRun(
            site_id=site.id if site else None,
            requested_url=capture_result.requested_url,
            final_url=capture_result.final_url,
            page_title=capture_result.page_title,
            status_code=capture_result.status_code,
            load_time_ms=capture_result.load_time_ms,
            html_characters=len(capture_result.html),
            cleaned_html_characters=len(cleaned),
            screenshot_path=capture_result.screenshot_path,
            cleaned_html_preview=cleaned[:3000],
        )
        db.add(capture_record)
        if site:
            site.status = "captured"
        db.commit()
        db.refresh(capture_record)
        capture_run_id = capture_record.id
        output = serialize_capture_record(capture_record)
    else:
        capture_run_id = _persist_capture_run_sqlite(capture_result, cleaned, site_id)
        screenshot_url = None
        if capture_result.screenshot_path:
            path = Path(capture_result.screenshot_path)
            screenshot_url = f"/artifacts/{path.parent.name}/{path.name}"
        output = {
            "id": capture_run_id,
            "site_id": site_id,
            "requested_url": capture_result.requested_url,
            "final_url": capture_result.final_url,
            "page_title": capture_result.page_title,
            "status_code": capture_result.status_code,
            "load_time_ms": capture_result.load_time_ms,
            "html_characters": len(capture_result.html),
            "cleaned_html_characters": len(cleaned),
            "screenshot_url": screenshot_url,
            "cleaned_html_preview": cleaned[:3000],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    fields = (
        [{"name": f.name, "type": f.data_type, "required": bool(f.required)} for f in site.fields]
        if (site and site.fields)
        else None
    )
    config_id = ensure_semantic_config(capture_result.final_url, fields=fields)

    try:
        records, sem_diag = extract_semantic_products(
            capture_result.html,
            capture_result.final_url,
            config={"fields": {f["name"]: f for f in (fields or [])}} if fields else None,
        )

        validation = sem_diag.get("validation", {})
        diagnostics = {
            "extraction_mode": "semantic_llm",
            "pages_visited": 1,
            "pages_crawled": 1,
            "product_cards_detected": sem_diag.get("product_cards_detected", 0),
            "llm_batches_processed": sem_diag.get("llm_batches_processed", 0),
            "llm_cache_hits": sem_diag.get("llm_cache_hits", 0),
            "products_extracted": len(records),
            "products_validated": validation.get("valid_records", 0),
            "rejected_non_product_count": sem_diag.get("rejected_non_product_count", 0),
            "rejected_non_products": sem_diag.get("rejected_non_products", []),
            "products_inserted": 0,
            "products_updated": 0,
            "duplicates_skipped": 0,
            "failed_records": validation.get("invalid_records", 0),
            "error_messages": sem_diag.get("llm_errors", []),
            "json_ld_count": sem_diag.get("json_ld_count", 0),
            "page_metadata": sem_diag.get("page_metadata", {}),
            "validation": validation,
        }

        run_id, now_iso = _save_extraction_run_sqlite(
            config_id=config_id,
            url=capture_result.final_url,
            records=records,
            diagnostics=diagnostics,
            capture_run_id=capture_run_id,
        )

        sync_stats = sync_run_products(
            run_id=run_id,
            config_id=config_id,
            start_url=capture_result.final_url,
            records=records,
            created_at=now_iso,
        )

        diagnostics["products_inserted"] = sync_stats.saved
        diagnostics["products_updated"] = sync_stats.updated
        diagnostics["duplicates_skipped"] = sync_stats.skipped
        diagnostics["failed_records"] = sync_stats.failed + validation.get("invalid_records", 0)

        with sqlite3.connect(get_database_path(), timeout=30) as conn:
            conn.execute("PRAGMA busy_timeout = 30000")
            conn.execute(
                "UPDATE extraction_runs SET diagnostics_json = ? WHERE id = ?",
                (json.dumps(diagnostics, ensure_ascii=False, default=str), run_id),
            )

        if site and db is not None:
            site.status = "active"
            db.commit()

        output["extraction"] = {
            "status": "completed" if records else "empty",
            "run_id": run_id,
            "config_id": config_id,
            "record_count": len(records),
            "products_saved": sync_stats.saved,
            "products_inserted": sync_stats.saved,
            "products_updated": sync_stats.updated,
            "duplicates_skipped": sync_stats.skipped,
            "failed_records": sync_stats.failed,
            "product_cards_detected": diagnostics["product_cards_detected"],
            "llm_batches_processed": diagnostics["llm_batches_processed"],
            "products_validated": diagnostics["products_validated"],
            "rejected_non_product_count": diagnostics["rejected_non_product_count"],
            "records": records[:5],
            "message": (
                f"Successfully extracted {len(records)} products via semantic LLM pipeline "
                f"({sync_stats.saved} inserted, {sync_stats.updated} updated, {sync_stats.skipped} skipped)."
                if records
                else "Webpage captured, but no product cards were detected on the page."
            ),
            "error": "; ".join(diagnostics["error_messages"]) if diagnostics["error_messages"] else None,
        }
    except Exception as exc:
        logger.error("Semantic extraction failed on captured HTML: %s", exc, exc_info=True)
        output["extraction"] = {
            "status": "failed",
            "run_id": None,
            "config_id": config_id,
            "record_count": 0,
            "products_saved": 0,
            "records": [],
            "message": "Webpage captured successfully but semantic extraction failed.",
            "error": str(exc)[:500],
        }

    return output

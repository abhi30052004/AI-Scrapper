import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.config import settings
from app.models import CaptureRun, Site
from app.services.capture import capture_page
from app.services.cleaner import clean_html
from app.services.extractor import extract_records
from app.services.onboarding import (
    get_database_path,
    initialize_onboarding_db,
    run_onboarding,
    save_config,
)
from app.services.extraction_service import initialize_extraction_db
from app.services.database_explorer_service import (
    initialize_database_explorer_db,
    sync_run_products,
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


def find_compatible_config(url: str, html: str) -> tuple[dict[str, Any] | None, int | None]:
    """
    Search existing configurations in scraper_configs that belong to this website
    and test whether they successfully extract records from the captured HTML.
    Never reuses an incompatible configuration (e.g. Books to Scrape on Amazon).
    """
    initialize_onboarding_db()
    parsed_target = urlparse(url)
    target_netloc = parsed_target.netloc.lower()

    with sqlite3.connect(get_database_path()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT id, site_url, version, config_json, status
            FROM scraper_configs
            ORDER BY id DESC
        """).fetchall()

    for row in rows:
        row_url = row["site_url"]
        row_netloc = urlparse(row_url).netloc.lower()

        # Only reuse configs for the same domain
        if row_netloc and target_netloc and (
            row_netloc == target_netloc
            or row_netloc.endswith(f".{target_netloc}")
            or target_netloc.endswith(f".{row_netloc}")
        ):
            try:
                cfg = json.loads(row["config_json"])
                if isinstance(cfg, dict) and cfg.get("item_selector"):
                    records, _ = extract_records(html, cfg, url)
                    if records and len(records) > 0:
                        logger.info(
                            f"Reusing compatible configuration #{row['id']} "
                            f"(extracted {len(records)} items)"
                        )
                        return cfg, row["id"]
            except Exception as e:
                logger.debug(f"Config #{row['id']} not compatible: {e}")

    return None, None


def _persist_capture_run_sqlite(capture_result, cleaned: str, site_id: int | None) -> int:
    """
    Fallback: insert capture_run directly via sqlite3 when SQLAlchemy session is unavailable,
    or when we need to ensure the row exists before reading its id.
    Returns the new row id.
    """
    initialize_onboarding_db()
    db_path = get_database_path()

    # Ensure capture_runs table exists (created by SQLAlchemy Base.metadata.create_all)
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
) -> int:
    """Insert into extraction_runs and return the new run id."""
    db_path = get_database_path()
    now_iso = datetime.now(timezone.utc).isoformat()
    diag_copy = dict(diagnostics)
    if capture_run_id is not None:
        diag_copy["capture_id"] = capture_run_id

    with sqlite3.connect(db_path) as conn:
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
            json.dumps(records, ensure_ascii=False),
            json.dumps(diag_copy, ensure_ascii=False),
            now_iso,
        ))
        return cur.lastrowid, now_iso


async def execute_capture_and_extract_pipeline(
    url: str,
    site_id: int | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    """
    Automated workflow:
    1. Capture webpage with Playwright (SSRF validated).
    2. Save screenshot and raw HTML to disk.
    3. Save capture record to SQLite (via SQLAlchemy if db provided, else raw sqlite3).
    4. Find compatible configuration or generate one via AI onboarding.
    5. Extract records directly from captured HTML.
    6. Save extraction run and products to SQLite.
    7. Return unified capture+extraction data with explicit error messages on failure.
    """
    initialize_onboarding_db()
    initialize_extraction_db()
    initialize_database_explorer_db()

    site = None
    if db is not None and site_id is not None:
        site = db.get(Site, site_id)

    # ── Step 1: Capture webpage ───────────────────────────────────────────────
    capture_result = await capture_page(url, "data/snapshots")

    # ── Step 2: Save raw HTML to disk alongside screenshot ───────────────────
    if capture_result.screenshot_path:
        try:
            folder = Path(capture_result.screenshot_path).parent
            raw_html_path = folder / "raw.html"
            raw_html_path.write_text(capture_result.html, encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"Could not save raw.html: {e}")

    # ── Step 3: Clean HTML ────────────────────────────────────────────────────
    cleaned = clean_html(capture_result.html, max_chars=settings.max_html_chars)

    # ── Step 4: Persist CaptureRun ───────────────────────────────────────────
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

    logger.info(
        f"Capture saved: id={capture_run_id} url={capture_result.final_url} "
        f"status={capture_result.status_code} html={len(capture_result.html)} chars"
    )

    # ── Step 5: Find or generate extraction configuration ────────────────────
    matched_config, config_id = find_compatible_config(capture_result.final_url, capture_result.html)
    ai_error: str | None = None

    if not matched_config:
        # Build field list from site definition or use sensible defaults
        if site and site.fields:
            fields = [
                {"name": f.name, "type": f.data_type, "required": bool(f.required)}
                for f in site.fields
            ]
        else:
            fields = [
                {"name": "title",        "type": "string", "required": True},
                {"name": "price",        "type": "string", "required": True},
                {"name": "rating",       "type": "string", "required": False},
                {"name": "availability", "type": "string", "required": False},
                {"name": "product_url",  "type": "string", "required": False},
            ]

        try:
            onboard_res = run_onboarding(
                url=capture_result.final_url,
                fields=fields,
                html=capture_result.html,
            )
            saved = save_config(capture_result.final_url, onboard_res)
            matched_config = onboard_res["config"]
            config_id = saved["id"]
            logger.info(
                f"AI generated new config #{config_id} for {capture_result.final_url} "
                f"with {len(onboard_res['records'])} sample records"
            )
        except Exception as exc:
            ai_error = str(exc)
            logger.warning(
                f"Could not automatically generate configuration for {url}: {exc}"
            )
            output["extraction"] = {
                "status": "needs_configuration",
                "run_id": None,
                "config_id": None,
                "record_count": 0,
                "records": [],
                "message": (
                    "Webpage captured and saved successfully. "
                    "Automatic AI configuration generation failed — "
                    "please check your GROQ_API_KEY and network connectivity, "
                    "then retry or manually configure field selectors."
                ),
                "error": ai_error[:500] if ai_error else None,
            }
            return output

    # ── Step 6: Extract records from captured HTML ───────────────────────────
    try:
        records, diagnostics = extract_records(
            capture_result.html,
            matched_config,
            capture_result.final_url,
        )

        logger.info(
            f"Extracted {len(records)} records from {capture_result.final_url} "
            f"using config #{config_id}"
        )

        # ── Step 7: Persist extraction_run ───────────────────────────────────
        run_id, now_iso = _save_extraction_run_sqlite(
            config_id=config_id,
            url=url,
            records=records,
            diagnostics=diagnostics,
            capture_run_id=capture_run_id,
        )
        logger.info(f"Saved extraction_run id={run_id}")

        # ── Step 8: Sync products table ──────────────────────────────────────
        products_saved = 0
        if records:
            products_saved = sync_run_products(
                run_id=run_id,
                config_id=config_id,
                start_url=url,
                records=records,
                created_at=now_iso,
            )
            logger.info(f"Saved {products_saved} products from run #{run_id}")
        else:
            logger.warning(
                f"Config #{config_id} extracted 0 records from {capture_result.final_url}. "
                "Selectors may need updating."
            )

        if site and db is not None:
            site.status = "active"
            db.commit()

        output["extraction"] = {
            "status": "completed" if records else "empty",
            "run_id": run_id,
            "config_id": config_id,
            "record_count": len(records),
            "products_saved": products_saved,
            "records": records[:5],
            "message": (
                f"Successfully extracted and saved {len(records)} products from captured HTML."
                if records
                else (
                    "Capture and configuration succeeded, but 0 products matched the selectors. "
                    "The page structure may differ from what the AI expected. "
                    "Try reconfiguring the selectors."
                )
            ),
            "error": None,
        }

    except Exception as exc:
        logger.error(f"Extraction failed on captured HTML: {exc}", exc_info=True)
        output["extraction"] = {
            "status": "failed",
            "run_id": None,
            "config_id": config_id,
            "record_count": 0,
            "products_saved": 0,
            "records": [],
            "message": "Webpage captured successfully but extraction failed.",
            "error": str(exc)[:500],
        }

    return output

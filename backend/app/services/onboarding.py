
import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

from app.services.ai_client import generate_config
from app.services.extractor import extract_records


ALLOWED_TRANSFORMS = {
    "strip", "strip_currency", "to_number",
    "to_date", "lowercase", "absolute_url",
}


def get_database_path():
    database_url = os.getenv(
        "DATABASE_URL", "sqlite:///./data/scraper.db"
    )

    if not database_url.startswith("sqlite:///"):
        raise RuntimeError(
            "This onboarding implementation currently requires SQLite"
        )

    path = database_url.replace("sqlite:///", "", 1)
    db_path = Path(path)

    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path

    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def initialize_onboarding_db():
    with sqlite3.connect(get_database_path()) as conn:
                conn.execute("""
            CREATE TABLE IF NOT EXISTS repair_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_config_id INTEGER NOT NULL,
                site_url TEXT NOT NULL,
                status TEXT NOT NULL,
                confidence REAL NOT NULL,
                ai_confidence REAL,
                reason TEXT,
                failure_report_json TEXT NOT NULL,
                proposed_config_json TEXT NOT NULL,
                sample_records_json TEXT NOT NULL,
                saved_config_id INTEGER,
                reviewed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


def validate_config(config, fields, url):
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a JSON object")

    if config.get("version") != 1:
        raise ValueError("Unsupported config version")

    if config.get("start_url") != url:
        raise ValueError("Config URL does not match requested URL")

    item_selector = config.get("item_selector")
    if not isinstance(item_selector, str) or not item_selector.strip():
        raise ValueError("Invalid item_selector")

    if not isinstance(config.get("fields"), dict):
        raise ValueError("Config fields must be an object")

    requested_names = {field["name"] for field in fields}
    generated_names = set(config["fields"])

    if requested_names != generated_names:
        raise ValueError("Generated fields do not match requested fields")

    for name, definition in config["fields"].items():
        if not isinstance(definition, dict):
            raise ValueError(f"Invalid definition for {name}")

        selectors = definition.get("selectors")
        if not isinstance(selectors, list):
            raise ValueError(f"Selectors must be a list for {name}")

        if len(selectors) > 3:
            raise ValueError(f"Too many selectors for {name}")

        for selector in selectors:
            if not isinstance(selector, str) or not selector.strip():
                raise ValueError(f"Invalid selector for {name}")

        attr = definition.get("attr", "text")
        if not isinstance(attr, str) or not attr.strip():
            raise ValueError(f"Invalid attribute for {name}")

        transform = definition.get("transform", "strip")
        if transform not in ALLOWED_TRANSFORMS:
            raise ValueError(f"Unsupported transform for {name}")

        if not isinstance(definition.get("required", False), bool):
            raise ValueError(f"Invalid required flag for {name}")

    return True


def run_onboarding(url, fields, html):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("A valid HTTP or HTTPS URL is required")

    if not fields:
        raise ValueError("At least one field is required")

    names = [field["name"] for field in fields]
    if len(names) != len(set(names)):
        raise ValueError("Field names must be unique")

    for field in fields:
        if not isinstance(field.get("name"), str) or not field["name"].strip():
            raise ValueError("Each field needs a valid name")

    config = generate_config(url, fields, html)
    validate_config(config, fields, url)

    records, diagnostics = extract_records(html, config, url)

    required_fields = [
        field["name"] for field in fields
        if field.get("required", True)
    ]

    if not records:
        raise ValueError(
            "No records were extracted. Review the generated selectors."
        )

    total = len(records) * len(required_fields)
    filled = sum(
        1
        for record in records
        for name in required_fields
        if record.get(name) is not None
    )

    confidence = filled / total if total else 1.0

    return {
        "config": config,
        "records": records,
        "diagnostics": diagnostics,
        "confidence": round(confidence, 3),
        "status": (
            "ready_for_review" if confidence >= 0.60
            else "needs_review"
        ),
    }


def save_config(url, result):
    initialize_onboarding_db()

    with sqlite3.connect(get_database_path()) as conn:
        current = conn.execute(
            "SELECT MAX(version) FROM scraper_configs WHERE site_url = ?",
            (url,),
        ).fetchone()[0]

        version = (current or 0) + 1

        cursor = conn.execute(
            """
            INSERT INTO scraper_configs
            (site_url, version, config_json, sample_records,
             confidence, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                url,
                version,
                json.dumps(result["config"]),
                json.dumps(result["records"]),
                result["confidence"],
                result["status"],
            ),
        )

        return {"id": cursor.lastrowid, "version": version}

def save_repair_history(
    original_config_id: int,
    site_url: str,
    status: str,
    confidence: float,
    ai_confidence: float | None,
    reason: str | None,
    failure_report: dict,
    proposed_config: dict,
    sample_records: list,
    saved_config_id: int | None = None,
):
    """Persist one self-healing attempt in SQLite."""

    initialize_onboarding_db()

    with sqlite3.connect(get_database_path()) as conn:
        cursor = conn.execute(
            """
            INSERT INTO repair_history (
                original_config_id,
                site_url,
                status,
                confidence,
                ai_confidence,
                reason,
                failure_report_json,
                proposed_config_json,
                sample_records_json,
                saved_config_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                original_config_id,
                site_url,
                status,
                confidence,
                ai_confidence,
                reason,
                json.dumps(failure_report),
                json.dumps(proposed_config),
                json.dumps(sample_records),
                saved_config_id,
            ),
        )

        return cursor.lastrowid

def list_repair_history():
    """Return all saved repair attempts."""

    initialize_onboarding_db()

    with sqlite3.connect(get_database_path()) as conn:
        conn.row_factory = sqlite3.Row

        rows = conn.execute(
            """
            SELECT *
            FROM repair_history
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()

    results = []

    for row in rows:
        item = dict(row)

        item["failure_report"] = json.loads(
            item.pop("failure_report_json")
        )
        item["proposed_config"] = json.loads(
            item.pop("proposed_config_json")
        )
        item["sample_records"] = json.loads(
            item.pop("sample_records_json")
        )

        results.append(item)

    return results


def get_repair_history(repair_id: int):
    """Return one repair attempt by ID."""

    initialize_onboarding_db()

    with sqlite3.connect(get_database_path()) as conn:
        conn.row_factory = sqlite3.Row

        row = conn.execute(
            """
            SELECT *
            FROM repair_history
            WHERE id = ?
            """,
            (repair_id,),
        ).fetchone()

    if not row:
        return None

    item = dict(row)

    item["failure_report"] = json.loads(
        item.pop("failure_report_json")
    )
    item["proposed_config"] = json.loads(
        item.pop("proposed_config_json")
    )
    item["sample_records"] = json.loads(
        item.pop("sample_records_json")
    )

    return item

def update_repair_review(
    repair_id: int,
    status: str,
    saved_config_id: int | None = None,
):
    """Record a human review decision."""

    if status not in ("approved", "rejected_by_human"):
        raise ValueError("Invalid review status")

    initialize_onboarding_db()

    with sqlite3.connect(get_database_path()) as conn:
        cursor = conn.execute(
            """
            UPDATE repair_history
            SET status = ?,
                saved_config_id = ?,
                reviewed_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND status = 'human_review_required'
            """,
            (status, saved_config_id, repair_id),
        )

        return cursor.rowcount
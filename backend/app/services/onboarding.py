
import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

from app.config import settings
from app.services.ai_client import generate_config
from app.services.extractor import extract_records, ALLOWED_TRANSFORMS
from app.services.validation_service import validate_records


def get_database_path():
    database_url = getattr(settings, "database_url", None) or os.getenv(
        "DATABASE_URL", "sqlite:///./data/scraper.db"
    )

    if not database_url.startswith("sqlite:///"):
        raise RuntimeError(
            "This onboarding implementation currently requires SQLite"
        )

    path = database_url.replace("sqlite:///", "", 1)
    # Strip any leading ./ or .\
    clean_path = path.lstrip("./").lstrip(".\\")
    backend_dir = Path(__file__).resolve().parents[2]

    # If already absolute
    if Path(path).is_absolute():
        db_path = Path(path)
    elif (backend_dir / clean_path).exists():
        db_path = backend_dir / clean_path
    elif (Path.cwd() / clean_path).exists():
        db_path = Path.cwd() / clean_path
    else:
        db_path = backend_dir / clean_path

    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def initialize_onboarding_db():
    with sqlite3.connect(get_database_path()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scraper_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_url TEXT NOT NULL,
                version INTEGER NOT NULL,
                config_json TEXT NOT NULL,
                sample_records TEXT NOT NULL,
                confidence REAL NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
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

    # Accept URLs that differ only by trailing slash
    if config.get("start_url", "").rstrip("/") != url.rstrip("/"):
        raise ValueError("Config URL does not match requested URL")

    item_selector = config.get("item_selector")
    if not isinstance(item_selector, str) or not item_selector.strip():
        raise ValueError("Invalid item_selector")

    if not isinstance(config.get("fields"), dict):
        raise ValueError("Config fields must be an object")

    # Normalize fields if selectors is provided as a string
    for name, definition in config["fields"].items():
        if isinstance(definition, dict):
            if isinstance(definition.get("selectors"), str):
                definition["selectors"] = [definition["selectors"]]

    requested_names = {field["name"] for field in fields}
    
    # If any optional requested field was omitted by the AI, supply an empty definition
    for f in fields:
        fname = f["name"]
        if fname not in config["fields"] and not f.get("required", False):
            config["fields"][fname] = {
                "selectors": [],
                "attr": "text",
                "type": f.get("type", "string"),
                "required": False,
                "transform": "strip",
            }
            
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

    validation = validate_records(records, config)
    confidence = validation["confidence"]
    status = "ready_for_review" if validation["is_valid"] and confidence >= 0.80 else "needs_review"
    diagnostics["validation"] = validation

    return {
        "config": config,
        "records": records,
        "diagnostics": diagnostics,
        "confidence": round(confidence, 3),
        "status": status,
        "validation": validation,
        "failed_fields": validation.get("failed_fields", []),
        "explanation": "; ".join(validation.get("validation_errors", [])) if not validation["is_valid"] else "Configuration passed sample record validation.",
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

import json
import sqlite3
from datetime import datetime, timezone

from app.services.extraction_service import (
    get_database_path,
    initialize_extraction_db,
    get_extraction_run,
)


def initialize_change_detection_db():
    initialize_extraction_db()

    with sqlite3.connect(get_database_path()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS change_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                config_id INTEGER NOT NULL,
                old_run_id INTEGER NOT NULL,
                new_run_id INTEGER NOT NULL,
                added_count INTEGER NOT NULL,
                removed_count INTEGER NOT NULL,
                modified_count INTEGER NOT NULL,
                unchanged_count INTEGER NOT NULL,
                changes_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(old_run_id, new_run_id)
            )
        """)


def compare_extractions(old_run_id: int, new_run_id: int):
    if old_run_id == new_run_id:
        raise ValueError("Cannot compare an extraction run with itself")

    old_run = get_extraction_run(old_run_id)
    new_run = get_extraction_run(new_run_id)

    if old_run["config_id"] != new_run["config_id"]:
        raise ValueError(
            "Both extraction runs must use the same configuration"
        )

    old_records = old_run["records"]
    new_records = new_run["records"]

    def create_index(records):
        index = {}

        for record in records:
            product_id = record.get("product_url")

            if not product_id:
                raise ValueError(
                    "Every record must contain product_url"
                )

            if product_id in index:
                raise ValueError(
                    f"Duplicate product_url found: {product_id}"
                )

            index[product_id] = record

        return index

    old_index = create_index(old_records)
    new_index = create_index(new_records)

    added = []
    removed = []
    modified = []
    unchanged = []

    for product_id, new_record in new_index.items():
        old_record = old_index.get(product_id)

        if old_record is None:
            added.append({
                "product_url": product_id,
                "record": new_record,
            })
            continue

        field_changes = {}

        all_fields = set(old_record) | set(new_record)

        for field in sorted(all_fields):
            old_value = old_record.get(field)
            new_value = new_record.get(field)

            if old_value != new_value:
                field_changes[field] = {
                    "old": old_value,
                    "new": new_value,
                }

        if field_changes:
            modified.append({
                "product_url": product_id,
                "changes": field_changes,
            })
        else:
            unchanged.append(product_id)

    for product_id, old_record in old_index.items():
        if product_id not in new_index:
            removed.append({
                "product_url": product_id,
                "record": old_record,
            })

    return {
        "config_id": old_run["config_id"],
        "old_run_id": old_run_id,
        "new_run_id": new_run_id,
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "modified": len(modified),
            "unchanged": len(unchanged),
        },
        "changes": {
            "added": added,
            "removed": removed,
            "modified": modified,
            "unchanged": unchanged,
        },
    }


def save_change_report(report: dict):
    initialize_change_detection_db()

    summary = report["summary"]

    with sqlite3.connect(get_database_path()) as conn:
        existing = conn.execute(
            """
            SELECT id
            FROM change_reports
            WHERE old_run_id = ? AND new_run_id = ?
            """,
            (
                report["old_run_id"],
                report["new_run_id"],
            ),
        ).fetchone()

        if existing:
            raise ValueError(
                f"Change report already exists with ID {existing[0]}"
            )

        cursor = conn.execute(
            """
            INSERT INTO change_reports (
                config_id,
                old_run_id,
                new_run_id,
                added_count,
                removed_count,
                modified_count,
                unchanged_count,
                changes_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report["config_id"],
                report["old_run_id"],
                report["new_run_id"],
                summary["added"],
                summary["removed"],
                summary["modified"],
                summary["unchanged"],
                json.dumps(report["changes"], ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
            ),
        )

        return cursor.lastrowid


def run_change_detection(old_run_id: int, new_run_id: int):
    report = compare_extractions(old_run_id, new_run_id)
    report_id = save_change_report(report)

    return {
        "message": "Change detection completed",
        "report_id": report_id,
        **report,
    }


def list_change_reports():
    initialize_change_detection_db()

    with sqlite3.connect(get_database_path()) as conn:
        conn.row_factory = sqlite3.Row

        rows = conn.execute("""
            SELECT
                id,
                config_id,
                old_run_id,
                new_run_id,
                added_count,
                removed_count,
                modified_count,
                unchanged_count,
                created_at
            FROM change_reports
            ORDER BY id DESC
        """).fetchall()

    return [dict(row) for row in rows]


def get_change_report(report_id: int):
    initialize_change_detection_db()

    with sqlite3.connect(get_database_path()) as conn:
        conn.row_factory = sqlite3.Row

        row = conn.execute(
            """
            SELECT *
            FROM change_reports
            WHERE id = ?
            """,
            (report_id,),
        ).fetchone()

    if row is None:
        raise ValueError(
            f"Change report {report_id} was not found"
        )

    result = dict(row)
    result["changes"] = json.loads(result.pop("changes_json"))

    return result

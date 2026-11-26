import csv
import io
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.onboarding import get_database_path

ALLOWED_TABLES = {
    "sites",
    "site_fields",
    "capture_runs",
    "scraper_configs",
    "extraction_runs",
    "products",
    "change_reports",
    "repair_history",
}


def initialize_database_explorer_db() -> int:
    """Initialize the products table if it doesn't exist."""
    db_path = get_database_path()
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                config_id INTEGER,
                site_id INTEGER,
                site_name TEXT,
                title TEXT,
                price TEXT,
                rating TEXT,
                availability TEXT,
                product_url TEXT,
                scraped_at TEXT,
                raw_data_json TEXT,
                FOREIGN KEY(run_id) REFERENCES extraction_runs(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_products_run_id ON products(run_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_products_site_id ON products(site_id)")

        return conn.execute("SELECT count(*) FROM products").fetchone()[0]


class SyncResult(int):
    """Integer-compatible summary of database synchronization statistics."""
    saved: int
    updated: int
    skipped: int
    failed: int
    total: int

    def __new__(cls, saved=0, updated=0, skipped=0, failed=0, total=0):
        instance = super().__new__(cls, saved)
        instance.saved = saved
        instance.updated = updated
        instance.skipped = skipped
        instance.failed = failed
        instance.total = total
        return instance

    def to_dict(self) -> dict[str, int]:
        return {
            "saved": self.saved,
            "updated": self.updated,
            "skipped": self.skipped,
            "failed": self.failed,
            "total": self.total,
        }


def sync_run_products(
    run_id: int,
    config_id: int,
    start_url: str,
    records: list[dict],
    created_at: str,
) -> SyncResult:
    """
    Persist products idempotently.

    A product with a canonical URL is maintained as one current row per site.
    Re-scraping updates known values but never replaces a previously known value
    with an empty value. The complete latest record is merged into raw_data_json.
    Records without a URL are deduplicated within this run only.
    """
    initialize_database_explorer_db()
    db_path = get_database_path()

    def clean_text(value):
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    def canonicalize(value):
        from app.services.extractor import canonicalize_product_url
        if not value:
            return None
        return canonicalize_product_url(str(value).strip(), start_url) or None

    with sqlite3.connect(db_path, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        site_row = conn.execute("""
            SELECT id, name FROM sites
            WHERE url = ? OR url = RTRIM(?, '/') OR RTRIM(url, '/') = RTRIM(?, '/')
            LIMIT 1
        """, (start_url, start_url, start_url)).fetchone()

        site_id = site_row["id"] if site_row else None
        site_name = site_row["name"] if site_row else start_url

        # Ensure unique index exists without ever deleting existing product records
        try:
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_products_site_url
                ON products(COALESCE(site_id, -1), RTRIM(product_url, '/'))
                WHERE product_url IS NOT NULL AND TRIM(product_url) <> ''
            """)
        except sqlite3.IntegrityError:
            pass

        saved = 0
        updated = 0
        skipped = 0
        failed = 0
        affected = 0
        seen_without_url = set()
        seen_canonical_in_batch = set()

        def _non_empty_merge(prev: dict, inc: dict) -> dict:
            merged = dict(prev)
            for k, v in inc.items():
                if v in (None, "", [], {}):
                    continue
                existing_val = merged.get(k)
                if k == "specifications" and isinstance(v, dict):
                    prev_s = existing_val if isinstance(existing_val, dict) else {}
                    merged["specifications"] = {**prev_s, **v}
                elif k == "image_urls" and isinstance(v, list):
                    prev_i = existing_val if isinstance(existing_val, list) else []
                    merged["image_urls"] = list(dict.fromkeys(prev_i + v))
                else:
                    merged[k] = v
            return merged

        from app.services.validation_service import is_genuine_product

        for rec in records:
            if not isinstance(rec, dict):
                failed += 1
                continue
            try:
                is_prod, _ = is_genuine_product(rec)
                if not is_prod:
                    skipped += 1
                    continue

                title = clean_text(rec.get("title") or rec.get("name") or rec.get("product_name"))
                price = clean_text(rec.get("price"))
                rating = clean_text(rec.get("rating"))
                availability = clean_text(rec.get("availability"))
                product_url = clean_text(rec.get("product_url") or rec.get("url"))
                canonical_url = canonicalize(product_url)

                # Reject completely empty or invalid-only records
                if not title and not canonical_url:
                    failed += 1
                    continue

                raw_json = json.dumps(rec, ensure_ascii=False, default=str)

                if not canonical_url:
                    fingerprint = json.dumps(rec, sort_keys=True, ensure_ascii=False, default=str)
                    if fingerprint in seen_without_url:
                        skipped += 1
                        continue
                    seen_without_url.add(fingerprint)
                    conn.execute("""
                        INSERT INTO products (
                            run_id, config_id, site_id, site_name, title, price,
                            rating, availability, product_url, scraped_at, raw_data_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (run_id, config_id, site_id, site_name, title, price,
                          rating, availability, None, created_at, raw_json))
                    saved += 1
                    affected += 1
                    continue

                if canonical_url in seen_canonical_in_batch:
                    skipped += 1
                    continue
                seen_canonical_in_batch.add(canonical_url)

                existing = conn.execute("""
                    SELECT * FROM products
                    WHERE COALESCE(site_id, -1) = COALESCE(?, -1)
                      AND RTRIM(product_url, '/') = RTRIM(?, '/')
                    LIMIT 1
                """, (site_id, canonical_url)).fetchone()

                if existing:
                    try:
                        previous_raw = json.loads(existing["raw_data_json"] or "{}")
                        if not isinstance(previous_raw, dict):
                            previous_raw = {}
                    except (TypeError, ValueError):
                        previous_raw = {}

                    merged_raw = _non_empty_merge(previous_raw, rec)
                    new_title = title or existing["title"]
                    new_price = price or existing["price"]
                    new_rating = rating or existing["rating"]
                    new_avail = availability or existing["availability"]

                    transient_keys = {"extraction_source", "card_index", "raw_html_audit"}
                    prev_comparable = {k: v for k, v in previous_raw.items() if k not in transient_keys}
                    merged_comparable = {k: v for k, v in merged_raw.items() if k not in transient_keys}

                    data_changed = (
                        new_title != existing["title"]
                        or new_price != existing["price"]
                        or new_rating != existing["rating"]
                        or new_avail != existing["availability"]
                        or merged_comparable != prev_comparable
                    )

                    if data_changed:
                        conn.execute("""
                            UPDATE products
                            SET run_id = ?, config_id = ?, site_name = ?,
                                title = ?, price = ?, rating = ?, availability = ?,
                                product_url = ?, scraped_at = ?, raw_data_json = ?
                            WHERE id = ?
                        """, (
                            run_id, config_id, site_name,
                            new_title, new_price, new_rating, new_avail,
                            canonical_url, created_at,
                            json.dumps(merged_raw, ensure_ascii=False, default=str),
                            existing["id"],
                        ))
                        updated += 1
                    else:
                        conn.execute("""
                            UPDATE products
                            SET run_id = ?, scraped_at = ?
                            WHERE id = ?
                        """, (run_id, created_at, existing["id"]))
                        skipped += 1
                else:
                    conn.execute("""
                        INSERT INTO products (
                            run_id, config_id, site_id, site_name, title, price,
                            rating, availability, product_url, scraped_at, raw_data_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (run_id, config_id, site_id, site_name, title, price,
                          rating, availability, canonical_url, created_at, raw_json))
                    saved += 1
                affected += 1
            except Exception:
                failed += 1

        return SyncResult(saved=saved, updated=updated, skipped=skipped, failed=failed, total=affected)


def get_database_overview() -> dict[str, Any]:
    """Retrieve full database metadata, connection status, table statistics and record counts."""
    initialize_database_explorer_db()
    db_path = get_database_path()

    if not db_path.exists():
        return {
            "connection_status": "disconnected",
            "database_name": db_path.name,
            "database_size_bytes": 0,
            "database_size_formatted": "0 B",
            "total_tables": 0,
            "total_products": 0,
            "total_sites": 0,
            "total_runs": 0,
            "latest_scraping_timestamp": None,
            "tables": [],
        }

    size_bytes = db_path.stat().st_size
    if size_bytes < 1024:
        size_str = f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        size_str = f"{size_bytes / 1024:.1f} KB"
    else:
        size_str = f"{size_bytes / (1024 * 1024):.1f} MB"

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        existing_tables = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]

        table_details = []
        for t in sorted(existing_tables):
            if t in ALLOWED_TABLES:
                row_count = conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
                cols = conn.execute(f'PRAGMA table_info("{t}")').fetchall()
                table_details.append({
                    "name": t,
                    "row_count": row_count,
                    "column_count": len(cols),
                })

        # Key stats
        total_products = conn.execute("SELECT count(*) FROM products").fetchone()[0] if "products" in existing_tables else 0
        total_sites = conn.execute("SELECT count(*) FROM sites").fetchone()[0] if "sites" in existing_tables else 0
        total_runs = conn.execute("SELECT count(*) FROM extraction_runs").fetchone()[0] if "extraction_runs" in existing_tables else 0

        latest_run_ts = None
        if "extraction_runs" in existing_tables:
            latest_row = conn.execute("SELECT created_at FROM extraction_runs ORDER BY id DESC LIMIT 1").fetchone()
            if latest_row and latest_row[0]:
                latest_run_ts = latest_row[0]

    return {
        "connection_status": "connected",
        "database_name": db_path.name,
        "database_size_bytes": size_bytes,
        "database_size_formatted": size_str,
        "total_tables": len(table_details),
        "total_products": total_products,
        "total_sites": total_sites,
        "total_runs": total_runs,
        "latest_scraping_timestamp": latest_run_ts,
        "tables": table_details,
    }


def get_database_tables_metadata() -> list[dict[str, Any]]:
    """List all permitted database tables with column names, data types, and row counts."""
    initialize_database_explorer_db()
    db_path = get_database_path()

    results = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        existing_tables = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]

        for t in sorted(existing_tables):
            if t in ALLOWED_TABLES:
                count = conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
                cols_raw = conn.execute(f'PRAGMA table_info("{t}")').fetchall()
                columns = [
                    {
                        "name": col["name"],
                        "type": col["type"] or "TEXT",
                        "primary_key": bool(col["pk"]),
                        "not_null": bool(col["notnull"]),
                    }
                    for col in cols_raw
                ]
                results.append({
                    "name": t,
                    "row_count": count,
                    "columns": columns,
                })

    return results


def get_table_data(
    table_name: str,
    page: int = 1,
    limit: int = 20,
    sort_by: str | None = None,
    sort_order: str = "desc",
) -> dict[str, Any]:
    """Safely query a permitted SQLite table with pagination and column inspection."""
    if table_name not in ALLOWED_TABLES:
        raise ValueError(f"Access to table '{table_name}' is not permitted.")

    initialize_database_explorer_db()
    db_path = get_database_path()

    page = max(1, page)
    limit = max(1, min(100, limit))
    offset = (page - 1) * limit

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        # Verify table existence in master
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
            (table_name,)
        ).fetchone()
        if not table_exists:
            raise ValueError(f"Table '{table_name}' does not exist.")

        # Inspect columns
        cols_raw = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        columns = [
            {
                "name": col["name"],
                "type": col["type"] or "TEXT",
                "primary_key": bool(col["pk"]),
            }
            for col in cols_raw
        ]
        column_names = {c["name"] for c in columns}

        # Determine primary key or default sort column
        pk_col = next((c["name"] for c in columns if c["primary_key"]), None)
        order_col = sort_by if sort_by in column_names else (pk_col or (columns[0]["name"] if columns else "rowid"))
        order_dir = "ASC" if sort_order.lower() == "asc" else "DESC"

        # Total count
        total_records = conn.execute(f'SELECT count(*) FROM "{table_name}"').fetchone()[0]

        # Fetch page records
        query = f'SELECT * FROM "{table_name}" ORDER BY "{order_col}" {order_dir} LIMIT ? OFFSET ?'
        rows = conn.execute(query, (limit, offset)).fetchall()

        records = [dict(r) for r in rows]
        total_pages = max(1, (total_records + limit - 1) // limit) if total_records > 0 else 1

        return {
            "table_name": table_name,
            "columns": columns,
            "total_records": total_records,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "records": records,
        }


def search_products(
    search: str | None = None,
    site_id: int | None = None,
    run_id: int | None = None,
    page: int = 1,
    limit: int = 20,
    sort_by: str = "id",
    sort_order: str = "desc",
) -> dict[str, Any]:
    """Search and filter the products table with pagination and metadata."""
    initialize_database_explorer_db()
    db_path = get_database_path()

    page = max(1, page)
    limit = max(1, min(100, limit))
    offset = (page - 1) * limit

    allowed_sort_cols = {
        "id", "title", "price", "rating", "availability",
        "product_url", "scraped_at", "run_id", "site_name", "site_id"
    }
    order_col = sort_by if sort_by in allowed_sort_cols else "id"
    order_dir = "ASC" if sort_order.lower() == "asc" else "DESC"

    where_clauses = []
    params: list[Any] = []

    if search and search.strip():
        term = f"%{search.strip()}%"
        where_clauses.append("(title LIKE ? OR product_url LIKE ? OR site_name LIKE ?)")
        params.extend([term, term, term])

    if site_id is not None:
        where_clauses.append("site_id = ?")
        params.append(site_id)

    if run_id is not None:
        where_clauses.append("run_id = ?")
        params.append(run_id)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        count_query = f"SELECT count(*) FROM products {where_sql}"
        total = conn.execute(count_query, params).fetchone()[0]

        select_query = f"""
            SELECT * FROM products
            {where_sql}
            ORDER BY "{order_col}" {order_dir}
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(select_query, params + [limit, offset]).fetchall()

        products = []
        for r in rows:
            item = dict(r)
            raw = None
            if item.get("raw_data_json"):
                try:
                    raw = json.loads(item["raw_data_json"])
                except Exception:
                    raw = None
            item["raw_data"] = raw
            products.append(item)

        total_pages = max(1, (total + limit - 1) // limit) if total > 0 else 1

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "products": products,
        }


def get_recent_products(limit: int = 20) -> list[dict[str, Any]]:
    """Retrieve the latest scraped products."""
    result = search_products(page=1, limit=limit, sort_by="id", sort_order="desc")
    return result["products"]


def clear_table(table_name: str) -> dict:
    """Delete all rows from a single allowed table and reset its auto-increment counter."""
    if table_name not in ALLOWED_TABLES:
        raise ValueError(f"Access to table '{table_name}' is not permitted.")

    db_path = get_database_path()
    with sqlite3.connect(db_path) as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
        ).fetchone()
        if not exists:
            raise ValueError(f"Table '{table_name}' does not exist.")

        count_before = conn.execute(f'SELECT count(*) FROM "{table_name}"').fetchone()[0]
        conn.execute(f'DELETE FROM "{table_name}"')
        # Reset auto-increment sequence if present
        try:
            conn.execute("DELETE FROM sqlite_sequence WHERE name=?", (table_name,))
        except Exception:
            pass

    return {
        "table": table_name,
        "rows_deleted": count_before,
        "message": f"Cleared {count_before} row(s) from table '{table_name}'.",
    }


def clear_all_tables() -> dict:
    """Delete all rows from every allowed data table, in FK-safe order."""
    deletion_order = [
        "products",
        "extraction_runs",
        "change_reports",
        "repair_history",
        "scraper_configs",
        "capture_runs",
        "site_fields",
        "sites",
    ]

    db_path = get_database_path()
    results: dict[str, int] = {}
    total_deleted = 0

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            for table_name in deletion_order:
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
                ).fetchone()
                if not exists:
                    continue
                count = conn.execute(f'SELECT count(*) FROM "{table_name}"').fetchone()[0]
                conn.execute(f'DELETE FROM "{table_name}"')
                try:
                    conn.execute("DELETE FROM sqlite_sequence WHERE name=?", (table_name,))
                except Exception:
                    pass
                results[table_name] = count
                total_deleted += count
        finally:
            conn.execute("PRAGMA foreign_keys = ON")

    return {
        "tables_cleared": results,
        "total_rows_deleted": total_deleted,
        "message": f"Cleared {total_deleted} row(s) across {len(results)} table(s).",
    }


def export_products_csv(
    search: str | None = None,
    site_id: int | None = None,
    run_id: int | None = None,
) -> tuple[str, str]:
    """Export filtered or all stored products as a CSV string with UTF-8 BOM."""
    initialize_database_explorer_db()
    db_path = get_database_path()

    where_clauses = []
    params: list[Any] = []

    if search and search.strip():
        term = f"%{search.strip()}%"
        where_clauses.append("(title LIKE ? OR product_url LIKE ? OR site_name LIKE ?)")
        params.extend([term, term, term])

    if site_id is not None:
        where_clauses.append("site_id = ?")
        params.append(site_id)

    if run_id is not None:
        where_clauses.append("run_id = ?")
        params.append(run_id)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        query = f"SELECT * FROM products {where_sql} ORDER BY id ASC LIMIT 10000"
        rows = conn.execute(query, params).fetchall()

    records = []
    all_keys = ["id", "title", "price", "rating", "availability", "product_url", "site_name", "run_id", "scraped_at"]

    for r in rows:
        item = dict(r)
        raw = {}
        if item.get("raw_data_json"):
            try:
                raw = json.loads(item["raw_data_json"])
            except Exception:
                raw = {}

        # Merge standard columns with any extra raw keys
        combined = {
            "id": item.get("id"),
            "title": item.get("title"),
            "price": item.get("price"),
            "rating": item.get("rating"),
            "availability": item.get("availability"),
            "product_url": item.get("product_url"),
            "site_name": item.get("site_name"),
            "run_id": item.get("run_id"),
            "scraped_at": item.get("scraped_at"),
        }
        for k, v in raw.items():
            if k not in combined:
                combined[k] = v
                if k not in all_keys:
                    all_keys.append(k)
        records.append(combined)

    output = io.StringIO()
    # Write UTF-8 BOM for Excel/editor compatibility
    output.write("\ufeff")

    if records:
        writer = csv.DictWriter(output, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    else:
        writer = csv.writer(output)
        writer.writerow(all_keys)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if run_id:
        filename = f"extraction_run_{run_id}.csv"
    elif search or site_id:
        filename = f"products_filtered_{today}.csv"
    else:
        filename = f"products_export_{today}.csv"

    return output.getvalue(), filename

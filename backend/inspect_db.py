import sqlite3
import json
from app.services.onboarding import get_database_path

db_path = get_database_path()
print("DB path:", db_path)
with sqlite3.connect(db_path) as conn:
    conn.row_factory = sqlite3.Row
    for table in ["sites", "site_fields", "scraper_configs", "extraction_runs", "products", "repair_history"]:
        try:
            rows = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            print(f"{table}: {rows} rows")
        except Exception as e:
            print(f"{table}: {e}")
    
    configs = conn.execute("SELECT id, site_url, version, status, confidence, config_json FROM scraper_configs").fetchall()
    for c in configs:
        print(f"\nConfig {c['id']}: url={c['site_url']}, ver={c['version']}, status={c['status']}, conf={c['confidence']}")
        print("  config_json:", c["config_json"])

    runs = conn.execute("SELECT id, config_id, start_url, pages_crawled, record_count, created_at FROM extraction_runs").fetchall()
    for r in runs:
        print(f"\nRun {r['id']}: config_id={r['config_id']}, url={r['start_url']}, pages={r['pages_crawled']}, count={r['record_count']}, time={r['created_at']}")

import sqlite3
import json
from pathlib import Path
from app.services.onboarding import get_database_path
from app.services.extractor import extract_records
from app.services.validation_service import validate_records

db_path = get_database_path()

html_path = Path("backend/uswitch_rendered.html")
if not html_path.exists():
    html_path = Path("uswitch_rendered.html")
html = html_path.read_text(encoding="utf-8")
base_url = "https://www.uswitch.com/mobiles/"

fixed_config = {
    "version": 1,
    "start_url": "https://www.uswitch.com/mobiles/",
    "render": "dynamic",
    "item_selector": "article:has(a[href$=\"-deals/\"])",
    "item_filter": "a[href$=\"-deals/\"]",
    "fields": {
        "title": {
            "selectors": ["a[href$='-deals/']", "h2.type-heading-lg"],
            "attr": "text",
            "type": "string",
            "required": True,
            "transform": "strip_deals"
        },
        "brand": {
            "selectors": ["a[href$='-deals/'] span:first-child", "a[href$='-deals/'] span"],
            "attr": "text",
            "type": "string",
            "required": False,
            "transform": "strip"
        },
        "model": {
            "selectors": ["a[href$='-deals/'] span:nth-of-type(2)", "a[href$='-deals/'] span:last-child"],
            "attr": "text",
            "type": "string",
            "required": False,
            "transform": "strip"
        },
        "price": {
            "selectors": ["p.type-body-sm", "span.text-2xl"],
            "attr": "text",
            "type": "string",
            "required": True,
            "transform": "strip"
        },
        "product_url": {
            "selectors": ["a[href$='-deals/']", "a"],
            "attr": "href",
            "type": "string",
            "required": True,
            "transform": "absolute_url"
        },
        "image_url": {
            "selectors": ["img[src]", "img"],
            "attr": "src",
            "type": "string",
            "required": False,
            "transform": "absolute_url"
        },
        "image_alt": {
            "selectors": ["img[alt]", "img"],
            "attr": "alt",
            "type": "string",
            "required": False,
            "transform": "strip"
        },
        "colours": {
            "selectors": ["li span[title]"],
            "attr": "title",
            "type": "list",
            "multiple": True,
            "required": False,
            "transform": "strip"
        },
        "rating": {
            "selectors": [],
            "attr": "text",
            "type": "string",
            "required": False,
            "transform": "strip"
        },
        "availability": {
            "selectors": [],
            "attr": "text",
            "type": "string",
            "required": False,
            "transform": "strip"
        }
    },
    "navigation": {
        "type": "load_more",
        "load_more_selector": "[data-nerd-props*=\"homepage-load-more\"]",
        "max_clicks": 20,
        "max_pages": 1
    },
    "wait_for": "[data-nerd-props*=\"homepage-load-more\"]",
    "notes": "Target handset article cards matching a[href$='-deals/']. Uses Load More button."
}

# Test extraction on uswitch_rendered.html
records, diagnostics = extract_records(html, fixed_config, base_url)
print(f"Extracted {len(records)} handset records from HTML.")

val = validate_records(records, fixed_config)
print("Validation result:")
print(f"  Total records: {val['total_records']}")
print(f"  Valid records: {val['valid_records']}")
print(f"  Invalid records: {val['invalid_records']}")
print(f"  Confidence: {val['confidence']}")
print(f"  Is valid: {val['is_valid']}")
print(f"  Validation errors: {val['validation_errors']}")

status = "active" if val["is_valid"] and val["confidence"] >= 0.80 else "needs_review"

from datetime import datetime, timezone
now = datetime.now(timezone.utc).isoformat()

with sqlite3.connect(db_path) as conn:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT UNIQUE NOT NULL,
            run_frequency TEXT DEFAULT 'manual',
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        INSERT INTO sites (id, name, url, run_frequency, status, created_at)
        VALUES (1, 'uSwitch Mobiles', 'https://www.uswitch.com/mobiles/', 'manual', 'active', ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            url = excluded.url,
            status = 'active'
    """, (now,))
    conn.execute("""
        INSERT INTO scraper_configs (id, site_url, version, config_json, sample_records, confidence, status)
        VALUES (1, ?, 1, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            site_url = excluded.site_url,
            version = excluded.version,
            config_json = excluded.config_json,
            sample_records = excluded.sample_records,
            confidence = excluded.confidence,
            status = excluded.status
    """, (
        base_url,
        json.dumps(fixed_config, ensure_ascii=False),
        json.dumps(records[:5], ensure_ascii=False),
        val["confidence"],
        status
    ))
    conn.commit()
    print(f"Upserted site and scraper_configs ID 1 with status={status}, confidence={val['confidence']}.")

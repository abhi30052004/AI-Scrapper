import json
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urljoin

from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

from app.services.onboarding import (
    get_database_path,
    initialize_onboarding_db,
)
from app.services.capture import validate_public_http_url
from app.services.extractor import extract_records
from app.services.validation_service import validate_records


def initialize_extraction_db():
    initialize_onboarding_db()

    with sqlite3.connect(get_database_path()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS extraction_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                config_id INTEGER NOT NULL,
                start_url TEXT NOT NULL,
                pages_crawled INTEGER NOT NULL,
                record_count INTEGER NOT NULL,
                records_json TEXT NOT NULL,
                diagnostics_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)


def get_saved_config(config_id: int):
    initialize_extraction_db()

    with sqlite3.connect(get_database_path()) as conn:
        conn.row_factory = sqlite3.Row

        row = conn.execute(
            """
            SELECT id, site_url, config_json, status
            FROM scraper_configs
            WHERE id = ?
            """,
            (config_id,),
        ).fetchone()

    if row is None:
        raise ValueError(
            f"Configuration {config_id} was not found"
        )

    config = json.loads(row["config_json"])

    if not isinstance(config, dict):
        raise ValueError("Saved configuration is invalid")

    return {
        "id": row["id"],
        "site_url": row["site_url"],
        "config": config,
        "status": row["status"],
    }


async def run_extraction(
    config_id: int,
    max_pages_override: int | None = None,
):
    saved = get_saved_config(config_id)

    config = saved["config"]
    start_url = saved["site_url"]

    validate_public_http_url(start_url)

    navigation = config.get("navigation", {})

    configured_max_pages = navigation.get("max_pages", 1)
    max_pages = max_pages_override or configured_max_pages

    if not isinstance(max_pages, int) or not 1 <= max_pages <= 20:
        raise ValueError("max_pages must be between 1 and 20")

    navigation_type = navigation.get("type", "none")
    next_selector = navigation.get("next_selector")

    if navigation_type not in {"none", "next_link"}:
        raise ValueError(
            f"Unsupported pagination type: {navigation_type}"
        )

    if navigation_type == "next_link" and not next_selector:
        raise ValueError(
            "next_selector is required for next_link pagination"
        )

    all_records = []
    visited_urls = set()
    pages_crawled = 0
    page_diagnostics = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)

        context = await browser.new_context(
            viewport={"width": 1366, "height": 900}
        )

        page = await context.new_page()

        async def guard_request(route):
            request_url = route.request.url

            if request_url.startswith(("http://", "https://")):
                try:
                    validate_public_http_url(request_url)
                except ValueError:
                    await route.abort()
                    return

            await route.continue_()

        await page.route("**/*", guard_request)

        try:
            current_url = start_url

            while current_url and pages_crawled < max_pages:
                validate_public_http_url(current_url)

                if current_url in visited_urls:
                    break

                visited_urls.add(current_url)

                response = await page.goto(
                    current_url,
                    wait_until="domcontentloaded",
                    timeout=45000,
                )

                if response and response.status >= 400:
                    raise ValueError(
                        f"Website returned HTTP {response.status}: "
                        f"{current_url}"
                    )

                try:
                    await page.wait_for_load_state(
                        "networkidle",
                        timeout=5000,
                    )
                except PlaywrightTimeoutError:
                    pass

                html = await page.content()

                records, diagnostics = extract_records(
                    html,
                    config,
                    page.url,
                )

                all_records.extend(records)

                pages_crawled += 1

                page_diagnostics.append({
                    "page": pages_crawled,
                    "url": page.url,
                    **diagnostics,
                })

                if (
                    navigation_type == "none"
                    or pages_crawled >= max_pages
                ):
                    break

                next_element = page.locator(
                    next_selector
                ).first

                if await next_element.count() == 0:
                    break

                next_href = await next_element.get_attribute("href")

                if not next_href:
                    break

                current_url = urljoin(page.url, next_href)

            validation = validate_records(
                all_records,
                config,
            )

            diagnostics = {
                "pages": page_diagnostics,
                "validation": validation,
            }

            initialize_extraction_db()

            with sqlite3.connect(get_database_path()) as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO extraction_runs (
                        config_id,
                        start_url,
                        pages_crawled,
                        record_count,
                        records_json,
                        diagnostics_json,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        config_id,
                        start_url,
                        pages_crawled,
                        len(all_records),
                        json.dumps(all_records),
                        json.dumps(diagnostics),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

                run_id = cursor.lastrowid

            return {
                "message": "Extraction completed",
                "run_id": run_id,
                "config_id": config_id,
                "pages_crawled": pages_crawled,
                "record_count": len(all_records),
                "diagnostics": diagnostics,
                "records": all_records,
            }

        finally:
            await context.close()
            await browser.close()


def get_extraction_run(run_id: int):
    initialize_extraction_db()

    with sqlite3.connect(get_database_path()) as conn:
        conn.row_factory = sqlite3.Row

        row = conn.execute(
            """
            SELECT *
            FROM extraction_runs
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()

    if row is None:
        raise ValueError(
            f"Extraction run {run_id} was not found"
        )

    result = dict(row)
    result["records"] = json.loads(result.pop("records_json"))
    result["diagnostics"] = json.loads(
        result.pop("diagnostics_json")
    )

    return result
import json
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urljoin

from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)
from bs4 import BeautifulSoup

from app.services.onboarding import (
    get_database_path,
    initialize_onboarding_db,
)
from app.services.capture import validate_public_http_url
from app.services.extractor import (
    extract_records,
    extract_json_ld_products,
    canonicalize_product_url,
)
from app.services.validation_service import validate_records
from app.services.async_helper import run_with_subprocess_loop

DEFAULT_LOAD_MORE_SELECTORS = [
    '[data-nerd-props*="homepage-load-more"]',
    '[data-nerd-props*="load-more"]',
    'button:has-text("Load More")',
    'button:has-text("Load more")',
    'button:has-text("Show More")',
    'button:has-text("Show more")',
    '[data-testid*="load-more"]',
    '[class*="load-more"]',
    'button[class*="load-more"]',
]


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


async def _dismiss_overlays(page) -> None:
    """Dismiss common cookie banners, consent modals, or overlays that could block pointer events."""
    try:
        cookie_candidates = [
            'button:has-text("Accept all")',
            'button:has-text("Accept All")',
            'button:has-text("Accept")',
            '#onetrust-accept-btn-handler',
            '.ucb button',
            '[data-accept-all]',
            'button[id*="cookie"]',
        ]
        for sel in cookie_candidates:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.click(timeout=1500)
                await page.wait_for_timeout(300)
                break
    except Exception:
        pass


async def _run_extraction_impl(
    config_id: int,
    max_pages_override: int | None = None,
):
    saved = get_saved_config(config_id)
    config = saved["config"]
    start_url = saved["site_url"]
    validate_public_http_url(start_url)

    navigation = config.get("navigation") or {}
    navigation_type = navigation.get("type", "none")
    allowed_navigation = {"none", "next_link", "load_more", "infinite_scroll"}
    if navigation_type not in allowed_navigation:
        raise ValueError(
            "navigation.type must be one of: none, next_link, load_more, infinite_scroll"
        )

    configured_max_pages = navigation.get("max_pages", 1)
    max_pages = max_pages_override if max_pages_override is not None else configured_max_pages
    if not isinstance(max_pages, int) or not 1 <= max_pages <= 100:
        raise ValueError("max_pages must be between 1 and 100")

    next_selector = navigation.get("next_selector")
    load_more_selector = navigation.get("load_more_selector")
    if navigation_type == "next_link" and not next_selector:
        raise ValueError("navigation.next_selector is required for next_link")

    all_records: list[dict] = []
    record_keys: set[str] = set()
    visited_urls: set[str] = set()
    pages_crawled = 0
    page_diagnostics: list[dict] = []
    detail_pages_crawled = 0
    detail_errors: list[dict] = []
    click_attempts = 0
    initial_products_found = 0
    products_discovered_load_more = 0
    extraction_warnings: list[str] = []

    def add_records(records: list[dict]) -> int:
        added = 0
        for record in records:
            if not isinstance(record, dict):
                continue
            product_url = record.get("product_url") or record.get("url")
            if product_url:
                key = canonicalize_product_url(str(product_url), start_url)
            else:
                key = json.dumps(record, sort_keys=True, ensure_ascii=False, default=str)

            if key in record_keys:
                # Merge non-empty values from repeated cards (e.g. newly loaded batches or detail data)
                existing = next(
                    (
                        item for item in all_records
                        if (
                            canonicalize_product_url(str(item.get("product_url") or item.get("url") or ""), start_url)
                            if (item.get("product_url") or item.get("url"))
                            else json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
                        ) == key
                    ),
                    None,
                )
                if existing is not None:
                    for k, v in record.items():
                        if v not in (None, "", []) and not existing.get(k):
                            existing[k] = v
                continue

            record_keys.add(key)
            all_records.append(record)
            added += 1
        return added

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1366, "height": 900},
            ignore_https_errors=False,
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

                response = None
                for attempt in range(3):
                    try:
                        response = await page.goto(
                            current_url, wait_until="domcontentloaded", timeout=45000
                        )
                        break
                    except Exception as goto_err:
                        if attempt < 2 and any(err_sig in str(goto_err).lower() for err_sig in ["connection_reset", "reset", "timeout", "timed out", "econnreset"]):
                            await page.wait_for_timeout(2000 * (attempt + 1))
                            continue
                        raise

                if response and response.status >= 400:
                    raise ValueError(
                        f"Website returned HTTP {response.status}: {current_url}"
                    )
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except PlaywrightTimeoutError:
                    pass

                # Dismiss any overlay / cookie banner before interacting
                await _dismiss_overlays(page)

                # Trigger lazy-loaded listing content before reading the DOM.
                try:
                    await page.locator(config["item_selector"]).first.wait_for(
                        state="attached", timeout=8000
                    )
                except PlaywrightTimeoutError:
                    pass

                # Extract initial batch of products before clicking Load More
                initial_html = await page.content()
                initial_batch, _ = extract_records(initial_html, config, page.url)
                add_records(initial_batch)
                initial_products_found = len(all_records)

                if navigation_type == "load_more":
                    max_clicks = min(int(navigation.get("max_clicks", 50)), 100)
                    stable_rounds = 0

                    # Resolve load more selector: use specified or detect candidate
                    target_btn_selector = load_more_selector
                    if not target_btn_selector:
                        for cand in DEFAULT_LOAD_MORE_SELECTORS:
                            if await page.locator(cand).count() > 0 and await page.locator(cand).first.is_visible():
                                target_btn_selector = cand
                                break

                    if not target_btn_selector:
                        extraction_warnings.append("Load more selector could not be resolved on page.")

                    while target_btn_selector and click_attempts < max_clicks:
                        button = page.locator(target_btn_selector).first
                        if await button.count() == 0 or not await button.is_visible():
                            break
                        if await button.is_disabled():
                            break

                        before_count = await page.locator(config["item_selector"]).count()
                        await button.scroll_into_view_if_needed()

                        # Click using evaluate to bypass pointer-intercepting cookie overlays
                        clicked = False
                        try:
                            await button.evaluate("el => el.click()")
                            clicked = True
                        except Exception:
                            try:
                                await button.click(force=True, timeout=5000)
                                clicked = True
                            except Exception as click_err:
                                extraction_warnings.append(f"Load more click attempt failed: {click_err}")
                                break

                        if not clicked:
                            break

                        click_attempts += 1

                        # Wait for cards to increase
                        timeout_ms = int(navigation.get("load_timeout_ms", 8000))
                        try:
                            await page.wait_for_function(
                                """({selector, before}) =>
                                    document.querySelectorAll(selector).length > before""",
                                arg={"selector": config["item_selector"], "before": before_count},
                                timeout=timeout_ms,
                            )
                        except PlaywrightTimeoutError:
                            pass

                        # Allow newly loaded batch to fully mount and settle
                        settle_ms = int(navigation.get("settle_wait_ms", 1200))
                        await page.wait_for_timeout(settle_ms)

                        # Deduplicate after every batch
                        batch_html = await page.content()
                        batch_records, _ = extract_records(batch_html, config, page.url)
                        newly_added = add_records(batch_records)

                        if newly_added > 0:
                            products_discovered_load_more += newly_added
                            stable_rounds = 0
                        else:
                            stable_rounds += 1
                            if stable_rounds >= 2:
                                # Stop if repeated clicks produce no new unique products
                                break

                elif navigation_type == "infinite_scroll":
                    max_steps = min(int(navigation.get("max_scroll_steps", 40)), 100)
                    stable_rounds = 0
                    previous_count = -1
                    for _ in range(max_steps):
                        count = await page.locator(config["item_selector"]).count()
                        if count <= previous_count:
                            stable_rounds += 1
                        else:
                            stable_rounds = 0
                        if stable_rounds >= 3:
                            break
                        previous_count = count
                        await page.evaluate(
                            "() => window.scrollTo(0, document.body.scrollHeight)"
                        )
                        await page.wait_for_timeout(
                            max(500, min(int(navigation.get("scroll_wait_ms", 1200)), 5000))
                        )
                        batch_html = await page.content()
                        batch_records, _ = extract_records(batch_html, config, page.url)
                        add_records(batch_records)

                # Ensure lazy-loaded product media is populated
                await page.evaluate("""() => {
                    document.querySelectorAll('img[loading="lazy"]').forEach(img => {
                        img.loading = 'eager';
                    });
                    window.scrollTo(0, document.body.scrollHeight);
                }""")
                await page.wait_for_timeout(400)
                await page.evaluate("() => window.scrollTo(0, 0)")

                final_page_html = await page.content()
                final_records, diagnostics_page = extract_records(final_page_html, config, page.url)
                new_count = add_records(final_records)
                pages_crawled += 1
                page_diagnostics.append({
                    "page": pages_crawled,
                    "url": page.url,
                    "records_found": len(final_records),
                    "new_records": new_count,
                    **diagnostics_page,
                })

                if navigation_type != "next_link" or pages_crawled >= max_pages:
                    break

                next_element = page.locator(next_selector).first
                if await next_element.count() == 0:
                    break
                next_href = await next_element.get_attribute("href")
                if not next_href:
                    break
                current_url = urljoin(page.url, next_href)

            # Product detail extraction: visit each unique product URL when configured
            detail_fields = config.get("detail_fields")
            extract_detail_pages = config.get("extract_detail_pages", False) or bool(detail_fields)
            if extract_detail_pages:
                detail_url_field = config.get("detail_url_field", "product_url")
                detail_item_selector = config.get("detail_item_selector", "body")
                detail_limit = max(1, min(int(config.get("max_detail_pages", 500)), 1000))

                detail_urls = []
                for record in all_records:
                    val = record.get(detail_url_field) or record.get("url")
                    if val:
                        abs_u = urljoin(start_url, str(val).strip())
                        if abs_u not in detail_urls:
                            detail_urls.append(abs_u)

                for detail_url in detail_urls[:detail_limit]:
                    try:
                        validate_public_http_url(detail_url)
                        detail_resp = await page.goto(
                            detail_url, wait_until="domcontentloaded", timeout=45000
                        )
                        if detail_resp and detail_resp.status >= 400:
                            raise ValueError(f"HTTP {detail_resp.status}")
                        try:
                            await page.wait_for_load_state("networkidle", timeout=3000)
                        except PlaywrightTimeoutError:
                            pass

                        detail_html = await page.content()
                        detail_soup = BeautifulSoup(detail_html, "lxml")

                        # Extract accessible metadata
                        h1_el = detail_soup.find("h1")
                        h1_text = h1_el.get_text(" ", strip=True) if h1_el else None

                        meta_desc = None
                        desc_tag = detail_soup.find("meta", attrs={"name": "description"})
                        if desc_tag:
                            meta_desc = desc_tag.get("content")

                        og_img = None
                        og_img_tag = detail_soup.find("meta", attrs={"property": "og:image"})
                        if og_img_tag:
                            og_img = og_img_tag.get("content")

                        detail_json_lds = extract_json_ld_products(detail_soup, detail_url)

                        custom_detail = {}
                        if isinstance(detail_fields, dict) and detail_fields:
                            detail_conf = {
                                "item_selector": detail_item_selector,
                                "fields": detail_fields,
                            }
                            recs, _ = extract_records(detail_html, detail_conf, detail_url)
                            if recs:
                                custom_detail = recs[0]

                        detail_payload = {
                            "source_url": detail_url,
                            "h1": h1_text,
                            "description": meta_desc,
                            "og_image": og_img,
                            "structured_products": detail_json_lds,
                            "attributes": custom_detail,
                        }

                        # Match target record and merge without overwriting valid listing values
                        target = next(
                            (
                                r for r in all_records
                                if canonicalize_product_url(str(r.get(detail_url_field) or r.get("url") or ""), start_url)
                                == canonicalize_product_url(detail_url, start_url)
                            ),
                            None,
                        )
                        if target is not None:
                            target["detail"] = detail_payload
                            for k, v in custom_detail.items():
                                if v not in (None, "", []) and not target.get(k):
                                    target[k] = v
                            if not target.get("image_url") and og_img:
                                target["image_url"] = og_img

                        detail_pages_crawled += 1
                    except Exception as exc:
                        detail_errors.append({
                            "url": detail_url,
                            "error": f"{type(exc).__name__}: {exc}"[:500],
                        })

            validation = validate_records(all_records, config)
            created_at = datetime.now(timezone.utc).isoformat()
            initialize_extraction_db()

            diagnostics = {
                "initial_products_found": initial_products_found,
                "products_discovered_load_more": products_discovered_load_more,
                "unique_products": len(all_records),
                "click_attempts": click_attempts,
                "detail_pages_visited": detail_pages_crawled,
                "successfully_saved_products": 0,
                "updated_products": 0,
                "duplicates_skipped": 0,
                "failed_products": 0,
                "extraction_warnings": extraction_warnings,
                "pages": page_diagnostics,
                "validation": validation,
                "navigation_type": navigation_type,
            }

            with sqlite3.connect(get_database_path(), timeout=30) as conn:
                conn.execute("PRAGMA busy_timeout = 30000")
                cursor = conn.execute(
                    """
                    INSERT INTO extraction_runs (
                        config_id, start_url, pages_crawled, record_count,
                        records_json, diagnostics_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        config_id,
                        start_url,
                        pages_crawled,
                        len(all_records),
                        json.dumps(all_records, ensure_ascii=False, default=str),
                        json.dumps(diagnostics, ensure_ascii=False, default=str),
                        created_at,
                    ),
                )
                run_id = cursor.lastrowid

            # Safe database synchronization with metrics tracking
            from app.services.database_explorer_service import sync_run_products
            sync_stats = sync_run_products(
                run_id=run_id,
                config_id=config_id,
                start_url=start_url,
                records=all_records,
                created_at=created_at,
            )

            diagnostics["successfully_saved_products"] = sync_stats.saved
            diagnostics["updated_products"] = sync_stats.updated
            diagnostics["duplicates_skipped"] = sync_stats.skipped
            diagnostics["failed_products"] = sync_stats.failed

            with sqlite3.connect(get_database_path(), timeout=30) as conn:
                conn.execute("PRAGMA busy_timeout = 30000")
                conn.execute(
                    "UPDATE extraction_runs SET diagnostics_json = ? WHERE id = ?",
                    (json.dumps(diagnostics, ensure_ascii=False, default=str), run_id),
                )

            return {
                "message": "Extraction completed" if not detail_errors else "Extraction completed with detail-page errors",
                "run_id": run_id,
                "config_id": config_id,
                "pages_crawled": pages_crawled,
                "record_count": len(all_records),
                "initial_products_found": initial_products_found,
                "products_discovered_load_more": products_discovered_load_more,
                "products_saved": sync_stats.saved,
                "products_updated": sync_stats.updated,
                "duplicates_skipped": sync_stats.skipped,
                "failed_products": sync_stats.failed,
                "detail_pages_crawled": detail_pages_crawled,
                "detail_page_errors": detail_errors,
                "diagnostics": diagnostics,
                "records": all_records,
            }
        finally:
            try:
                await context.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass


async def run_extraction(
    config_id: int,
    max_pages_override: int | None = None,
):
    return await run_with_subprocess_loop(
        _run_extraction_impl,
        config_id,
        max_pages_override,
    )


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

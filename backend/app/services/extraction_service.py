import json
import logging
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urljoin

from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

from app.config import settings
from app.services.async_helper import run_with_subprocess_loop
from app.services.capture import (
    DEFAULT_LOAD_MORE_SELECTORS,
    DEFAULT_NEXT_SELECTORS,
    detect_navigation_controls,
    dismiss_overlays,
    goto_with_retries,
    trigger_lazy_media,
    validate_public_http_url,
)
from app.services.extractor import (
    canonicalize_product_url,
    extract_semantic_products_from_cards,
    filter_listing_cards,
)
from app.services.llm_extractor import extract_details_with_llm
from app.services.onboarding import (
    get_database_path,
    initialize_onboarding_db,
)
from app.services.semantic_extractor import (
    extract_semantic_detail,
    extract_semantic_listing,
)
from app.services.validation_service import (
    merge_product_records,
    validate_and_normalize_records,
)

logger = logging.getLogger(__name__)


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
        raise ValueError(f"Configuration {config_id} was not found")

    config = json.loads(row["config_json"])

    if not isinstance(config, dict):
        raise ValueError("Saved configuration is invalid")

    return {
        "id": row["id"],
        "site_url": row["site_url"],
        "config": config,
        "status": row["status"],
    }


def ensure_semantic_config(url: str, fields: list[dict] | None = None, navigation_type: str = "auto", max_pages: int = 10) -> int:
    """Find an existing semantic_llm config for this URL or create one cleanly."""
    initialize_onboarding_db()
    norm_url = url.rstrip("/")
    with sqlite3.connect(get_database_path()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, site_url, version, config_json FROM scraper_configs ORDER BY id DESC"
        ).fetchall()
        for row in rows:
            if row["site_url"].rstrip("/") == norm_url:
                try:
                    cfg = json.loads(row["config_json"])
                    if isinstance(cfg, dict) and cfg.get("extraction_mode") == "semantic_llm":
                        return row["id"]
                except Exception:
                    continue

        current_ver = conn.execute(
            "SELECT MAX(version) FROM scraper_configs WHERE site_url = ?",
            (url,),
        ).fetchone()[0]
        version = (current_ver or 0) + 1

        field_map = {}
        for f in (fields or []):
            name = f.get("name")
            if name:
                field_map[name] = {
                    "type": f.get("type", "string"),
                    "required": bool(f.get("required", False)),
                }
        if not field_map:
            field_map = {
                "title": {"type": "string", "required": True},
                "price": {"type": "string", "required": False},
                "product_url": {"type": "string", "required": False},
            }

        cfg = {
            "version": 1,
            "extraction_mode": "semantic_llm",
            "start_url": url,
            "render": "dynamic",
            "extract_detail_pages": settings.extract_detail_pages_default,
            "max_detail_pages": 100,
            "fields": field_map,
            "navigation": {
                "type": navigation_type,
                "max_pages": max_pages,
                "max_clicks": 40,
            },
        }
        cur = conn.execute(
            """
            INSERT INTO scraper_configs
            (site_url, version, config_json, sample_records, confidence, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (url, version, json.dumps(cfg, ensure_ascii=False), "[]", 1.0, "active"),
        )
        return cur.lastrowid


async def _run_extraction_impl(
    config_id: int,
    max_pages_override: int | None = None,
    extract_details_override: bool | None = None,
    max_detail_pages_override: int | None = None,
):
    saved = get_saved_config(config_id)
    config = saved["config"]
    start_url = saved["site_url"]
    validate_public_http_url(start_url)

    navigation = config.get("navigation") or {}
    navigation_type = navigation.get("type", "auto")
    allowed_navigation = {"auto", "none", "next_link", "load_more", "infinite_scroll"}
    if navigation_type not in allowed_navigation:
        raise ValueError(
            "navigation.type must be one of: auto, none, next_link, load_more, infinite_scroll"
        )

    configured_max_pages = navigation.get("max_pages", 10 if navigation_type in {"auto", "next_link"} else 1)
    max_pages = max_pages_override if max_pages_override is not None else configured_max_pages
    if not isinstance(max_pages, int) or not 1 <= max_pages <= 100:
        raise ValueError("max_pages must be between 1 and 100")

    next_selector = navigation.get("next_selector")
    load_more_selector = navigation.get("load_more_selector")

    all_records: list[dict] = []
    record_index_by_key: dict[str, int] = {}
    seen_card_keys: set[str] = set()
    visited_urls: set[str] = set()

    pages_crawled = 0
    page_diagnostics: list[dict] = []
    product_cards_detected = 0
    llm_batches_processed = 0
    llm_cache_hits = 0
    detail_pages_crawled = 0
    detail_errors: list[dict] = []
    error_messages: list[str] = []
    extraction_warnings: list[str] = []
    rejected_non_products: list[dict] = []
    click_attempts = 0
    initial_products_found = 0
    products_discovered_load_more = 0

    def _record_key(record: dict) -> str:
        product_url = record.get("product_url") or record.get("url")
        if product_url:
            canon = canonicalize_product_url(str(product_url), start_url)
            if canon:
                return canon
        title = str(record.get("title") or "").strip().lower()
        price = str(record.get("price") or "").strip().lower()
        if title:
            return f"title:{title}|price:{price}"
        return json.dumps(record, sort_keys=True, ensure_ascii=False, default=str)

    def add_records(records: list[dict]) -> int:
        added = 0
        for record in records:
            if not isinstance(record, dict):
                continue
            key = _record_key(record)
            if key in record_index_by_key:
                idx = record_index_by_key[key]
                all_records[idx] = merge_product_records(all_records[idx], record)
                continue
            record_index_by_key[key] = len(all_records)
            all_records.append(record)
            added += 1
        return added

    def _card_identity(card: dict, page_url: str) -> str:
        if card.get("primary_url"):
            canon = canonicalize_product_url(card["primary_url"], page_url)
            if canon:
                return canon
        return card.get("card_hash", "")

    def process_unseen_cards(cards: list[dict], page_url: str) -> tuple[int, dict]:
        nonlocal product_cards_detected, llm_batches_processed, llm_cache_hits
        filtered = filter_listing_cards(cards)
        unseen = []
        for card in filtered:
            cid = _card_identity(card, page_url)
            if cid and cid not in seen_card_keys:
                seen_card_keys.add(cid)
                unseen.append(card)
        if not unseen:
            return 0, {"llm_batches_processed": 0, "llm_cache_hits": 0, "llm_errors": []}

        product_cards_detected += len(unseen)
        extracted, metrics = extract_semantic_products_from_cards(unseen, page_url, config=config)
        llm_batches_processed += metrics["llm_batches_processed"]
        llm_cache_hits += metrics["llm_cache_hits"]
        error_messages.extend(metrics.get("llm_errors", []))
        rejected_non_products.extend(metrics.get("rejected_non_products", []))
        newly_added = add_records(extracted)
        return newly_added, metrics

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
            resolved_nav_type = navigation_type

            while current_url and pages_crawled < max_pages:
                validate_public_http_url(current_url)
                canon_page = canonicalize_product_url(current_url, start_url) or current_url
                if canon_page in visited_urls:
                    break
                visited_urls.add(canon_page)

                response = await goto_with_retries(page, current_url)
                if response and response.status >= 400:
                    raise ValueError(f"Website returned HTTP {response.status}: {current_url}")
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except PlaywrightTimeoutError:
                    pass

                await dismiss_overlays(page)
                await trigger_lazy_media(page)

                # Resolve auto navigation on the first page
                if resolved_nav_type == "auto":
                    detected_nav = await detect_navigation_controls(page)
                    resolved_nav_type = detected_nav["type"]
                    if resolved_nav_type == "load_more" and not load_more_selector:
                        load_more_selector = detected_nav.get("selector")
                    elif resolved_nav_type == "next_link" and not next_selector:
                        next_selector = detected_nav.get("selector")

                initial_html = await page.content()
                initial_semantic = extract_semantic_listing(initial_html, page.url)
                initial_added, initial_metrics = process_unseen_cards(initial_semantic["cards"], page.url)
                if pages_crawled == 0:
                    initial_products_found = len(all_records)

                # Handle Load More
                if resolved_nav_type == "load_more":
                    max_clicks = min(int(navigation.get("max_clicks", 50)), 100)
                    stable_rounds = 0
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

                        before_text_len = await page.evaluate("() => document.body ? document.body.innerText.length : 0")
                        await button.scroll_into_view_if_needed()

                        clicked = False
                        try:
                            await button.evaluate("el => el.click()")
                            clicked = True
                        except Exception:
                            try:
                                await button.click(force=True, timeout=5000)
                                clicked = True
                            except Exception as click_err:
                                extraction_warnings.append(f"Load more click failed: {click_err}")
                                break

                        if not clicked:
                            break

                        click_attempts += 1
                        timeout_ms = int(navigation.get("load_timeout_ms", 8000))
                        try:
                            await page.wait_for_function(
                                """(prevLen) => document.body && document.body.innerText.length > prevLen + 40""",
                                arg=before_text_len,
                                timeout=timeout_ms,
                            )
                        except PlaywrightTimeoutError:
                            pass

                        settle_ms = int(navigation.get("settle_wait_ms", 1000))
                        await page.wait_for_timeout(settle_ms)
                        await trigger_lazy_media(page)

                        batch_html = await page.content()
                        batch_semantic = extract_semantic_listing(batch_html, page.url)
                        newly_added, _ = process_unseen_cards(batch_semantic["cards"], page.url)

                        if newly_added > 0:
                            products_discovered_load_more += newly_added
                            stable_rounds = 0
                        else:
                            stable_rounds += 1
                            if stable_rounds >= 2:
                                break

                elif resolved_nav_type == "infinite_scroll":
                    max_steps = min(int(navigation.get("max_scroll_steps", 40)), 100)
                    stable_rounds = 0
                    for _ in range(max_steps):
                        await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                        await page.wait_for_timeout(
                            max(500, min(int(navigation.get("scroll_wait_ms", 1200)), 5000))
                        )
                        batch_html = await page.content()
                        batch_semantic = extract_semantic_listing(batch_html, page.url)
                        newly_added, _ = process_unseen_cards(batch_semantic["cards"], page.url)
                        if newly_added > 0:
                            stable_rounds = 0
                        else:
                            stable_rounds += 1
                            if stable_rounds >= 3:
                                break

                # Include any JSON-LD products from the final state not already matched to DOM cards
                final_html = await page.content()
                final_semantic = extract_semantic_listing(final_html, page.url)
                final_added, _ = process_unseen_cards(final_semantic["cards"], page.url)

                extra_ld = []
                for ld in final_semantic["json_ld"]["products"]:
                    ld_key = _record_key(ld)
                    if ld_key not in record_index_by_key:
                        extra_ld.append(ld)
                if extra_ld:
                    norm_ld, _ = validate_and_normalize_records(extra_ld, base_url=page.url, config=config)
                    add_records(norm_ld)

                pages_crawled += 1
                page_diagnostics.append({
                    "page": pages_crawled,
                    "url": page.url,
                    "page_title": final_semantic["page_metadata"].get("page_title", ""),
                    "cards_detected": final_semantic["card_count"],
                    "json_ld_count": len(final_semantic["json_ld"]["products"]),
                    "new_records": initial_added + final_added,
                })

                if resolved_nav_type != "next_link" or pages_crawled >= max_pages:
                    break

                # Resolve next page link
                next_href = None
                candidate_selectors = [next_selector] if next_selector else DEFAULT_NEXT_SELECTORS
                for sel in candidate_selectors:
                    if not sel:
                        continue
                    loc = page.locator(sel).first
                    if await loc.count() > 0:
                        href = await loc.get_attribute("href")
                        if href:
                            next_href = href
                            break

                if not next_href:
                    break
                current_url = urljoin(page.url, next_href)

            # ── Product Detail Extraction (Semantic + Batched LLM) ────────────────────────
            should_extract_details = (
                extract_details_override
                if extract_details_override is not None
                else bool(config.get("extract_detail_pages", settings.extract_detail_pages_default))
            )

            if should_extract_details and all_records:
                detail_limit = max_detail_pages_override or int(config.get("max_detail_pages", 100))
                detail_limit = max(1, min(detail_limit, 500))

                detail_urls: list[str] = []
                seen_detail_canon: set[str] = set()
                for rec in all_records:
                    u = rec.get("product_url") or rec.get("url")
                    if not u:
                        continue
                    abs_u = urljoin(start_url, str(u).strip())
                    canon_u = canonicalize_product_url(abs_u, start_url)
                    if canon_u and canon_u not in seen_detail_canon:
                        seen_detail_canon.add(canon_u)
                        detail_urls.append(abs_u)

                semantic_details: list[dict] = []
                for detail_url in detail_urls[:detail_limit]:
                    try:
                        validate_public_http_url(detail_url)
                        detail_resp = await goto_with_retries(page, detail_url, timeout_ms=30000, attempts=2)
                        if detail_resp and detail_resp.status >= 400:
                            raise ValueError(f"HTTP {detail_resp.status}")
                        try:
                            await page.wait_for_load_state("networkidle", timeout=1500)
                        except PlaywrightTimeoutError:
                            pass

                        detail_html = await page.content()
                        sem_detail = extract_semantic_detail(detail_html, page.url or detail_url)
                        sem_detail["requested_detail_url"] = detail_url
                        semantic_details.append(sem_detail)
                        detail_pages_crawled += 1
                    except Exception as exc:
                        err_text = f"{type(exc).__name__}: {exc}"[:300]
                        detail_errors.append({"url": detail_url, "error": err_text})
                        error_messages.append(f"Detail page error ({detail_url}): {err_text}")

                if semantic_details:
                    detail_llm_res = extract_details_with_llm(semantic_details)
                    llm_batches_processed += detail_llm_res["llm_batches_processed"]
                    llm_cache_hits += detail_llm_res["cache_hits"]
                    error_messages.extend(detail_llm_res.get("errors", []))
                    rejected_non_products.extend(detail_llm_res.get("rejected_non_products", []))

                    # Only drop listing records if the visited detail page is explicitly
                    # a non-product legal/merger/community/partnership/support page
                    rejected_detail_urls = {
                        canonicalize_product_url(r.get("url") or "", start_url)
                        for r in detail_llm_res.get("rejected_non_products", [])
                        if r.get("url") and str(r.get("reason", "")).startswith("non_product_")
                    }
                    if rejected_detail_urls:
                        all_records = [
                            rec for rec in all_records
                            if canonicalize_product_url(str(rec.get("product_url") or ""), start_url) not in rejected_detail_urls
                            or rec.get("raw_json_ld")
                        ]
                        record_index_by_key.clear()
                        for i_rec, rec_item in enumerate(all_records):
                            record_index_by_key[_record_key(rec_item)] = i_rec

                    for sem_detail in semantic_details:
                        src = sem_detail["source_url"]
                        req_src = sem_detail.get("requested_detail_url", src)
                        raw_detail = detail_llm_res["details_by_url"].get(src)
                        if not raw_detail:
                            continue
                        norm_details, _ = validate_and_normalize_records(
                            [raw_detail], base_url=src, filter_non_products=False
                        )
                        if not norm_details:
                            continue
                        detail_rec = norm_details[0]
                        detail_rec["detail_visited"] = True

                        target_canon = canonicalize_product_url(req_src, start_url)
                        target_idx = record_index_by_key.get(target_canon)
                        if target_idx is None:
                            src_canon = canonicalize_product_url(src, start_url)
                            target_idx = record_index_by_key.get(src_canon)
                        if target_idx is not None:
                            all_records[target_idx] = merge_product_records(all_records[target_idx], detail_rec)

            # Final validation & product-only normalization pass across all merged products
            all_records, validation = validate_and_normalize_records(
                all_records,
                base_url=start_url,
                config=config,
                filter_non_products=True,
            )
            rejected_non_products.extend(validation.get("rejected_non_products", []))

            # Deduplicate rejected tracking list by (url, title)
            dedup_rejected: list[dict] = []
            seen_rej: set[tuple] = set()
            for rej in rejected_non_products:
                rk = (rej.get("url") or "", rej.get("title") or "", rej.get("reason") or "")
                if rk not in seen_rej:
                    seen_rej.add(rk)
                    dedup_rejected.append(rej)

            created_at = datetime.now(timezone.utc).isoformat()
            initialize_extraction_db()

            products_validated = validation.get("valid_records", 0)
            invalid_count = validation.get("invalid_records", 0)
            all_error_messages = list(dict.fromkeys(
                error_messages + extraction_warnings + validation.get("validation_errors", [])
            ))

            diagnostics = {
                "extraction_mode": "semantic_llm",
                "pages_visited": pages_crawled,
                "pages_crawled": pages_crawled,
                "product_cards_detected": product_cards_detected,
                "llm_batches_processed": llm_batches_processed,
                "llm_cache_hits": llm_cache_hits,
                "products_extracted": len(all_records),
                "products_validated": products_validated,
                "rejected_non_product_count": len(dedup_rejected),
                "rejected_non_products": dedup_rejected,
                "initial_products_found": initial_products_found,
                "products_discovered_load_more": products_discovered_load_more,
                "unique_products": len(all_records),
                "click_attempts": click_attempts,
                "detail_pages_visited": detail_pages_crawled,
                "products_inserted": 0,
                "successfully_saved_products": 0,
                "products_updated": 0,
                "updated_products": 0,
                "duplicates_skipped": 0,
                "failed_records": invalid_count,
                "failed_products": 0,
                "error_messages": all_error_messages,
                "extraction_warnings": extraction_warnings,
                "detail_page_errors": detail_errors,
                "pages": page_diagnostics,
                "validation": validation,
                "navigation_type": resolved_nav_type,
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

            from app.services.database_explorer_service import sync_run_products
            sync_stats = sync_run_products(
                run_id=run_id,
                config_id=config_id,
                start_url=start_url,
                records=all_records,
                created_at=created_at,
            )

            diagnostics["products_inserted"] = sync_stats.saved
            diagnostics["successfully_saved_products"] = sync_stats.saved
            diagnostics["products_updated"] = sync_stats.updated
            diagnostics["updated_products"] = sync_stats.updated
            diagnostics["duplicates_skipped"] = sync_stats.skipped
            diagnostics["failed_products"] = sync_stats.failed
            diagnostics["failed_records"] = sync_stats.failed + invalid_count

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
                "pages_visited": pages_crawled,
                "pages_crawled": pages_crawled,
                "product_cards_detected": product_cards_detected,
                "llm_batches_processed": llm_batches_processed,
                "llm_cache_hits": llm_cache_hits,
                "products_extracted": len(all_records),
                "products_validated": products_validated,
                "rejected_non_product_count": len(dedup_rejected),
                "rejected_non_products": dedup_rejected,
                "record_count": len(all_records),
                "initial_products_found": initial_products_found,
                "products_discovered_load_more": products_discovered_load_more,
                "products_inserted": sync_stats.saved,
                "products_saved": sync_stats.saved,
                "products_updated": sync_stats.updated,
                "duplicates_skipped": sync_stats.skipped,
                "failed_records": sync_stats.failed,
                "failed_products": sync_stats.failed,
                "detail_pages_crawled": detail_pages_crawled,
                "detail_page_errors": detail_errors,
                "error_messages": all_error_messages,
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
    extract_details_override: bool | None = None,
    max_detail_pages_override: int | None = None,
):
    return await run_with_subprocess_loop(
        _run_extraction_impl,
        config_id,
        max_pages_override,
        extract_details_override,
        max_detail_pages_override,
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
        raise ValueError(f"Extraction run {run_id} was not found")

    result = dict(row)
    result["records"] = json.loads(result.pop("records_json"))
    result["diagnostics"] = json.loads(result.pop("diagnostics_json"))

    return result

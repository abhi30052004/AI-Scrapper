from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse, urljoin
from ipaddress import ip_address
import socket
import time
import uuid
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from ..config import settings
from .async_helper import run_with_subprocess_loop

DEFAULT_LOAD_MORE_SELECTORS = [
    '[data-nerd-props*="homepage-load-more"]',
    '[data-nerd-props*="load-more"]',
    'button:has-text("Load More")',
    'button:has-text("Load more")',
    'button:has-text("Show More")',
    'button:has-text("Show more")',
    'a:has-text("Load More")',
    'a:has-text("Load more")',
    '[data-testid*="load-more"]',
    '[class*="load-more"]',
    'button[class*="load-more"]',
]

DEFAULT_NEXT_SELECTORS = [
    'li.next > a',
    'a[rel="next"]',
    'a.next',
    'button[aria-label*="Next" i]',
    'a[aria-label*="Next" i]',
    'a:has-text("Next")',
]


@dataclass
class CaptureResult:
    requested_url: str
    final_url: str
    html: str
    screenshot_path: str | None
    load_time_ms: int
    page_title: str
    status_code: int | None
    metadata: dict = field(default_factory=dict)

def validate_public_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only valid http:// and https:// URLs are allowed.")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing embedded credentials are not allowed.")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local")):
        raise ValueError("Local network targets are not allowed.")
    try:
        addresses = [ip_address(host)]
    except ValueError:
        try:
            addresses = [ip_address(item[4][0]) for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)]
        except socket.gaierror as exc:
            raise ValueError(f"Could not resolve website hostname: {host}") from exc
    if not addresses or any(not addr.is_global for addr in addresses):
        raise ValueError("The website resolves to a private or reserved IP address and cannot be captured.")

async def dismiss_overlays(page) -> None:
    """Dismiss common cookie banners, consent modals, or overlays that block interaction."""
    try:
        cookie_candidates = [
            'button:has-text("Accept all")',
            'button:has-text("Accept All")',
            'button:has-text("Accept")',
            '#onetrust-accept-btn-handler',
            '.ucb button',
            '[data-accept-all]',
            'button[id*="cookie" i]',
        ]
        for sel in cookie_candidates:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.click(timeout=1500)
                await page.wait_for_timeout(300)
                break
    except Exception:
        pass


async def trigger_lazy_media(page) -> None:
    """Trigger lazy-loaded images and intersection-observer content on the page."""
    try:
        await page.evaluate("""() => {
            document.querySelectorAll('img[loading="lazy"]').forEach(img => {
                img.loading = 'eager';
            });
            window.scrollTo(0, document.body.scrollHeight);
        }""")
        await page.wait_for_timeout(350)
        await page.evaluate("() => window.scrollTo(0, 0)")
    except Exception:
        pass


async def goto_with_retries(page, url: str, timeout_ms: int | None = None, attempts: int = 3):
    """Navigate to a URL with transient network retry handling."""
    effective_timeout = timeout_ms or settings.page_timeout_ms
    response = None
    for attempt in range(attempts):
        try:
            response = await page.goto(
                url, wait_until="domcontentloaded", timeout=effective_timeout
            )
            return response
        except Exception as goto_err:
            err_msg = str(goto_err).lower()
            transient_sigs = ("connection_reset", "reset", "timeout", "timed out", "econnreset", "aborted")
            if attempt < attempts - 1 and any(sig in err_msg for sig in transient_sigs):
                await page.wait_for_timeout(1500 * (attempt + 1))
                continue
            raise
    return response


async def detect_navigation_controls(page) -> dict:
    """Detect Load More or Next-page controls present in the live DOM."""
    for sel in DEFAULT_LOAD_MORE_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible() and not await loc.is_disabled():
                return {"type": "load_more", "selector": sel}
        except Exception:
            continue

    for sel in DEFAULT_NEXT_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                href = await loc.get_attribute("href")
                if href:
                    return {"type": "next_link", "selector": sel, "next_href": href}
        except Exception:
            continue

    return {"type": "none", "selector": None}


async def _capture_page_impl(url: str, snapshot_dir: str | None = None) -> CaptureResult:
    validate_public_http_url(url)
    started = time.perf_counter()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1366, "height": 900})
        page = await context.new_page()

        async def guard_request(route):
            request_url = route.request.url
            if urlparse(request_url).scheme in {"http", "https"}:
                try:
                    validate_public_http_url(request_url)
                except ValueError:
                    await route.abort()
                    return
            await route.continue_()

        await page.route("**/*", guard_request)
        try:
            response = await goto_with_retries(page, url)
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except PlaywrightTimeoutError:
                pass
            await dismiss_overlays(page)
            await trigger_lazy_media(page)
            html = await page.content()
            title = await page.title()
            screenshot = None
            if snapshot_dir:
                folder = Path(snapshot_dir) / uuid.uuid4().hex
                folder.mkdir(parents=True, exist_ok=True)
                screenshot = str(folder / "capture.png")
                await page.screenshot(path=screenshot, full_page=True)
            metadata = {
                "requested_url": url,
                "final_url": page.url,
                "page_title": title,
                "status_code": response.status if response else None,
            }
            return CaptureResult(
                url,
                page.url,
                html,
                screenshot,
                int((time.perf_counter() - started) * 1000),
                title,
                response.status if response else None,
                metadata=metadata,
            )
        finally:
            try:
                await context.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass

async def capture_page(url: str, snapshot_dir: str | None = None) -> CaptureResult:
    return await run_with_subprocess_loop(_capture_page_impl, url, snapshot_dir)

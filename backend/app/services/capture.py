from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from ipaddress import ip_address
import socket
import time
import uuid
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from ..config import settings

@dataclass
class CaptureResult:
    requested_url: str
    final_url: str
    html: str
    screenshot_path: str | None
    load_time_ms: int
    page_title: str
    status_code: int | None

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

async def capture_page(url: str, snapshot_dir: str | None = None) -> CaptureResult:
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
            response = await page.goto(url, wait_until="domcontentloaded", timeout=settings.page_timeout_ms)
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except PlaywrightTimeoutError:
                pass
            html = await page.content()
            title = await page.title()
            screenshot = None
            if snapshot_dir:
                folder = Path(snapshot_dir) / uuid.uuid4().hex
                folder.mkdir(parents=True, exist_ok=True)
                screenshot = str(folder / "capture.png")
                await page.screenshot(path=screenshot, full_page=True)
            return CaptureResult(url, page.url, html, screenshot,
                int((time.perf_counter()-started)*1000), title,
                response.status if response else None)
        finally:
            await context.close()
            await browser.close()

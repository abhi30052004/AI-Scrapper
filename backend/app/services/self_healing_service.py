
import json

from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

from app.services.ai_client import repair_config
from app.services.capture import validate_public_http_url
from app.services.extraction_service import get_saved_config
from app.services.onboarding import (
    save_config,
    save_repair_history,
)
from app.services.repair_validator import validate_repair
from app.services.async_helper import run_with_subprocess_loop


AUTO_APPLY_THRESHOLD = 0.90
HUMAN_REVIEW_THRESHOLD = 0.60


async def _capture_latest_html_impl(url: str) -> tuple[str, str]:
    """Safely capture the latest rendered website HTML."""

    validate_public_http_url(url)

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
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=45000,
            )

            if response and response.status >= 400:
                raise ValueError(
                    f"Website returned HTTP {response.status}"
                )

            try:
                await page.wait_for_load_state(
                    "networkidle",
                    timeout=5000,
                )
            except PlaywrightTimeoutError:
                pass

            html = await page.content()

            return html, page.url

        finally:
            try:
                await context.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass


async def capture_latest_html(url: str) -> tuple[str, str]:
    return await run_with_subprocess_loop(_capture_latest_html_impl, url)


def build_failure_report(
    config: dict,
    original_records: list,
    original_diagnostics: dict,
) -> dict:
    """Describe the current extraction quality."""

    fields = config.get("fields", {})
    missing_fields = []

    for field_name, definition in fields.items():
        missing_count = sum(
            1
            for record in original_records
            if record.get(field_name) is None
            or str(record.get(field_name)).strip() == ""
        )

        if missing_count:
            missing_fields.append({
                "field": field_name,
                "missing_records": missing_count,
                "required": definition.get("required", False),
            })

    required_fields_unverifiable = [
        field_name
        for field_name, definition in fields.items()
        if definition.get("required", False)
    ] if not original_records else []

    return {
        "original_record_count": len(original_records),
        "no_records_extracted": len(original_records) == 0,
        "configured_item_selector": config.get("item_selector"),
        "missing_fields": missing_fields,
        "required_fields_unverifiable": required_fields_unverifiable,
        "extraction_error": original_diagnostics.get("error"),
        "original_diagnostics": original_diagnostics,
    }


async def run_self_healing(config_id: int):
    """
    Generate and validate a selector repair.

    Confidence is calculated from actual extraction results,
    not from the AI-provided confidence score.
    """

    saved = get_saved_config(config_id)

    original_config = saved["config"]
    website_url = saved["site_url"]

    # Step 1: Capture the latest website HTML.
    html, final_url = await capture_latest_html(website_url)

    # Step 2: Test the original configuration.
    from app.services.extractor import extract_records

    try:
        original_records, original_diagnostics = extract_records(
            html,
            original_config,
            final_url,
        )
    except Exception as exc:
        original_records = []
        original_diagnostics = {
            "error": str(exc)[:500]
        }

    # Step 3: Build a failure report.
    failure_report = build_failure_report(
        original_config,
        original_records,
        original_diagnostics,
    )

    # Step 4: Check whether the original configuration is already healthy.
    fields = original_config.get("fields", {})

    required_fields = {
        name: definition
        for name, definition in fields.items()
        if definition.get("required", False)
    }

    if original_records:
        if required_fields:
            total_checks = len(original_records) * len(required_fields)

            successful_checks = sum(
                1
                for record in original_records
                for field_name in required_fields
                if record.get(field_name) is not None
                and str(record.get(field_name)).strip() != ""
            )

            original_confidence = successful_checks / total_checks
        else:
            original_confidence = 1.0
    else:
        original_confidence = 0.0

    if (
        original_records
        and original_confidence >= AUTO_APPLY_THRESHOLD
    ):
        return {
            "message": "Original configuration is already healthy. No repair needed.",
            "original_config_id": config_id,
            "status": "already_healthy",
            "confidence": original_confidence,
            "ai_confidence": None,
            "reason": "Existing selectors successfully extracted the required fields.",
            "original_record_count": len(original_records),
            "repaired_record_count": len(original_records),
            "failure_report": failure_report,
            "repaired_config": original_config,
            "sample_records": original_records[:5],
            "saved_version": None,
        }

    # Step 5: Ask Groq for replacement selectors.
    ai_repair = repair_config(
        website_url,
        original_config,
        html,
        failure_report,
    )

    # Step 6: Validate the AI suggestions against real HTML.
    validated = validate_repair(
        original_config,
        ai_repair,
        html,
        final_url,
    )

    measured_confidence = validated["confidence"]

        # Step 7: Decide what happens next.
    if measured_confidence >= AUTO_APPLY_THRESHOLD:
        status = "auto_applied"

        save_result = {
            "config": validated["config"],
            "records": validated["records"],
            "confidence": measured_confidence,
            "status": status,
        }

        saved_version = save_config(
            website_url,
            save_result,
        )

    elif measured_confidence >= HUMAN_REVIEW_THRESHOLD:
        status = "human_review_required"
        saved_version = None

    else:
        status = "rejected"
        saved_version = None

    # Step 8: Save the repair attempt in history.
    repair_history_id = save_repair_history(
        original_config_id=config_id,
        site_url=website_url,
        status=status,
        confidence=measured_confidence,
        ai_confidence=validated["ai_confidence"],
        reason=validated["reason"],
        failure_report=failure_report,
        proposed_config=validated["config"],
        sample_records=validated["records"][:5],
        saved_config_id=(
            saved_version["id"] if saved_version else None
        ),
    )

    return {
        "message": "Self-healing analysis completed",
        "original_config_id": config_id,
        "repair_history_id": repair_history_id,
        "status": status,
        "confidence": measured_confidence,
        "ai_confidence": validated["ai_confidence"],
        "reason": validated["reason"],
        "original_record_count": len(original_records),
        "repaired_record_count": len(validated["records"]),
        "failure_report": failure_report,
        "repaired_config": validated["config"],
        "sample_records": validated["records"][:5],
        "saved_version": saved_version,
    }
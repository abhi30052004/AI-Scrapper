
from bs4 import BeautifulSoup

from app.services.extractor import (
    ALLOWED_ATTRIBUTES,
    ALLOWED_TRANSFORMS,
    extract_records,
)
from app.services.validation_service import validate_records


def validate_repair(
    original_config: dict,
    repair: dict,
    html: str,
    base_url: str,
):
    if not isinstance(repair, dict):
        raise ValueError("Repair must be a JSON object")

    item_selector = repair.get("item_selector")
    repaired_fields = repair.get("fields")
    confidence = repair.get("confidence")

    if not isinstance(item_selector, str) or not item_selector.strip():
        raise ValueError("Invalid repaired item_selector")

    if not isinstance(repaired_fields, dict):
        raise ValueError("Repaired fields must be an object")

    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise ValueError("Invalid repair confidence")

    if not 0 <= confidence <= 1:
        raise ValueError("Repair confidence must be between 0 and 1")

    original_fields = original_config.get("fields", {})

    if set(repaired_fields) != set(original_fields):
        raise ValueError("Repair must preserve all original field names")

    # Test CSS selectors safely using BeautifulSoup.
    soup = BeautifulSoup(html, "lxml")

    try:
        containers = soup.select(item_selector)
    except Exception as exc:
        raise ValueError("Invalid repaired item_selector") from exc

    if not containers:
        raise ValueError("Repaired item_selector matched no elements")

    candidate = dict(original_config)
    candidate["item_selector"] = item_selector
    candidate["fields"] = {}

    for field_name, original_definition in original_fields.items():
        suggestion = repaired_fields[field_name]

        if not isinstance(suggestion, dict):
            raise ValueError(f"Invalid repair for field: {field_name}")

        selectors = suggestion.get("selectors")

        if not isinstance(selectors, list) or not selectors or len(selectors) > 3:
            raise ValueError(f"Invalid selectors for field: {field_name}")

        for selector in selectors:
            if not isinstance(selector, str) or not selector.strip():
                raise ValueError(f"Invalid CSS selector for field: {field_name}")

            try:
                for container in containers:
                    container.select(selector)
            except Exception as exc:
                raise ValueError(
                    f"Invalid CSS selector for field: {field_name}"
                ) from exc

        attr = suggestion.get(
            "attr",
            original_definition.get("attr", "text"),
        )

        if attr not in ALLOWED_ATTRIBUTES:
            raise ValueError(f"Unsupported attribute for field: {field_name}")

        transform = original_definition.get("transform", "strip")

        if transform not in ALLOWED_TRANSFORMS:
            raise ValueError(f"Unsupported transform for field: {field_name}")

        candidate["fields"][field_name] = {
            **original_definition,
            "selectors": selectors,
            "attr": attr,
        }

    records, diagnostics = extract_records(
        html,
        candidate,
        base_url,
    )

    if not records:
        raise ValueError("Repaired configuration extracted no records")

    val = validate_records(records, candidate)
    validation_confidence = val["confidence"]
    diagnostics["validation"] = val

    if validation_confidence < 0.60 or not val["is_valid"]:
        error_msg = "; ".join(val.get("validation_errors", []))
        return {
            "config": candidate,
            "records": records,
            "diagnostics": diagnostics,
            "confidence": round(validation_confidence, 3),
            "ai_confidence": round(float(confidence), 3),
            "reason": (
                "Rejected: repaired configuration failed validation. "
                + (error_msg or str(repair.get("reason", "")))[:400]
            ),
        }

    return {
        "config": candidate,
        "records": records,
        "diagnostics": diagnostics,
        "confidence": round(validation_confidence, 3),
        "ai_confidence": round(float(confidence), 3),
        "reason": str(repair.get("reason", ""))[:400],
    }

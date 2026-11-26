import re
from typing import Any
from urllib.parse import urljoin, urlsplit

from app.config import settings
from app.services.semantic_extractor import classify_candidate_non_product

STORAGE_PATTERN = re.compile(r"^\s*\d+(?:\.\d+)?\s*(?:gb|tb|mb|ram|rom)\s*$", re.I)

CURRENCY_SYMBOL_MAP = {
    "£": "GBP",
    "$": "USD",
    "€": "EUR",
    "₹": "INR",
    "RS": "INR",
    "RS.": "INR",
    "GBP": "GBP",
    "USD": "USD",
    "EUR": "EUR",
    "INR": "INR",
}

PRICE_EXTRACT_RE = re.compile(
    r"(?P<curr>[£$€₹]|Rs\.?|GBP|USD|EUR|INR)?\s*(?P<num>\d[\d,]*(?:\.\d{1,2})?)",
    re.IGNORECASE,
)


def is_storage_value(val: Any) -> bool:
    if val is None:
        return False
    return bool(STORAGE_PATTERN.match(str(val).strip()))


def normalize_currency_and_price(
    raw_price: Any,
    numeric_price: Any = None,
    currency: str | None = None,
) -> tuple[str | None, float | None, str | None, str | None]:
    """
    Preserve raw displayed price text, normalize ISO currency code, and parse numeric price.
    Distinguishes missing price (None) from invalid price (e.g. storage size or negative number).
    """
    raw_str = str(raw_price).strip() if raw_price not in (None, "") else None
    norm_curr = currency.strip().upper() if isinstance(currency, str) and currency.strip() else None
    if norm_curr in CURRENCY_SYMBOL_MAP:
        norm_curr = CURRENCY_SYMBOL_MAP[norm_curr]

    if raw_str and is_storage_value(raw_str):
        return None, None, norm_curr, f"Invalid price '{raw_str}': looks like storage capacity"

    parsed_num: float | None = None
    if isinstance(numeric_price, (int, float)) and not isinstance(numeric_price, bool):
        parsed_num = float(numeric_price)

    if raw_str:
        for sym, code in CURRENCY_SYMBOL_MAP.items():
            if sym in raw_str or raw_str.upper().startswith(sym):
                norm_curr = norm_curr or code
                break

        if parsed_num is None:
            m = PRICE_EXTRACT_RE.search(raw_str)
            if m:
                if not norm_curr and m.group("curr"):
                    norm_curr = CURRENCY_SYMBOL_MAP.get(m.group("curr").upper(), m.group("curr").upper())
                try:
                    parsed_num = float(m.group("num").replace(",", ""))
                except ValueError:
                    parsed_num = None
            elif "no upfront" in raw_str.lower() or "free" in raw_str.lower():
                parsed_num = 0.0
            else:
                return raw_str, None, norm_curr, f"Invalid non-numeric price '{raw_str}'"

    if parsed_num is not None and parsed_num < 0:
        return raw_str, None, norm_curr, f"Invalid negative price: {parsed_num}"

    return raw_str, round(parsed_num, 2) if parsed_num is not None else None, norm_curr, None


def validate_http_url(url: Any, base_url: str = "") -> tuple[str | None, str | None]:
    """Validate and resolve a product or image URL. Distinguishes missing vs invalid."""
    if url is None or str(url).strip() == "":
        return None, None
    raw = str(url).strip()
    if raw.startswith(("javascript:", "mailto:", "tel:", "data:", "#")):
        return None, f"Invalid URL scheme: {raw[:80]}"
    if base_url:
        raw = urljoin(base_url, raw)
    parts = urlsplit(raw)
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return None, f"Invalid URL format: {raw[:120]}"
    return raw, None


def merge_product_records(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """
    Merge incoming record (e.g. detail page or repeated batch) into base record.
    NEVER overwrites existing non-empty values with null, empty string, or empty collections.
    """
    merged = dict(base)
    list_merge_keys = {"image_urls", "storage_variants", "colour_variants", "related_offers", "validation_errors"}
    for key, val in incoming.items():
        if val in (None, "", [], {}):
            continue
        existing = merged.get(key)
        if key == "specifications" and isinstance(val, dict):
            prev_specs = existing if isinstance(existing, dict) else {}
            merged["specifications"] = {**val, **prev_specs}
        elif key in list_merge_keys and isinstance(val, list):
            prev_list = existing if isinstance(existing, list) else []
            combined = list(prev_list)
            for item in val:
                if item and item not in combined:
                    combined.append(item)
            merged[key] = combined
        elif existing in (None, "", [], {}):
            merged[key] = val
    return merged


def is_genuine_product(
    record: dict[str, Any],
    min_confidence: float | None = None,
) -> tuple[bool, str | None]:
    """
    Verify using multiple signals that a record represents a genuine purchasable product.
    Rejects non-product pages (terms, merger, community, partnerships, support, nav hubs)
    even when they mention prices.
    """
    if not isinstance(record, dict):
        return False, "invalid_record_type"

    if record.get("is_product") is False:
        return False, str(record.get("rejection_reason") or "classified_non_product")

    classification = str(record.get("product_classification") or "").strip().lower()
    if classification == "non_product":
        return False, str(record.get("rejection_reason") or "classification_non_product")

    title = record.get("title") or record.get("name") or record.get("product_name")
    url = record.get("product_url") or record.get("url")
    desc = record.get("description")

    non_prod_reason = classify_candidate_non_product(
        url=str(url or ""),
        title=str(title or ""),
        text=str(desc or ""),
    )
    if non_prod_reason:
        return False, non_prod_reason

    if not title or not str(title).strip():
        return False, "missing_title"

    # Multi-signal product identity check (price alone is NOT sufficient)
    signals = 0
    if url:
        signals += 1
    if record.get("brand") or (classification and classification not in {"", "non_product"}):
        signals += 1
    if record.get("image_urls") or record.get("image_url"):
        signals += 1
    if (
        record.get("price") is not None
        or record.get("numeric_price") is not None
        or record.get("monthly_payment") is not None
        or record.get("upfront_payment") is not None
    ):
        signals += 1
    if (
        record.get("specifications")
        or record.get("storage_variants")
        or record.get("colour_variants")
        or record.get("raw_json_ld")
        or record.get("availability")
        or record.get("rating")
    ):
        signals += 1

    if signals < 2:
        return False, "insufficient_product_signals"

    # Require at least one structural product identity signal besides price
    has_identity_signal = bool(
        url
        or record.get("image_urls")
        or record.get("image_url")
        or record.get("specifications")
        or record.get("raw_json_ld")
        or record.get("brand")
    )
    if not has_identity_signal:
        return False, "price_without_product_identity"

    threshold = min_confidence if min_confidence is not None else settings.min_product_confidence
    llm_conf = record.get("confidence_score")
    if isinstance(llm_conf, (int, float)) and llm_conf > 0 and llm_conf < threshold:
        return False, f"low_product_confidence:{llm_conf}"

    return True, None


def validate_and_normalize_record(
    record: dict[str, Any],
    base_url: str = "",
    required_fields: set[str] | None = None,
) -> dict[str, Any]:
    """
    Validate and normalize a single extracted product record.
    Preserves raw displayed values, normalizes currency/numeric prices & URLs,
    distinguishes missing vs invalid values, and records confidence & validation errors.
    """
    rec = dict(record)
    errors: list[str] = []
    missing_fields: list[str] = []
    invalid_fields: list[str] = []

    for k, v in list(rec.items()):
        if isinstance(v, str) and not v.strip():
            rec[k] = None

    title = rec.get("title") or rec.get("name") or rec.get("product_name")
    if isinstance(title, str):
        title = " ".join(title.split()).strip() or None
    rec["title"] = title
    if not title:
        missing_fields.append("title")
        errors.append("Missing required title")

    raw_url = rec.get("product_url") or rec.get("url")
    valid_url, url_err = validate_http_url(raw_url, base_url)
    if url_err:
        invalid_fields.append("product_url")
        errors.append(url_err)
        rec["product_url"] = None
    else:
        rec["product_url"] = valid_url
        if not valid_url:
            missing_fields.append("product_url")

    # Preserve raw price + normalize numeric price & currency
    raw_price = rec.get("price_raw") or rec.get("price")
    price_raw, numeric_price, currency, price_err = normalize_currency_and_price(
        raw_price, rec.get("numeric_price"), rec.get("currency") or rec.get("price_currency")
    )
    if price_err:
        invalid_fields.append("price")
        errors.append(price_err)
        rec["price"] = None
        rec["price_raw"] = None
        rec["numeric_price"] = None
        rec["currency"] = currency
    else:
        rec["price"] = price_raw
        rec["price_raw"] = price_raw
        rec["numeric_price"] = numeric_price
        rec["currency"] = currency

    # Normalize monthly_payment & upfront_payment while keeping raw strings
    if rec.get("monthly_payment"):
        mp_raw, mp_num, mp_curr, mp_err = normalize_currency_and_price(
            rec.get("monthly_payment"), rec.get("monthly_payment_numeric"), rec.get("currency")
        )
        if not mp_err:
            rec["monthly_payment"] = mp_raw
            rec["monthly_payment_numeric"] = mp_num
            if not rec.get("currency") and mp_curr:
                rec["currency"] = mp_curr
            if rec.get("price") is None and mp_raw:
                rec["price"] = mp_raw
                rec["price_raw"] = mp_raw
                rec["numeric_price"] = mp_num

    if rec.get("upfront_payment"):
        up_raw, up_num, up_curr, up_err = normalize_currency_and_price(
            rec.get("upfront_payment"), rec.get("upfront_payment_numeric"), rec.get("currency")
        )
        if not up_err:
            rec["upfront_payment"] = up_raw
            rec["upfront_payment_numeric"] = up_num
            if not rec.get("currency") and up_curr:
                rec["currency"] = up_curr

    if rec.get("price") is None and rec.get("numeric_price") is None:
        missing_fields.append("price")

    # Validate image_urls
    raw_imgs = rec.get("image_urls")
    if not raw_imgs and rec.get("image_url"):
        raw_imgs = [rec["image_url"]]
    clean_imgs: list[str] = []
    if isinstance(raw_imgs, list):
        for img in raw_imgs:
            v_img, img_err = validate_http_url(img, base_url)
            if v_img and v_img not in clean_imgs:
                clean_imgs.append(v_img)
            elif img_err:
                invalid_fields.append("image_urls")
    rec["image_urls"] = clean_imgs
    if clean_imgs and not rec.get("image_url"):
        rec["image_url"] = clean_imgs[0]

    if not rec.get("source_website") and base_url:
        rec["source_website"] = urlsplit(base_url).netloc.lower()

    if required_fields:
        for req_name in required_fields:
            if rec.get(req_name) in (None, "", []) and req_name not in missing_fields:
                missing_fields.append(req_name)
                errors.append(f"Missing required field '{req_name}'")

    # Compute deterministic extraction confidence
    score = 0.0
    if rec.get("title"):
        score += 0.30
    if rec.get("product_url"):
        score += 0.25
    if rec.get("price") is not None or rec.get("numeric_price") is not None or rec.get("monthly_payment") is not None:
        score += 0.25
    if rec.get("image_urls"):
        score += 0.10
    if rec.get("availability") or rec.get("rating") or rec.get("brand") or rec.get("description") or rec.get("specifications"):
        score += 0.10
    if invalid_fields:
        score = max(0.0, score - 0.25 * len(set(invalid_fields)))

    rec["extraction_confidence"] = round(min(1.0, score), 3)
    if not rec.get("confidence_score"):
        rec["confidence_score"] = rec["extraction_confidence"]
    rec["missing_fields"] = missing_fields
    rec["invalid_fields"] = sorted(set(invalid_fields))
    rec["validation_errors"] = errors
    rec["is_valid_record"] = bool(rec.get("title")) and not invalid_fields

    return rec


def validate_records(records: list[dict], config: dict | None = None):
    """
    Validate extracted sample or run records against schema and data quality rules.
    Preserves backwards-compatible output shape while supporting semantic/LLM fields.
    """
    fields = (config or {}).get("fields", {})

    missing_required: dict[str, list[int]] = {}
    duplicate_indexes: list[int] = []
    storage_price_indexes: list[int] = []
    missing_url_indexes: list[int] = []
    missing_title_indexes: list[int] = []
    irrelevant_indexes: list[int] = []
    invalid_url_indexes: list[int] = []
    validation_errors: list[str] = []
    failed_fields: set[str] = set()

    seen_fingerprints = set()
    seen_urls = set()

    total_records = len(records)
    if total_records == 0:
        return {
            "total_records": 0,
            "valid_records": 0,
            "invalid_records": 0,
            "missing_required_fields": {},
            "duplicate_record_indexes": [],
            "validation_errors": ["No records were extracted."],
            "failed_fields": ["records"],
            "confidence": 0.0,
            "is_valid": False,
        }

    for index, record in enumerate(records):
        non_empty_count = 0

        for field_name, definition in fields.items():
            val = record.get(field_name)
            if val not in (None, "", []):
                non_empty_count += 1

            if definition.get("required", False):
                if val is None or str(val).strip() == "" or (isinstance(val, list) and len(val) == 0):
                    missing_required.setdefault(field_name, []).append(index)
                    failed_fields.add(field_name)

        if not fields:
            non_empty_count = sum(
                1 for k, v in record.items()
                if k not in {"raw_json_ld", "raw_html_audit", "detail", "validation_errors", "missing_fields", "invalid_fields"}
                and v not in (None, "", [], {})
            )

        title_val = record.get("title") or record.get("name") or record.get("product_name")
        title_def = fields.get("title", {})
        if title_def.get("required", True):
            if not title_val or not str(title_val).strip():
                missing_title_indexes.append(index)
                failed_fields.add("title")

        url_val = record.get("product_url") or record.get("url")
        url_def = fields.get("product_url", {})
        if url_def.get("required", False) or "product_url" in fields:
            if not url_val or not str(url_val).strip():
                missing_url_indexes.append(index)
                failed_fields.add("product_url")

        if url_val:
            _, u_err = validate_http_url(url_val)
            if u_err:
                invalid_url_indexes.append(index)
                failed_fields.add("product_url")

        price_val = record.get("price")
        if price_val and is_storage_value(price_val):
            storage_price_indexes.append(index)
            failed_fields.add("price")

        if non_empty_count < 2 and total_records > 1:
            irrelevant_indexes.append(index)

        fingerprint = tuple(
            sorted(
                (k, str(v))
                for k, v in record.items()
                if k not in ("raw_json_ld", "raw_html_audit", "detail", "validation_errors", "missing_fields", "invalid_fields")
            )
        )
        if fingerprint in seen_fingerprints:
            duplicate_indexes.append(index)
        else:
            seen_fingerprints.add(fingerprint)

        if url_val:
            clean_u = str(url_val).strip().rstrip("/")
            if clean_u in seen_urls and index not in duplicate_indexes:
                duplicate_indexes.append(index)
            else:
                seen_urls.add(clean_u)

    if missing_title_indexes:
        validation_errors.append(
            f"Required titles are null or missing in {len(missing_title_indexes)}/{total_records} record(s)."
        )
    if missing_url_indexes:
        validation_errors.append(
            f"Product URLs are missing in {len(missing_url_indexes)}/{total_records} record(s)."
        )
    if invalid_url_indexes:
        validation_errors.append(
            f"Product URLs are invalid in {len(invalid_url_indexes)}/{total_records} record(s)."
        )
    if storage_price_indexes:
        sample_storage = records[storage_price_indexes[0]].get("price")
        validation_errors.append(
            f"Price extracted storage capacity ('{sample_storage}') instead of price in {len(storage_price_indexes)} record(s)."
        )
    if irrelevant_indexes:
        validation_errors.append(
            f"Matched {len(irrelevant_indexes)} irrelevant or incomplete element(s)."
        )
    if duplicate_indexes:
        validation_errors.append(
            f"Extracted records contain {len(duplicate_indexes)} duplicate record(s)."
        )
    for field_name, idxs in missing_required.items():
        if field_name not in ("title", "product_url"):
            validation_errors.append(
                f"Required field '{field_name}' is missing in {len(idxs)}/{total_records} record(s)."
            )

    valid_records = [
        record
        for i, record in enumerate(records)
        if i not in duplicate_indexes
        and i not in irrelevant_indexes
        and i not in missing_title_indexes
        and i not in invalid_url_indexes
        and i not in storage_price_indexes
        and all(
            not definition.get("required", False)
            or (record.get(name) is not None and str(record.get(name)).strip() != "")
            for name, definition in fields.items()
        )
    ]

    confidence = len(valid_records) / total_records if total_records > 0 else 0.0

    if missing_title_indexes:
        confidence = min(confidence, 0.20)
    if missing_url_indexes and ("product_url" in fields and fields["product_url"].get("required", False)):
        confidence = min(confidence, 0.30)
    if storage_price_indexes:
        confidence = min(confidence, 0.40)
    if irrelevant_indexes and len(irrelevant_indexes) > total_records * 0.3:
        confidence = min(confidence, 0.20)
    if duplicate_indexes and len(duplicate_indexes) > total_records * 0.5:
        confidence = min(confidence, 0.30)

    is_valid = (
        total_records > 0
        and len(valid_records) == total_records
        and len(duplicate_indexes) == 0
        and len(storage_price_indexes) == 0
        and len(missing_title_indexes) == 0
        and len(invalid_url_indexes) == 0
        and len(irrelevant_indexes) == 0
        and confidence >= 0.80
    )

    return {
        "total_records": total_records,
        "valid_records": len(valid_records),
        "invalid_records": total_records - len(valid_records),
        "missing_required_fields": missing_required,
        "duplicate_record_indexes": duplicate_indexes,
        "storage_price_indexes": storage_price_indexes,
        "missing_title_indexes": missing_title_indexes,
        "missing_url_indexes": missing_url_indexes,
        "invalid_url_indexes": invalid_url_indexes,
        "irrelevant_element_indexes": irrelevant_indexes,
        "validation_errors": validation_errors,
        "failed_fields": list(failed_fields),
        "confidence": round(confidence, 3),
        "is_valid": is_valid,
    }


def validate_and_normalize_records(
    records: list[dict[str, Any]],
    base_url: str = "",
    config: dict[str, Any] | None = None,
    filter_non_products: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Normalize and validate all records, rejecting non-product entries when enabled.
    Returns (accepted_normalized_records, summary_with_rejected_non_products).
    """
    fields = (config or {}).get("fields", {})
    req = {name for name, dfn in fields.items() if isinstance(dfn, dict) and dfn.get("required", False)}

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for r in records:
        norm = validate_and_normalize_record(r, base_url=base_url, required_fields=req)
        if filter_non_products:
            ok, reason = is_genuine_product(norm)
            if not ok:
                rejected.append({
                    "url": norm.get("product_url"),
                    "title": norm.get("title"),
                    "reason": reason or "rejected_non_product",
                    "stage": "validation_gate",
                })
                continue
        accepted.append(norm)

    summary = validate_records(accepted, config=config)
    summary["rejected_non_products"] = rejected
    summary["rejected_non_product_count"] = len(rejected)
    return accepted, summary

import re

STORAGE_PATTERN = re.compile(r"^\s*\d+(?:\.\d+)?\s*(?:gb|tb|mb|ram|rom)\s*$", re.I)


def is_storage_value(val) -> bool:
    if val is None:
        return False
    return bool(STORAGE_PATTERN.match(str(val).strip()))


def validate_records(records: list[dict], config: dict):
    """
    Validate extracted sample or run records against schema and data quality rules.

    Does not consider extraction valid when:
    - Required titles are null or empty.
    - Product URLs are missing.
    - Selectors match irrelevant nested elements.
    - Price selectors extract storage capacity (e.g. 600 GB) or unrelated text.
    - Records contain duplicates or incomplete records.
    """
    fields = config.get("fields", {})

    missing_required: dict[str, list[int]] = {}
    duplicate_indexes: list[int] = []
    storage_price_indexes: list[int] = []
    missing_url_indexes: list[int] = []
    missing_title_indexes: list[int] = []
    irrelevant_indexes: list[int] = []
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

        # Check required fields
        for field_name, definition in fields.items():
            val = record.get(field_name)
            if val not in (None, "", []):
                non_empty_count += 1

            if definition.get("required", False):
                if val is None or str(val).strip() == "" or (isinstance(val, list) and len(val) == 0):
                    missing_required.setdefault(field_name, []).append(index)
                    failed_fields.add(field_name)

        # Check title quality
        title_val = record.get("title") or record.get("name") or record.get("product_name")
        title_def = fields.get("title", {})
        if title_def.get("required", True):
            if not title_val or not str(title_val).strip():
                missing_title_indexes.append(index)
                failed_fields.add("title")

        # Check URL quality
        url_val = record.get("product_url") or record.get("url")
        url_def = fields.get("product_url", {})
        if url_def.get("required", False) or "product_url" in fields:
            if not url_val or not str(url_val).strip():
                missing_url_indexes.append(index)
                failed_fields.add("product_url")

        # Check price quality: detect storage capacity mistakenly extracted as price
        price_val = record.get("price")
        if price_val:
            if is_storage_value(price_val):
                storage_price_indexes.append(index)
                failed_fields.add("price")

        # Check for irrelevant nested elements (fewer than 2 non-empty values or empty records)
        if non_empty_count < 2 and total_records > 1:
            irrelevant_indexes.append(index)

        # Fingerprint duplicate check
        fingerprint = tuple(
            sorted(
                (k, str(v))
                for k, v in record.items()
                if k not in ("raw_json_ld", "detail")
            )
        )
        if fingerprint in seen_fingerprints:
            duplicate_indexes.append(index)
        else:
            seen_fingerprints.add(fingerprint)

        # Canonical URL duplicate check
        if url_val:
            clean_u = str(url_val).strip().rstrip("/")
            if clean_u in seen_urls and index not in duplicate_indexes:
                duplicate_indexes.append(index)
            else:
                seen_urls.add(clean_u)

    # Compile human-readable error reasons
    if missing_title_indexes:
        validation_errors.append(
            f"Required titles are null or missing in {len(missing_title_indexes)}/{total_records} record(s)."
        )
    if missing_url_indexes:
        validation_errors.append(
            f"Product URLs are missing in {len(missing_url_indexes)}/{total_records} record(s)."
        )
    if storage_price_indexes:
        sample_storage = records[storage_price_indexes[0]].get("price")
        validation_errors.append(
            f"Price selector extracted storage capacity ('{sample_storage}') instead of price in {len(storage_price_indexes)} record(s)."
        )
    if irrelevant_indexes:
        validation_errors.append(
            f"Selector matched {len(irrelevant_indexes)} irrelevant or empty nested element(s)."
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

    # Compute quality score
    valid_records = [
        record
        for i, record in enumerate(records)
        if i not in duplicate_indexes
        and i not in irrelevant_indexes
        and i not in missing_title_indexes
        and all(
            not definition.get("required", False)
            or (record.get(name) is not None and str(record.get(name)).strip() != "")
            for name, definition in fields.items()
        )
    ]

    # Baseline ratio
    confidence = len(valid_records) / total_records if total_records > 0 else 0.0

    # Apply strict penalties for fatal extraction errors
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
        "irrelevant_element_indexes": irrelevant_indexes,
        "validation_errors": validation_errors,
        "failed_fields": list(failed_fields),
        "confidence": round(confidence, 3),
        "is_valid": is_valid,
    }

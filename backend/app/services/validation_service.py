def validate_records(records: list[dict], config: dict):
    fields = config.get("fields", {})

    missing_required = {}
    duplicate_indexes = []
    seen = set()

    for index, record in enumerate(records):
        for field_name, definition in fields.items():
            if definition.get("required", False):
                value = record.get(field_name)

                if value is None or str(value).strip() == "":
                    missing_required.setdefault(
                        field_name, []
                    ).append(index)

        # Detect completely identical records.
        fingerprint = tuple(
            sorted(
                (key, str(value))
                for key, value in record.items()
            )
        )

        if fingerprint in seen:
            duplicate_indexes.append(index)
        else:
            seen.add(fingerprint)

    valid_records = [
        record
        for record in records
        if all(
            not definition.get("required", False)
            or (
                record.get(name) is not None
                and str(record.get(name)).strip() != ""
            )
            for name, definition in fields.items()
        )
    ]

    return {
        "total_records": len(records),
        "valid_records": len(valid_records),
        "invalid_records": len(records) - len(valid_records),
        "missing_required_fields": missing_required,
        "duplicate_record_indexes": duplicate_indexes,
        "is_valid": (
            len(records) > 0
            and len(valid_records) == len(records)
            and len(duplicate_indexes) == 0
        ),
    }
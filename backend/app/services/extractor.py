
from urllib.parse import urljoin

from bs4 import BeautifulSoup


ALLOWED_TRANSFORMS = {
    "strip",
    "strip_currency",
    "to_number",
    "to_date",
    "lowercase",
    "absolute_url",
}

ALLOWED_ATTRIBUTES = {
    "text",
    "href",
    "src",
    "title",
    "alt",
    "class",
}


def get_element_value(element, attr):
    """Safely extract text or an allowed HTML attribute."""

    if attr == "text":
        return element.get_text(" ", strip=True)

    value = element.get(attr)

    # BeautifulSoup returns class as a list.
    if isinstance(value, list):
        return " ".join(str(item) for item in value)

    return value


def apply_transform(value, transform, base_url):
    if value is None:
        return None

    value = str(value).strip()

    if transform == "strip":
        return value.strip()

    if transform == "strip_currency":
        return (
            value.replace("£", "")
            .replace("$", "")
            .replace("€", "")
            .strip()
        )

    if transform == "to_number":
        cleaned = "".join(
            c for c in value if c.isdigit() or c in ".-"
        )
        try:
            return float(cleaned)
        except ValueError:
            return None

    if transform == "lowercase":
        return value.lower()

    if transform == "absolute_url":
        return urljoin(base_url, value)

    if transform == "to_date":
        return value

    return value


def extract_records(html: str, config: dict, base_url: str):
    soup = BeautifulSoup(html, "lxml")

    item_selector = config.get("item_selector")

    if not item_selector:
        raise ValueError("Missing item_selector")

    containers = soup.select(item_selector)

    records = []

    diagnostics = {
        "container_count": len(containers),
        "matched_fields": {},
        "missing_fields": [],
    }

    for container in containers:
        record = {}

        for field_name, definition in config["fields"].items():
            selectors = definition.get("selectors", [])
            attr = definition.get("attr", "text")
            transform = definition.get("transform", "strip")

            if attr not in ALLOWED_ATTRIBUTES:
                raise ValueError(
                    f"Unsupported attribute: {attr}"
                )

            if transform not in ALLOWED_TRANSFORMS:
                raise ValueError(
                    f"Unsupported transform: {transform}"
                )

            value = None
            matched_selector = None

            for selector in selectors:
                element = container.select_one(selector)

                if element is None:
                    continue

                candidate = get_element_value(element, attr)

                if candidate:
                    value = candidate
                    matched_selector = selector
                    break

            if value is not None:
                value = apply_transform(
                    value,
                    transform,
                    base_url
                )

            record[field_name] = value

            if value is None:
                if definition.get("required", False):
                    diagnostics["missing_fields"].append(
                        field_name
                    )
            else:
                diagnostics["matched_fields"].setdefault(
                    field_name, {}
                )

                diagnostics["matched_fields"][field_name][
                    matched_selector
                ] = (
                    diagnostics["matched_fields"][field_name]
                    .get(matched_selector, 0) + 1
                )

        if any(value is not None for value in record.values()):
            records.append(record)

    return records, diagnostics

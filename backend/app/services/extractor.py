import json
import re
from urllib.parse import urljoin, urlsplit, urlunsplit
from bs4 import BeautifulSoup

ALLOWED_TRANSFORMS = {
    "strip",
    "strip_currency",
    "to_number",
    "to_date",
    "lowercase",
    "absolute_url",
    "remove_trailing_deals",
    "strip_deals",
}

ALLOWED_ATTRIBUTES = {
    "text",
    "href",
    "src",
    "title",
    "alt",
    "class",
    "data-src",
    "data-original",
    "data-lazy-src",
    "srcset",
    "content",
    "value",
    "itemprop",
    "data-testid",
    "aria-label",
}

STORAGE_PATTERN = re.compile(r"^\s*\d+(?:\.\d+)?\s*(?:gb|tb|mb|ram|rom)\s*$", re.I)


def is_storage_value(value: str) -> bool:
    """Return True if text represents a storage capacity rather than a price."""
    if not value:
        return False
    return bool(STORAGE_PATTERN.match(str(value).strip()))


def canonicalize_product_url(url: str, base_url: str = "") -> str:
    """Normalize a product URL for deduplication and matching."""
    if not url:
        return ""
    if base_url:
        url = urljoin(base_url, str(url).strip())
    parts = urlsplit(url)
    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        parts.path.rstrip("/") or "/",
        "",
        ""
    ))


def get_element_value(element, attr):
    """Safely extract text or an allowed HTML attribute."""
    if attr == "text":
        return element.get_text(" ", strip=True)

    value = element.get(attr)

    # Many product sites keep lazy-loaded media URLs outside src.
    if attr == "src" and not value:
        value = (
            element.get("data-src")
            or element.get("data-original")
            or element.get("data-lazy-src")
        )

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

    if transform in ("remove_trailing_deals", "strip_deals"):
        return re.sub(r"\s+deals?\s*$", "", value, flags=re.IGNORECASE).strip()

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


def extract_json_ld_products(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """
    Extract generic Schema.org ItemList and Product records from JSON-LD script tags.
    Preserves raw JSON-LD and resolves relative URLs.
    """
    products = []
    scripts = soup.find_all("script", type="application/ld+json")

    for s in scripts:
        if not s.string:
            continue
        try:
            data = json.loads(s.string)
        except Exception:
            continue

        objects = data if isinstance(data, list) else [data]
        if isinstance(data, dict) and "@graph" in data:
            graph = data["@graph"]
            objects = graph if isinstance(graph, list) else [graph]

        for obj in objects:
            if not isinstance(obj, dict):
                continue
            obj_type = obj.get("@type")

            if obj_type == "ItemList":
                items = obj.get("itemListElement", [])
                for elem in items:
                    if not isinstance(elem, dict):
                        continue
                    prod = elem.get("item", elem) if isinstance(elem.get("item"), dict) else elem
                    parsed = _parse_single_json_ld_product(prod, base_url, raw=elem)
                    if parsed:
                        products.append(parsed)
            elif obj_type == "Product":
                parsed = _parse_single_json_ld_product(obj, base_url, raw=obj)
                if parsed:
                    products.append(parsed)

    return products


def _parse_single_json_ld_product(item: dict, base_url: str, raw: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    url = item.get("url")
    if not url:
        return None
    abs_url = urljoin(base_url, str(url).strip())
    name = item.get("name") or item.get("title")

    image = item.get("image")
    if isinstance(image, dict):
        image = image.get("url")
    elif isinstance(image, list) and image:
        image = image[0] if isinstance(image[0], str) else (image[0].get("url") if isinstance(image[0], dict) else None)
    if image:
        image = urljoin(base_url, str(image).strip())

    offers = item.get("offers", [])
    if isinstance(offers, dict):
        offers = [offers]
    price = None
    currency = None
    if isinstance(offers, list) and offers:
        first_offer = offers[0]
        if isinstance(first_offer, dict):
            price = first_offer.get("price")
            currency = first_offer.get("priceCurrency")

    brand = item.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")

    return {
        "title": name,
        "name": name,
        "product_url": abs_url,
        "image_url": image,
        "offers": offers,
        "structured_price": price,
        "price_currency": currency,
        "brand": brand,
        "raw_json_ld": raw,
    }


def merge_dom_and_json_ld(dom_records: list[dict], json_ld_records: list[dict], base_url: str) -> list[dict]:
    """
    Merge JSON-LD and DOM records using canonical product URL as the identity key.
    Prefers valid structured fields when available and fills missing values from DOM.
    Preserves original price text from DOM extraction.
    """
    ld_by_url = {}
    for r in json_ld_records:
        u = canonicalize_product_url(r.get("product_url") or "", base_url)
        if u:
            ld_by_url[u] = r

    merged = []
    used_ld_urls = set()

    for d in dom_records:
        d_url = canonicalize_product_url(d.get("product_url") or d.get("url") or "", base_url)
        ld = ld_by_url.get(d_url)
        if ld:
            used_ld_urls.add(d_url)
            rec = dict(d)
            if ld.get("image_url") and not rec.get("image_url"):
                rec["image_url"] = ld["image_url"]
            elif ld.get("image_url") and "?" in str(rec.get("image_url", "")):
                rec["structured_image_url"] = ld["image_url"]

            if ld.get("offers"):
                rec["offers"] = ld["offers"]
            if ld.get("structured_price") is not None:
                rec["structured_price"] = ld["structured_price"]
            if ld.get("price_currency"):
                rec["price_currency"] = ld["price_currency"]
            if ld.get("raw_json_ld"):
                rec["raw_json_ld"] = ld["raw_json_ld"]

            # If DOM price was missing or was mistaken for storage, fill from structured
            if not rec.get("price") or is_storage_value(rec.get("price")):
                if ld.get("structured_price") is not None:
                    curr = ld.get("price_currency", "")
                    sym = "£" if curr == "GBP" else ("$" if curr == "USD" else ("€" if curr == "EUR" else curr))
                    rec["price"] = f"{sym}{ld['structured_price']}".strip()

            # Ensure complete title with brand
            if not rec.get("title") and ld.get("title"):
                brand = rec.get("brand") or ld.get("brand")
                ld_title = ld["title"]
                rec["title"] = f"{brand} {ld_title}".strip() if (brand and brand.lower() not in ld_title.lower()) else ld_title
            elif rec.get("title") and rec.get("brand") and rec["brand"].lower() not in rec["title"].lower():
                rec["title"] = f"{rec['brand']} {rec['title']}".strip()

            merged.append(rec)
        else:
            merged.append(dict(d))

    # Include any structured products that were not present in DOM listing
    for u, ld in ld_by_url.items():
        if u not in used_ld_urls:
            rec = dict(ld)
            if not rec.get("price") and ld.get("structured_price") is not None:
                curr = ld.get("price_currency", "")
                sym = "£" if curr == "GBP" else ("$" if curr == "USD" else ("€" if curr == "EUR" else curr))
                rec["price"] = f"{sym}{ld['structured_price']}".strip()
            merged.append(rec)

    return merged


def extract_records(html: str, config: dict, base_url: str):
    soup = BeautifulSoup(html, "lxml")

    item_selector = config.get("item_selector")
    if not item_selector:
        raise ValueError("Missing item_selector")

    containers = soup.select(item_selector)

    # Filter containers if an item_filter is configured or if dealing with article elements
    item_filter = config.get("item_filter")
    if item_filter:
        containers = [c for c in containers if c.select_one(item_filter)]
    elif item_selector == "article":
        # If raw article was selected, exclude promoted deal-group links
        handset_cards = [c for c in containers if c.select_one('a[href$="-deals/"]')]
        if handset_cards:
            containers = handset_cards

    records = []
    diagnostics = {
        "container_count": len(containers),
        "matched_fields": {},
        "missing_fields": [],
    }

    for container in containers:
        record = {}

        for field_name, definition in config.get("fields", {}).items():
            selectors = definition.get("selectors", [])
            attr = definition.get("attr", "text")
            transform = definition.get("transform", "strip")

            if attr not in ALLOWED_ATTRIBUTES:
                raise ValueError(f"Unsupported attribute: {attr}")

            if transform not in ALLOWED_TRANSFORMS:
                raise ValueError(f"Unsupported transform: {transform}")

            value = None
            matched_selector = None

            for selector in selectors:
                if definition.get("multiple", False):
                    elements = container.select(selector)
                    candidates = [get_element_value(el, attr) for el in elements]
                    candidates = [item for item in candidates if item not in (None, "")]
                    if candidates:
                        value = [apply_transform(item, transform, base_url) for item in candidates]
                        matched_selector = selector
                        break
                else:
                    element = container.select_one(selector)
                    if element is None:
                        continue
                    candidate = get_element_value(element, attr)
                    if candidate not in (None, ""):
                        # Do not mistake storage capacity (e.g. 600 GB) for a price
                        if field_name == "price" and is_storage_value(candidate):
                            continue
                        value = apply_transform(candidate, transform, base_url)
                        matched_selector = selector
                        break

            record[field_name] = value

            if value is None:
                if definition.get("required", False):
                    diagnostics["missing_fields"].append(field_name)
            else:
                diagnostics["matched_fields"].setdefault(field_name, {})
                diagnostics["matched_fields"][field_name][matched_selector] = (
                    diagnostics["matched_fields"][field_name].get(matched_selector, 0) + 1
                )

        # Composite title generation if brand & model are present
        if record.get("brand") and record.get("model"):
            full_title = f"{record['brand']} {record['model']}".strip()
            if not record.get("title") or record["title"] == record["model"]:
                record["title"] = full_title
        elif record.get("brand") and record.get("title") and record["brand"].lower() not in record["title"].lower():
            record["title"] = f"{record['brand']} {record['title']}".strip()

        if record.get("title"):
            record["title"] = re.sub(r"\s+deals?\s*$", "", record["title"], flags=re.IGNORECASE).strip()

        if any(v is not None for v in record.values()):
            records.append(record)

    # Extract Schema.org JSON-LD structured data and merge
    json_ld_products = extract_json_ld_products(soup, base_url)
    diagnostics["json_ld_count"] = len(json_ld_products)

    if json_ld_products:
        records = merge_dom_and_json_ld(records, json_ld_products, base_url)

    diagnostics["merged_count"] = len(records)
    return records, diagnostics

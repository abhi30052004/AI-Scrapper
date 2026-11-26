import hashlib
import json
import re
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit
from bs4 import BeautifulSoup, Comment, Tag

PRICE_TEXT_RE = re.compile(
    r"(?:[£$€₹]|Rs\.?|GBP|USD|EUR|INR)\s*\d[\d,]*(?:\.\d{1,2})?"
    r"(?:\s*(?:per\s+month|a\s+month|/mo|/month|pm|upfront|each|total\s+cost))?",
    re.IGNORECASE,
)

MONTHLY_PRICE_RE = re.compile(
    r"(?:[£$€₹]|Rs\.?)\s*\d[\d,]*(?:\.\d{1,2})?\s*(?:per\s+month|a\s+month|/mo|/month|pm)\b",
    re.IGNORECASE,
)

UPFRONT_PRICE_RE = re.compile(
    r"(?:(?:[£$€₹]|Rs\.?)\s*\d[\d,]*(?:\.\d{1,2})?\s*upfront\b|\bno\s+upfront\s+cost\b)",
    re.IGNORECASE,
)

STORAGE_VARIANT_RE = re.compile(r"\b((?:16|32|64|128|256|512)\s*GB|[1-8]\s*TB)\b(?!\s*(?:of\s+)?(?:5G|4G|data|allowance))", re.IGNORECASE)

COLOUR_WORDS = {
    "black", "white", "silver", "gold", "blue", "mist blue", "sky blue", "ultramarine",
    "pink", "green", "sage", "lavender", "purple", "violet", "cobalt violet", "red",
    "orange", "yellow", "grey", "gray", "graphite", "titanium", "burgundy", "glacier",
    "teal", "midnight", "starlight", "natural titanium", "desert titanium", "peach",
    "coral", "cream", "bronze", "navy",
}

OFFER_TEXT_RE = re.compile(
    r"(?:save\s+up\s+to\s+[£$€₹]?\d[\d,]*(?:\.\d{1,2})?|"
    r"claim\s+up\s+to\s+[£$€₹]?\d[\d,]*(?:\.\d{1,2})?(?:\s+credit)?|"
    r"black\s+friday\s+(?:offer|deal)|"
    r"\d+%\s+off|"
    r"free\s+(?:delivery|gift|earbuds|case)|"
    r"student\s+discount|"
    r"up\s+to\s+[£$€₹]\d+\s+(?:off|credit|cashback))",
    re.IGNORECASE,
)

AVAILABILITY_RE = re.compile(
    r"\b(?:in\s+stock(?:\s*\([^)]+\))?|out\s+of\s+stock|available|unavailable|pre-?order|sold\s+out|coming\s+soon)\b",
    re.IGNORECASE,
)

RATING_TEXT_RE = re.compile(
    r"(?:\b[1-5](?:\.\d)?\s*(?:out\s+of\s+5|/5|stars?)\b|\b(?:one|two|three|four|five)\s+stars?\b)",
    re.IGNORECASE,
)

REVIEWS_COUNT_RE = re.compile(r"\b(\d[\d,]*)\s+reviews?\b", re.IGNORECASE)

STAR_WORD_MAP = {
    "one": "1/5",
    "two": "2/5",
    "three": "3/5",
    "four": "4/5",
    "five": "5/5",
}

NOISE_TAGS = {"script", "style", "svg", "noscript", "iframe", "template", "canvas"}
PAGE_CHROME_TAGS = {"nav", "footer", "aside"}
NOISE_ATTR_RE = re.compile(
    r"(?:cookie|consent|gdpr|onetrust|advert|ad-slot|adsbox|banner-ad|newsletter|popup|modal-backdrop|flyout|breadcrumb|pagination|pager)",
    re.IGNORECASE,
)
PROMOTED_RE = re.compile(r"\b(?:promoted|sponsored|advertisement)\b", re.IGNORECASE)

# Generic URL & text rejection rules for non-product pages
NON_PRODUCT_LINK_RE = re.compile(
    r"^(?:#|javascript:|mailto:|tel:)|"
    r"/(?:login|signin|signup|register|privacy|terms|terms-and-conditions|legal|cookie|cookies|"
    r"help|support|faq|contact|about|about-us|company|careers|press|news|blog|articles|"
    r"merger|partnerships|partners|sponsor|community|forum|why-[a-z0-9-]+/network|"
    r"basket|review-basket|cart|checkout|wishlist|my-account|account|anonymous-topup)(?:/|$|\?)",
    re.IGNORECASE,
)

NON_PRODUCT_URL_RULES: list[tuple[str, re.Pattern]] = [
    ("terms_and_conditions", re.compile(r"/(?:terms|terms-conditions|legal|privacy|cookie|price-increase|bills-and-contracts)(?:/|$|-|\?)", re.I)),
    ("support_or_help", re.compile(r"/(?:support|help|faqs?|contact|store-locator)(?:/|$|\?)", re.I)),
    ("merger_or_company_info", re.compile(r"/(?:merger|about|company|careers|press|investor|why-[a-z0-9-]+)(?:/|$|\?)", re.I)),
    ("community_page", re.compile(r"(?:^https?://community\.|/community(?:/|$|\?)|/forum(?:/|$|\?))", re.I)),
    ("partnership_page", re.compile(r"/(?:partnerships?|sponsorships?|sponsorship|charity)(?:/|$|\?)", re.I)),
    ("blog_or_news", re.compile(r"/(?:blog|news|articles|editorial|guides)(?:/|$|\?)", re.I)),
    ("account_or_cart", re.compile(r"/(?:basket|review-basket|cart|checkout|login|signin|my-account|anonymous-topup)(?:/|$|\?)", re.I)),
    ("generic_offers_hub", re.compile(r"/(?:existing-customer-offers|student-discount|black-friday/?$)", re.I)),
]

NON_PRODUCT_TEXT_RULES: list[tuple[str, re.Pattern]] = [
    ("terms_and_conditions", re.compile(r"^(?:terms\s+(?:and|&)\s+conditions|privacy\s+policy|cookie\s+policy)\b|\b(?:each\s+april,?\s+your\s+monthly\s+charge\s+will\s+increase)\b", re.I)),
    ("merger_or_company_info", re.compile(r"\b(?:merger\s+completed|vodafone\s+uk\s+merger|about\s+us|our\s+company|why\s+choose\b|on\s+the\s+nation.?s\s+network|nation.?s\s+(?:biggest|fastest)\s+network|bn\s+investment)\b", re.I)),
    ("community_page", re.compile(r"\b(?:connect\s+with\s+our\s+community|share\s+questions\s+and\s+answers\s+with\s+your\s+community)\b", re.I)),
    ("partnership_page", re.compile(r"\b(?:three\s+partners|powerful\s+alliance|charity\s+partner)\b", re.I)),
    ("navigation_hub", re.compile(r"\b(?:take\s+a\s+look\s+around|show\s+me\s+more\b.*\bdeals|get\s+more\s+with\b)\b", re.I)),
]


def normalize_inline_text(text: str) -> str:
    """Collapse whitespace and fix split currency/decimal tokens such as '£ 29 . 00'."""
    if not text:
        return ""
    cleaned = " ".join(str(text).split())
    cleaned = re.sub(r"([£$€₹])\s+(\d)", r"\1\2", cleaned)
    cleaned = re.sub(r"(\d)\s*\.\s*(\d{2})\b", r"\1.\2", cleaned)
    cleaned = re.sub(r"(\d)\s*,\s*(\d{3})\b", r"\1,\2", cleaned)
    return cleaned.strip()


def canonicalize_url(url: str, base_url: str = "") -> str:
    """Normalize a URL to absolute canonical form without tracking query noise."""
    if not url:
        return ""
    raw = str(url).strip()
    if raw.startswith(("javascript:", "mailto:", "tel:", "#")):
        return ""
    if base_url:
        raw = urljoin(base_url, raw)
    parts = urlsplit(raw)
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return ""
    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        parts.path.rstrip("/") or "/",
        "",
        "",
    ))


def classify_candidate_non_product(
    url: str | None = None,
    title: str | None = None,
    text: str | None = None,
    check_body_text: bool = True,
) -> str | None:
    """
    Deterministically detect non-product pages/cards (terms, merger, community,
    partnership, support, navigation hubs). Returns rejection reason or None.
    """
    url_str = str(url or "").strip()
    title_str = str(title or "").strip()
    text_str = str(text or "").strip()

    if url_str:
        for reason, pattern in NON_PRODUCT_URL_RULES:
            if pattern.search(url_str):
                return f"non_product_url:{reason}"

    target_text = f"{title_str} {text_str[:300]}".strip() if check_body_text else title_str
    if target_text:
        for reason, pattern in NON_PRODUCT_TEXT_RULES:
            if pattern.search(target_text):
                return f"non_product_content:{reason}"

    return None


def _resolve_abs_url(url: str | None, base_url: str) -> str | None:
    if not url:
        return None
    raw = str(url).strip()
    if not raw or raw.startswith(("javascript:", "mailto:", "tel:", "data:", "#")):
        return None
    abs_url = urljoin(base_url, raw) if base_url else raw
    parts = urlsplit(abs_url)
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return None
    return abs_url


def _extract_img_url(img: Tag, base_url: str) -> str | None:
    for attr in ("src", "data-src", "data-original", "data-lazy-src", "data-url"):
        val = img.get(attr)
        if val:
            resolved = _resolve_abs_url(val, base_url)
            if resolved:
                return resolved
    srcset = img.get("srcset")
    if srcset:
        first_part = str(srcset).split(",")[0].strip().split(" ")[0]
        resolved = _resolve_abs_url(first_part, base_url)
        if resolved:
            return resolved
    return None


def extract_json_ld_data(soup: BeautifulSoup, base_url: str) -> dict[str, Any]:
    """Extract Schema.org Product, ProductGroup, and ItemList entries from JSON-LD before DOM stripping."""
    products: list[dict[str, Any]] = []
    item_lists: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for script in soup.find_all("script", type=re.compile(r"application/ld\+json", re.I)):
        raw_text = script.string or script.get_text()
        if not raw_text or not raw_text.strip():
            continue
        try:
            data = json.loads(raw_text)
        except Exception:
            continue

        queue: list[Any] = data if isinstance(data, list) else [data]
        while queue:
            obj = queue.pop(0)
            if not isinstance(obj, dict):
                continue
            if "@graph" in obj and isinstance(obj["@graph"], list):
                queue.extend(obj["@graph"])

            obj_type = obj.get("@type")
            types = obj_type if isinstance(obj_type, list) else [obj_type]
            types_lower = {str(t).lower() for t in types if t}

            if "itemlist" in types_lower:
                elements = obj.get("itemListElement") or []
                list_items = []
                for elem in elements:
                    if not isinstance(elem, dict):
                        continue
                    prod = elem.get("item") if isinstance(elem.get("item"), dict) else elem
                    parsed = _parse_json_ld_product(prod, base_url, raw=elem)
                    if parsed:
                        list_items.append(parsed)
                        key = canonicalize_url(parsed.get("product_url") or "", base_url) or parsed.get("title", "")
                        if key and key not in seen_urls:
                            seen_urls.add(key)
                            products.append(parsed)
                item_lists.append({
                    "name": obj.get("name"),
                    "numberOfItems": obj.get("numberOfItems"),
                    "items_count": len(list_items),
                })

            elif "productgroup" in types_lower:
                variants = obj.get("hasVariant") or []
                parsed_group = _parse_json_ld_product(obj, base_url, raw=obj)
                if parsed_group:
                    key = canonicalize_url(parsed_group.get("product_url") or "", base_url) or parsed_group.get("title", "")
                    if key and key not in seen_urls:
                        seen_urls.add(key)
                        products.append(parsed_group)
                if isinstance(variants, list):
                    for var in variants[:10]:
                        if isinstance(var, dict):
                            pv = _parse_json_ld_product(var, base_url, raw=var)
                            if pv and pv.get("product_url"):
                                key = canonicalize_url(pv["product_url"], base_url)
                                if key and key not in seen_urls:
                                    seen_urls.add(key)
                                    products.append(pv)

            elif "product" in types_lower:
                parsed = _parse_json_ld_product(obj, base_url, raw=obj)
                if parsed:
                    key = canonicalize_url(parsed.get("product_url") or "", base_url) or parsed.get("title", "")
                    if not key or key not in seen_urls:
                        if key:
                            seen_urls.add(key)
                        products.append(parsed)

    return {
        "products": products,
        "item_lists": item_lists,
    }


def _parse_json_ld_product(item: dict, base_url: str, raw: dict) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    name = item.get("name") or item.get("title")
    url = _resolve_abs_url(item.get("url"), base_url)
    if not name and not url:
        return None

    images: list[str] = []
    raw_img = item.get("image")
    img_candidates = raw_img if isinstance(raw_img, list) else [raw_img]
    for candidate in img_candidates:
        if isinstance(candidate, dict):
            candidate = candidate.get("url") or candidate.get("contentUrl")
        if isinstance(candidate, str):
            resolved = _resolve_abs_url(candidate, base_url)
            if resolved and resolved not in images:
                images.append(resolved)

    offers_raw = item.get("offers")
    offers = offers_raw if isinstance(offers_raw, list) else ([offers_raw] if isinstance(offers_raw, dict) else [])
    price = None
    currency = None
    availability = None
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        if price is None:
            price = offer.get("price") or offer.get("lowPrice") or offer.get("highPrice")
        if currency is None:
            currency = offer.get("priceCurrency")
        if availability is None and offer.get("availability"):
            availability = str(offer.get("availability")).split("/")[-1]
        if not url and offer.get("url"):
            url = _resolve_abs_url(offer.get("url"), base_url)

    brand = item.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")

    rating_val = None
    reviews_count = None
    agg = item.get("aggregateRating")
    if isinstance(agg, dict):
        if agg.get("ratingValue") is not None:
            best = agg.get("bestRating", 5)
            rating_val = f"{agg['ratingValue']}/{best}"
        if agg.get("reviewCount") is not None:
            reviews_count = str(agg["reviewCount"])
        elif agg.get("ratingCount") is not None:
            reviews_count = str(agg["ratingCount"])

    description = item.get("description")
    if description:
        description = normalize_inline_text(str(description))

    return {
        "title": normalize_inline_text(str(name)) if name else None,
        "brand": normalize_inline_text(str(brand)) if brand else None,
        "category": normalize_inline_text(str(item.get("category"))) if item.get("category") else None,
        "price": price,
        "currency": str(currency).strip().upper() if currency else None,
        "description": description,
        "image_urls": images,
        "product_url": url,
        "availability": availability,
        "rating": rating_val,
        "reviews_count": reviews_count,
        "sku": item.get("sku"),
        "raw_json_ld": raw,
    }


def extract_page_metadata(soup: BeautifulSoup, base_url: str) -> dict[str, Any]:
    """Extract general page-level metadata (title, canonical, meta description, og tags, h1)."""
    title = normalize_inline_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
    h1_el = soup.find("h1")
    h1_text = normalize_inline_text(h1_el.get_text(" ", strip=True)) if h1_el else None

    meta_desc = None
    desc_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    if desc_tag and desc_tag.get("content"):
        meta_desc = normalize_inline_text(desc_tag.get("content"))

    og_title = None
    og_title_tag = soup.find("meta", attrs={"property": "og:title"})
    if og_title_tag and og_title_tag.get("content"):
        og_title = normalize_inline_text(og_title_tag.get("content"))

    og_image = None
    og_img_tag = soup.find("meta", attrs={"property": "og:image"})
    if og_img_tag and og_img_tag.get("content"):
        og_image = _resolve_abs_url(og_img_tag.get("content"), base_url)

    canonical_url = None
    canon_tag = soup.find("link", rel=lambda r: r and "canonical" in [x.lower() for x in (r if isinstance(r, list) else [r])])
    if canon_tag and canon_tag.get("href"):
        canonical_url = _resolve_abs_url(canon_tag.get("href"), base_url)

    return {
        "source_url": base_url,
        "canonical_url": canonical_url or base_url,
        "page_title": title,
        "h1": h1_text,
        "meta_description": meta_desc,
        "og_title": og_title,
        "og_image": og_image,
    }


def clean_dom_for_semantics(soup: BeautifulSoup) -> BeautifulSoup:
    """Remove scripts, styles, navigation, ads, and non-content elements while preserving product structures."""
    for comment in soup.find_all(string=lambda val: isinstance(val, Comment)):
        comment.extract()

    for tag in list(soup.find_all(NOISE_TAGS)):
        tag.decompose()

    for tag in list(soup.find_all(PAGE_CHROME_TAGS)):
        text = tag.get_text(" ", strip=True)
        if not PRICE_TEXT_RE.search(text) or len(tag.find_all("a", href=True)) > 25:
            tag.decompose()

    for header in list(soup.find_all("header")):
        if not header.find_parent("article") and not PRICE_TEXT_RE.search(header.get_text(" ", strip=True)):
            header.decompose()

    for el in list(soup.find_all(True)):
        if not getattr(el, "attrs", None):
            continue
        id_str = str(el.get("id") or "")
        cls_val = el.get("class") or []
        cls_str = " ".join(cls_val) if isinstance(cls_val, list) else str(cls_val)
        role_str = str(el.get("role") or "")
        if role_str in {"banner", "navigation", "contentinfo", "search"}:
            if not el.find("article") and len(PRICE_TEXT_RE.findall(el.get_text(" ", strip=True))) < 2:
                el.decompose()
                continue
        if NOISE_ATTR_RE.search(id_str) or NOISE_ATTR_RE.search(cls_str):
            if not el.find("article") and len(PRICE_TEXT_RE.findall(el.get_text(" ", strip=True))) < 3:
                el.decompose()

    return soup


def _card_signal_score(el: Tag, base_url: str = "") -> tuple[bool, float, bool]:
    """Score whether a single DOM element looks like a genuine product card."""
    text = normalize_inline_text(el.get_text(" ", strip=True))
    if not text or len(text) < 5 or len(text) > 2500:
        return False, 0.0, False

    raw_links = el.find_all("a", href=True)
    product_links = []
    for a in raw_links:
        href = str(a.get("href") or "")
        if NON_PRODUCT_LINK_RE.search(href):
            continue
        abs_h = _resolve_abs_url(href, base_url) or href
        product_links.append(abs_h)

    if not product_links:
        return False, 0.0, False

    has_price = bool(PRICE_TEXT_RE.search(text))
    has_img = el.find("img") is not None
    has_heading = el.find(["h1", "h2", "h3", "h4"]) is not None
    has_itemtype = "product" in str(el.get("itemtype") or "").lower()

    if not (has_price or has_img or has_itemtype or has_heading):
        return False, 0.0, False

    nested_articles = el.find_all("article")
    if len(nested_articles) > 1:
        return False, 0.0, False

    score = 1.0
    if has_price:
        score += 3.5
    if has_img:
        score += 1.5
    if has_heading:
        score += 1.0
    if has_itemtype:
        score += 2.0
    if el.name == "article" or el.find("article") is not None:
        score += 1.5
    if len(product_links) <= 4:
        score += 0.5
    elif len(product_links) > 12:
        score -= 2.5
    return True, max(0.1, score), has_price


def _expand_section_into_inner_cards(section: Tag, base_url: str) -> list[Tag]:
    """
    If an outer container wraps multiple distinct product cards (e.g. a carousel or
    multi-product promo grid), expand it into its inner product card elements.
    """
    # Look for repeating sibling groups inside this section first
    best_inner: list[Tag] = []
    best_score = 0.0

    for sub_parent in section.find_all(["div", "ul", "ol", "section"]):
        children = [c for c in sub_parent.find_all(recursive=False) if isinstance(c, Tag)]
        if len(children) < 2:
            continue
        by_tag: dict[str, list[Tag]] = {}
        for child in children:
            by_tag.setdefault(child.name, []).append(child)
        for _, group in by_tag.items():
            if len(group) < 2:
                continue
            valid: list[Tag] = []
            scores: list[float] = []
            price_hits = 0
            for item in group:
                ok, s, has_p = _card_signal_score(item, base_url)
                if ok:
                    valid.append(item)
                    scores.append(s)
                    if has_p:
                        price_hits += 1
            if len(valid) >= 2 and price_hits >= 2:
                sc = len(valid) * (sum(scores) / len(scores))
                if sc > best_score:
                    best_score = sc
                    best_inner = valid

    if best_inner:
        return best_inner

    # Fallback: check distinct shop/product anchor blocks inside an oversized section
    if len(normalize_inline_text(section.get_text(" ", strip=True))) > 500:
        shop_links = [
            a for a in section.find_all("a", href=True)
            if not NON_PRODUCT_LINK_RE.search(str(a.get("href") or ""))
            and any(k in str(a.get("href") or "").lower() for k in ("/shop/", "/product", "/phones/", "/broadband", "/tablets", "/laptops", "-deals"))
        ]
        distinct_hrefs = {canonicalize_url(str(a.get("href")), base_url) for a in shop_links}
        if len(distinct_hrefs) >= 3:
            sub_cards: list[Tag] = []
            seen_nodes: set[int] = set()
            for a in shop_links:
                # Walk up to find the smallest card block holding a single distinct product URL
                curr = a.parent
                chosen = None
                for _ in range(7):
                    if curr is None or curr == section:
                        break
                    hrefs_inside = {
                        canonicalize_url(str(x.get("href")), base_url)
                        for x in curr.find_all("a", href=True)
                        if not NON_PRODUCT_LINK_RE.search(str(x.get("href") or ""))
                    }
                    hrefs_inside.discard("")
                    if len(hrefs_inside) <= 2 and len(normalize_inline_text(curr.get_text(" ", strip=True))) >= 20:
                        chosen = curr
                    elif len(hrefs_inside) > 2:
                        break
                    curr = curr.parent
                if chosen is not None and id(chosen) not in seen_nodes:
                    seen_nodes.add(id(chosen))
                    sub_cards.append(chosen)
            if len(sub_cards) >= 2:
                return sub_cards

    return [section]


def _is_ancestor_of_any(candidate: Tag, others: list[Tag]) -> bool:
    other_ids = {id(o) for o in others}
    for desc in candidate.find_all(True):
        if id(desc) in other_ids:
            return True
    return False


def detect_product_card_elements(
    soup: BeautifulSoup,
    json_ld_urls: set[str] | None = None,
    base_url: str = "",
) -> list[Tag]:
    """
    Detect product card elements using site-agnostic structural repetition and semantic signals.
    Handles both single-grid listings (uSwitch, Books to Scrape) and multi-section
    homepages/carousels (Three UK) without relying on one site's CSS selectors.
    """
    candidates_clusters: list[tuple[float, list[Tag], float]] = []

    # 1. Explicit Schema.org microdata Product elements
    microdata_cards = [
        el for el in soup.find_all(attrs={"itemtype": re.compile(r"schema\.org/Product", re.I)})
        if _card_signal_score(el, base_url)[0]
    ]
    if len(microdata_cards) >= 2:
        candidates_clusters.append((len(microdata_cards) * 8.0, microdata_cards, 1.0))

    # 2. Standalone <article> cluster
    article_cards: list[Tag] = []
    article_scores: list[float] = []
    article_prices = 0
    for art in soup.find_all("article"):
        ok, s, has_p = _card_signal_score(art, base_url)
        if ok:
            article_cards.append(art)
            article_scores.append(s)
            if has_p:
                article_prices += 1
    if len(article_cards) >= 2:
        price_ratio = article_prices / len(article_cards)
        avg_s = sum(article_scores) / len(article_scores)
        factor = 1.4 if price_ratio >= 0.5 else 0.35
        candidates_clusters.append((len(article_cards) * avg_s * factor, article_cards, price_ratio))

    # 3. Structural sibling cluster scoring across containers
    for parent in soup.find_all(["div", "ul", "ol", "section", "main", "tbody"]):
        children = [c for c in parent.find_all(recursive=False) if isinstance(c, Tag)]
        if len(children) < 2:
            continue

        by_tag: dict[str, list[Tag]] = {}
        for child in children:
            by_tag.setdefault(child.name, []).append(child)

        for tag_name, group in by_tag.items():
            if len(group) < 2:
                continue
            valid_cards: list[Tag] = []
            card_scores: list[float] = []
            price_count = 0
            for item in group:
                target = item
                inner_articles = item.find_all("article")
                if len(inner_articles) == 1 and item.name not in {"article", "li"}:
                    target = inner_articles[0]
                ok, s, has_p = _card_signal_score(target, base_url)
                if ok:
                    valid_cards.append(target)
                    card_scores.append(s)
                    if has_p:
                        price_count += 1

            if len(valid_cards) < 2:
                continue

            avg_score = sum(card_scores) / len(card_scores)
            price_ratio = price_count / len(valid_cards)
            factor = 1.25 if price_ratio >= 0.5 else (0.7 if price_ratio > 0 else 0.25)
            if tag_name in {"article", "li"}:
                factor *= 1.15
            cluster_score = len(valid_cards) * avg_score * factor

            if json_ld_urls:
                matched = 0
                for c in valid_cards[:15]:
                    for a in c.find_all("a", href=True):
                        if canonicalize_url(a.get("href"), base_url) in json_ld_urls:
                            matched += 1
                            break
                if matched > 0:
                    cluster_score *= (1.0 + min(1.0, matched / min(len(valid_cards), 15)))

            candidates_clusters.append((cluster_score, valid_cards, price_ratio))

    if not candidates_clusters:
        return []

    # Pick primary highest-scoring cluster
    _, best_cluster, best_price_ratio = max(candidates_clusters, key=lambda pair: pair[0])

    # Expand any section card that wraps multiple inner product cards (e.g. homepage carousels)
    expanded: list[Tag] = []
    seen_el_ids: set[int] = set()
    for card in best_cluster:
        inner = _expand_section_into_inner_cards(card, base_url)
        for item in inner:
            if id(item) not in seen_el_ids:
                seen_el_ids.add(id(item))
                expanded.append(item)

    # On heterogeneous homepages (fewer than 30 cards in the primary cluster), also include
    # strong inner product clusters and featured/hero product blocks
    if len(expanded) < 30:
        for _, cluster, p_ratio in sorted(candidates_clusters, key=lambda p: p[0], reverse=True):
            if p_ratio < 0.3:
                continue
            for item in cluster:
                if id(item) in seen_el_ids:
                    continue
                if _is_ancestor_of_any(item, expanded):
                    continue
                ok, sc, has_p = _card_signal_score(item, base_url)
                if ok and has_p and sc >= 5.0:
                    seen_el_ids.add(id(item))
                    expanded.append(item)

        # Recover standalone featured/hero product blocks not yet represented by valid product cards
        covered_urls = set()
        for card in expanded:
            card_txt = normalize_inline_text(card.get_text(" ", strip=True))
            if classify_candidate_non_product(text=card_txt):
                continue
            for a in card.find_all("a", href=True):
                cu = canonicalize_url(str(a.get("href")), base_url)
                if cu:
                    covered_urls.add(cu)

        featured_link_re = re.compile(
            r"/(?:shop/(?:phones|tablets|laptops|smart-watches)/[^/?#]+|broadband/(?:home-broadband|mobile-broadband)/?$|product/[^/?#]+|dp/[A-Z0-9]+)",
            re.I,
        )
        for a in soup.find_all("a", href=True):
            abs_u = _resolve_abs_url(a.get("href"), base_url)
            if not abs_u or not featured_link_re.search(abs_u):
                continue
            canon_u = canonicalize_url(abs_u, base_url)
            if not canon_u or canon_u in covered_urls:
                continue
            curr = a.parent
            best_block = None
            for _ in range(10):
                if curr is None or curr.name in {"body", "main", "html"}:
                    break
                if _is_ancestor_of_any(curr, expanded):
                    break
                txt = normalize_inline_text(curr.get_text(" ", strip=True))
                if classify_candidate_non_product(text=txt):
                    best_block = None
                    break
                if 20 <= len(txt) <= 1500 and (PRICE_TEXT_RE.search(txt) or curr.find("img") is not None):
                    best_block = curr
                curr = curr.parent
            if best_block is not None and id(best_block) not in seen_el_ids:
                seen_el_ids.add(id(best_block))
                covered_urls.add(canon_u)
                expanded.append(best_block)

    return expanded


def _choose_primary_url(links: list[dict[str, str]], title_candidates: list[str]) -> str | None:
    if not links:
        return None

    def link_rank(item: dict[str, str]) -> tuple[int, int]:
        href = item["href"]
        text = item["text"]
        href_lower = href.lower()
        score = 0
        if "deal-group" in href_lower or "is_promoted=true" in href_lower:
            score -= 5
        if NON_PRODUCT_LINK_RE.search(href_lower):
            score -= 8
        if any(p in href_lower for p in ("/shop/phones/", "/shop/tablets/", "/shop/laptops/", "/product", "/dp/", "/p/")):
            score += 6
        elif any(p in href_lower for p in ("/shop/", "/item", "/book", "/catalogue", "-deals", "/broadband/")):
            score += 4
        if item.get("in_heading"):
            score += 4
        if text and not re.match(r"^(?:see all|view|buy|more|details|read more|get this.*)$", text, re.I):
            score += 2
        if title_candidates:
            for t in title_candidates[:3]:
                t_low = t.lower()
                if text and (text.lower() in t_low or t_low in text.lower()):
                    score += 3
                    break
                slug_tokens = [tok for tok in re.findall(r"[a-z0-9]+", t_low) if len(tok) >= 2]
                if slug_tokens and sum(1 for tok in slug_tokens if tok in href_lower) >= min(2, len(slug_tokens)):
                    score += 4
                    break
        return (score, len(text))

    best = max(links, key=link_rank)
    return best["href"]


def _extract_variants_and_offers(raw_text: str, card: Tag) -> dict[str, Any]:
    storage_variants = list(dict.fromkeys(m.group(1).upper().replace(" ", "") for m in STORAGE_VARIANT_RE.finditer(raw_text)))
    lowered = raw_text.lower()
    colour_variants: list[str] = []
    for c in sorted(COLOUR_WORDS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(c)}\b", lowered):
            # Avoid duplicating e.g. 'Blue' if 'Mist Blue' already found
            if not any(c in existing.lower() for existing in colour_variants):
                colour_variants.append(c.title())

    for swatch in card.select('[aria-label], [title], [data-color], [data-colour]'):
        for attr in ("data-color", "data-colour", "aria-label"):
            val = swatch.get(attr)
            if val and val.strip().lower() in COLOUR_WORDS:
                norm = val.strip().title()
                if norm not in colour_variants:
                    colour_variants.append(norm)

    related_offers = list(dict.fromkeys(normalize_inline_text(m.group(0)) for m in OFFER_TEXT_RE.finditer(raw_text)))[:5]
    monthly_payments = []
    for m in MONTHLY_PRICE_RE.finditer(raw_text):
        prefix = raw_text[max(0, m.start() - 45):m.start()].lower()
        if any(skip in prefix for skip in ("increase by", "price rises", "rise by", "increasing to")):
            continue
        val = normalize_inline_text(m.group(0))
        if val and val not in monthly_payments:
            monthly_payments.append(val)
        if len(monthly_payments) >= 4:
            break
    upfront_payments = list(dict.fromkeys(normalize_inline_text(m.group(0)) for m in UPFRONT_PRICE_RE.finditer(raw_text)))[:3]

    return {
        "storage_variants": storage_variants[:8],
        "colour_variants": colour_variants[:10],
        "related_offers": related_offers,
        "monthly_payments": monthly_payments,
        "upfront_payments": upfront_payments,
    }


def _extract_card_semantics(card: Tag, index: int, base_url: str, json_ld_by_url: dict[str, dict]) -> dict[str, Any]:
    """Convert one product card Tag into a compact semantic dictionary plus raw_html for auditing."""
    raw_text = normalize_inline_text(card.get_text(" ", strip=True))

    links: list[dict[str, Any]] = []
    seen_hrefs: set[str] = set()
    for a in card.find_all("a", href=True):
        href = _resolve_abs_url(a.get("href"), base_url)
        if not href:
            continue
        link_text = normalize_inline_text(a.get_text(" ", strip=True))
        in_heading = a.find_parent(["h1", "h2", "h3", "h4"]) is not None
        if href not in seen_hrefs:
            seen_hrefs.add(href)
            links.append({"text": link_text, "href": href, "in_heading": in_heading})

    title_candidates: list[str] = []
    for h in card.find_all(["h1", "h2", "h3", "h4"]):
        t = normalize_inline_text(h.get_text(" ", strip=True))
        if t and t not in title_candidates:
            title_candidates.append(t)
        a_in_h = h.find("a", title=True)
        if a_in_h and a_in_h.get("title"):
            at = normalize_inline_text(a_in_h.get("title"))
            if at and at not in title_candidates:
                title_candidates.append(at)

    for a in card.find_all("a", href=True):
        if a.get("title"):
            at = normalize_inline_text(a.get("title"))
            if at and at not in title_candidates:
                title_candidates.append(at)

    images: list[dict[str, str]] = []
    seen_imgs: set[str] = set()
    for img in card.find_all("img"):
        src = _extract_img_url(img, base_url)
        alt = normalize_inline_text(img.get("alt") or "")
        if alt and not title_candidates:
            cleaned_alt = re.sub(r"\s+(?:front and back|image|photo|thumbnail)\s*$", "", alt, flags=re.I).strip()
            if cleaned_alt:
                title_candidates.append(cleaned_alt)
        if src and src not in seen_imgs:
            seen_imgs.add(src)
            images.append({"src": src, "alt": alt})

    price_texts: list[str] = []
    for m in PRICE_TEXT_RE.finditer(raw_text):
        p = normalize_inline_text(m.group(0))
        if p and p not in price_texts:
            price_texts.append(p)

    availability_texts: list[str] = []
    for m in AVAILABILITY_RE.finditer(raw_text):
        av = normalize_inline_text(m.group(0))
        if av and av not in availability_texts:
            availability_texts.append(av)

    rating_texts: list[str] = []
    for m in RATING_TEXT_RE.finditer(raw_text):
        rt = normalize_inline_text(m.group(0))
        if rt and rt not in rating_texts:
            rating_texts.append(rt)
    for el in card.find_all(True):
        cls_list = el.get("class") or []
        if isinstance(cls_list, list) and any("star" in c.lower() or "rating" in c.lower() for c in cls_list):
            for c in cls_list:
                if c.lower() in STAR_WORD_MAP:
                    mapped = f"{c} ({STAR_WORD_MAP[c.lower()]})"
                    if mapped not in rating_texts:
                        rating_texts.append(mapped)
        aria = el.get("aria-label")
        if aria and ("star" in aria.lower() or "rating" in aria.lower() or "out of" in aria.lower()):
            ar = normalize_inline_text(aria)
            if ar and ar not in rating_texts:
                rating_texts.append(ar)

    primary_url = _choose_primary_url(links, title_candidates)
    canon_url = canonicalize_url(primary_url or "", base_url)
    matched_json_ld = json_ld_by_url.get(canon_url) if canon_url else None

    if matched_json_ld and matched_json_ld.get("title"):
        ld_title = matched_json_ld["title"]
        ld_brand = matched_json_ld.get("brand")
        full_ld = f"{ld_brand} {ld_title}".strip() if ld_brand and ld_brand.lower() not in ld_title.lower() else ld_title
        if full_ld not in title_candidates:
            title_candidates.insert(0, full_ld)

    is_promoted = bool(
        PROMOTED_RE.search(raw_text[:80])
        or (primary_url and ("is_promoted=true" in primary_url.lower() or "deal-group" in primary_url.lower()))
    )

    extras = _extract_variants_and_offers(raw_text, card)
    non_product_reason = classify_candidate_non_product(
        url=primary_url,
        title=title_candidates[0] if title_candidates else None,
        text=raw_text,
    )

    raw_html_snippet = str(card)
    if len(raw_html_snippet) > 3000:
        raw_html_snippet = raw_html_snippet[:3000] + "..."

    semantic_summary_parts = []
    if title_candidates:
        semantic_summary_parts.append(f"Title candidates: {'; '.join(title_candidates[:3])}")
    if primary_url:
        semantic_summary_parts.append(f"URL: {primary_url}")
    if price_texts:
        semantic_summary_parts.append(f"Prices: {'; '.join(price_texts[:4])}")
    if extras["monthly_payments"]:
        semantic_summary_parts.append(f"Monthly: {'; '.join(extras['monthly_payments'][:2])}")
    if extras["upfront_payments"]:
        semantic_summary_parts.append(f"Upfront: {'; '.join(extras['upfront_payments'][:2])}")
    if availability_texts:
        semantic_summary_parts.append(f"Availability: {'; '.join(availability_texts[:2])}")
    if rating_texts:
        semantic_summary_parts.append(f"Rating: {'; '.join(rating_texts[:2])}")
    if images:
        semantic_summary_parts.append(f"Images: {', '.join(img['src'] for img in images[:2])}")
    semantic_summary_parts.append(f"Text: {raw_text[:450]}")

    semantic_text = " | ".join(semantic_summary_parts)
    fingerprint_src = json.dumps(
        {
            "u": canon_url,
            "t": title_candidates[:2],
            "p": price_texts[:3],
            "txt": raw_text[:300],
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    card_hash = hashlib.sha256(fingerprint_src.encode("utf-8")).hexdigest()[:16]

    return {
        "card_index": index,
        "card_hash": card_hash,
        "is_promoted": is_promoted,
        "non_product_reason": non_product_reason,
        "title_candidates": title_candidates,
        "primary_url": primary_url,
        "canonical_url": canon_url,
        "links": [{"text": l["text"], "href": l["href"]} for l in links[:5]],
        "images": images[:4],
        "price_texts": price_texts,
        "monthly_payments": extras["monthly_payments"],
        "upfront_payments": extras["upfront_payments"],
        "storage_variants": extras["storage_variants"],
        "colour_variants": extras["colour_variants"],
        "related_offers": extras["related_offers"],
        "availability_texts": availability_texts,
        "rating_texts": rating_texts,
        "semantic_text": semantic_text,
        "raw_text": raw_text[:800],
        "raw_html": raw_html_snippet,
        "matched_json_ld": matched_json_ld,
        "source_website": urlsplit(base_url).netloc.lower() if base_url else None,
    }


def extract_semantic_listing(html: str, base_url: str) -> dict[str, Any]:
    """
    Perform site-agnostic semantic extraction on a product listing or storefront page.
    Extracts JSON-LD & page metadata first, removes noise, detects product cards,
    flags obvious non-product items for rejection tracking, and returns compact semantics.
    """
    soup = BeautifulSoup(html, "lxml")
    page_metadata = extract_page_metadata(soup, base_url)
    json_ld = extract_json_ld_data(soup, base_url)

    json_ld_by_url: dict[str, dict] = {}
    for prod in json_ld["products"]:
        cu = canonicalize_url(prod.get("product_url") or "", base_url)
        if cu:
            json_ld_by_url[cu] = prod

    clean_dom_for_semantics(soup)
    card_elements = detect_product_card_elements(soup, json_ld_urls=set(json_ld_by_url.keys()), base_url=base_url)

    cards: list[dict[str, Any]] = []
    seen_card_hashes: set[str] = set()
    for idx, el in enumerate(card_elements):
        card_data = _extract_card_semantics(el, idx, base_url, json_ld_by_url)
        if not card_data["primary_url"] and not card_data["price_texts"] and not card_data["title_candidates"]:
            continue
        if card_data["card_hash"] in seen_card_hashes:
            continue
        seen_card_hashes.add(card_data["card_hash"])
        cards.append(card_data)

    raw_body_text = normalize_inline_text((soup.body or soup).get_text(" ", strip=True))

    return {
        "source_url": base_url,
        "page_metadata": page_metadata,
        "json_ld": json_ld,
        "cards": cards,
        "card_count": len(cards),
        "raw_text_preview": raw_body_text[:4000],
    }


def extract_semantic_detail(html: str, detail_url: str) -> dict[str, Any]:
    """
    Perform site-agnostic semantic extraction on a single product detail page.
    Extracts JSON-LD, page metadata, specs, description, images, prices, monthly/upfront
    payments, variants, offers, availability, ratings, and non-product signals.
    """
    soup = BeautifulSoup(html, "lxml")
    page_metadata = extract_page_metadata(soup, detail_url)
    json_ld = extract_json_ld_data(soup, detail_url)

    clean_dom_for_semantics(soup)

    main_container = (
        soup.find("main")
        or soup.find(attrs={"role": "main"})
        or soup.find("article")
        or soup.find(id=re.compile(r"content|main|product", re.I))
        or soup.body
        or soup
    )

    specs: dict[str, str] = {}
    for table in main_container.find_all("table")[:4]:
        for tr in table.find_all("tr")[:30]:
            cells = tr.find_all(["th", "td"])
            if len(cells) >= 2:
                k = normalize_inline_text(cells[0].get_text(" ", strip=True)).rstrip(":")
                v = normalize_inline_text(cells[1].get_text(" ", strip=True))
                if k and v and len(k) <= 80 and len(v) <= 300:
                    specs[k] = v

    for dl in main_container.find_all("dl")[:4]:
        dts = dl.find_all("dt")
        dds = dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            k = normalize_inline_text(dt.get_text(" ", strip=True)).rstrip(":")
            v = normalize_inline_text(dd.get_text(" ", strip=True))
            if k and v and len(k) <= 80 and len(v) <= 300:
                specs[k] = v

    desc_candidates: list[str] = []
    for p in main_container.find_all("p"):
        txt = normalize_inline_text(p.get_text(" ", strip=True))
        if len(txt) >= 40 and not PRICE_TEXT_RE.fullmatch(txt):
            if txt not in desc_candidates:
                desc_candidates.append(txt)
        if len(desc_candidates) >= 5:
            break
    description_text = " ".join(desc_candidates)[:1500] if desc_candidates else page_metadata.get("meta_description")

    images: list[str] = []
    if page_metadata.get("og_image"):
        images.append(page_metadata["og_image"])
    for img in main_container.find_all("img")[:12]:
        src = _extract_img_url(img, detail_url)
        if src and src not in images and not re.search(r"logo|icon|sprite|avatar|flag", src, re.I):
            images.append(src)

    raw_text = normalize_inline_text(main_container.get_text(" ", strip=True))
    price_texts = list(dict.fromkeys(normalize_inline_text(m.group(0)) for m in PRICE_TEXT_RE.finditer(raw_text[:3500])))[:8]
    availability_texts = list(dict.fromkeys(normalize_inline_text(m.group(0)) for m in AVAILABILITY_RE.finditer(raw_text[:3500])))[:4]
    rating_texts = list(dict.fromkeys(normalize_inline_text(m.group(0)) for m in RATING_TEXT_RE.finditer(raw_text[:3500])))[:4]
    reviews_match = REVIEWS_COUNT_RE.search(raw_text[:3500])
    reviews_count = reviews_match.group(1) if reviews_match else None

    for el in main_container.find_all(True):
        cls_list = el.get("class") or []
        if isinstance(cls_list, list) and any("star" in c.lower() or "rating" in c.lower() for c in cls_list):
            for c in cls_list:
                if c.lower() in STAR_WORD_MAP:
                    mapped = f"{c} ({STAR_WORD_MAP[c.lower()]})"
                    if mapped not in rating_texts:
                        rating_texts.append(mapped)

    extras = _extract_variants_and_offers(raw_text[:3500], main_container)
    primary_ld = json_ld["products"][0] if json_ld["products"] else None
    if primary_ld and primary_ld.get("reviews_count") and not reviews_count:
        reviews_count = primary_ld["reviews_count"]

    non_product_reason = None
    if not primary_ld:
        non_product_reason = classify_candidate_non_product(
            url=detail_url,
            title=page_metadata.get("h1") or page_metadata.get("page_title"),
            text=None,
            check_body_text=False,
        )

    summary_parts = [
        f"URL: {detail_url}",
        f"Title: {page_metadata.get('h1') or page_metadata.get('page_title') or ''}",
    ]
    if price_texts:
        summary_parts.append(f"Prices: {'; '.join(price_texts[:4])}")
    if extras["monthly_payments"]:
        summary_parts.append(f"Monthly: {'; '.join(extras['monthly_payments'][:3])}")
    if extras["upfront_payments"]:
        summary_parts.append(f"Upfront: {'; '.join(extras['upfront_payments'][:2])}")
    if availability_texts:
        summary_parts.append(f"Availability: {'; '.join(availability_texts[:2])}")
    if rating_texts:
        summary_parts.append(f"Rating: {'; '.join(rating_texts[:2])}")
    if extras["storage_variants"]:
        summary_parts.append(f"Storage: {', '.join(extras['storage_variants'][:5])}")
    if extras["colour_variants"]:
        summary_parts.append(f"Colours: {', '.join(extras['colour_variants'][:6])}")
    if extras["related_offers"]:
        summary_parts.append(f"Offers: {'; '.join(extras['related_offers'][:3])}")
    if description_text:
        summary_parts.append(f"Description: {description_text[:600]}")
    if specs:
        spec_str = "; ".join(f"{k}: {v}" for k, v in list(specs.items())[:12])
        summary_parts.append(f"Specifications: {spec_str}")
    if primary_ld:
        ld_compact = {k: v for k, v in primary_ld.items() if k != "raw_json_ld" and v not in (None, "", [])}
        summary_parts.append(f"JSON-LD: {json.dumps(ld_compact, ensure_ascii=False)[:500]}")

    semantic_text = " | ".join(summary_parts)
    detail_hash = hashlib.sha256(semantic_text.encode("utf-8")).hexdigest()[:16]

    return {
        "source_url": detail_url,
        "canonical_url": canonicalize_url(detail_url, detail_url),
        "detail_hash": detail_hash,
        "non_product_reason": non_product_reason,
        "page_metadata": page_metadata,
        "json_ld_products": json_ld["products"],
        "primary_json_ld": primary_ld,
        "h1": page_metadata.get("h1"),
        "title": page_metadata.get("h1") or page_metadata.get("page_title"),
        "description": description_text,
        "specifications": specs,
        "image_urls": images[:6],
        "price_texts": price_texts,
        "monthly_payments": extras["monthly_payments"],
        "upfront_payments": extras["upfront_payments"],
        "storage_variants": extras["storage_variants"],
        "colour_variants": extras["colour_variants"],
        "related_offers": extras["related_offers"],
        "availability_texts": availability_texts,
        "rating_texts": rating_texts,
        "reviews_count": reviews_count,
        "source_website": urlsplit(detail_url).netloc.lower() if detail_url else None,
        "semantic_text": semantic_text,
        "raw_text": raw_text[:3000],
        "raw_html_preview": str(main_container)[:4000],
    }

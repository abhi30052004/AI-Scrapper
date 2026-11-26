import hashlib
import json
import logging
import os
import re
import threading
import time
from typing import Any
from urllib.parse import urlsplit

from groq import Groq
from pydantic import BaseModel, Field, ValidationError

from app.config import settings
from app.services.ai_client import (
    BACKEND_DIR,
    _execute_groq_call,
    _extract_json_dict,
    _is_rate_or_size_error,
    get_groq_model,
)

logger = logging.getLogger(__name__)

_CACHE_LOCK = threading.Lock()
_MEMORY_CACHE: dict[str, dict[str, Any]] | None = None
CACHE_FILE = BACKEND_DIR / "data" / "llm_cache.json"
CACHE_SCHEMA_VERSION = "v2"


class ExtractedProductSchema(BaseModel):
    card_index: int | None = None
    is_product: bool = True
    product_classification: str = "other_product"
    rejection_reason: str | None = None
    confidence_score: float = 0.0
    title: str | None = None
    brand: str | None = None
    category: str | None = None
    product_url: str | None = None
    image_urls: list[str] = Field(default_factory=list)
    price: str | None = None
    numeric_price: float | None = None
    currency: str | None = None
    monthly_payment: str | None = None
    monthly_payment_numeric: float | None = None
    upfront_payment: str | None = None
    upfront_payment_numeric: float | None = None
    description: str | None = None
    specifications: dict[str, Any] = Field(default_factory=dict)
    availability: str | None = None
    rating: str | None = None
    reviews_count: str | None = None
    storage_variants: list[str] = Field(default_factory=list)
    colour_variants: list[str] = Field(default_factory=list)
    related_offers: list[str] = Field(default_factory=list)
    source_website: str | None = None


class BatchProductExtractionSchema(BaseModel):
    products: list[ExtractedProductSchema] = Field(default_factory=list)


class DetailProductSchema(BaseModel):
    source_url: str | None = None
    is_product: bool = True
    product_classification: str = "other_product"
    rejection_reason: str | None = None
    confidence_score: float = 0.0
    title: str | None = None
    brand: str | None = None
    category: str | None = None
    product_url: str | None = None
    image_urls: list[str] = Field(default_factory=list)
    price: str | None = None
    numeric_price: float | None = None
    currency: str | None = None
    monthly_payment: str | None = None
    monthly_payment_numeric: float | None = None
    upfront_payment: str | None = None
    upfront_payment_numeric: float | None = None
    description: str | None = None
    specifications: dict[str, Any] = Field(default_factory=dict)
    availability: str | None = None
    rating: str | None = None
    reviews_count: str | None = None
    storage_variants: list[str] = Field(default_factory=list)
    colour_variants: list[str] = Field(default_factory=list)
    related_offers: list[str] = Field(default_factory=list)
    source_website: str | None = None


class DetailBatchExtractionSchema(BaseModel):
    products: list[DetailProductSchema] = Field(default_factory=list)


def _load_cache() -> dict[str, dict[str, Any]]:
    global _MEMORY_CACHE
    if _MEMORY_CACHE is not None:
        return _MEMORY_CACHE
    if CACHE_FILE.is_file():
        try:
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _MEMORY_CACHE = data
                return _MEMORY_CACHE
        except Exception:
            pass
    _MEMORY_CACHE = {}
    return _MEMORY_CACHE


def _save_cache() -> None:
    if not settings.llm_cache_enabled:
        return
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        cache = _load_cache()
        if len(cache) > 5000:
            keys = list(cache.keys())[-3500:]
            trimmed = {k: cache[k] for k in keys}
            cache.clear()
            cache.update(trimmed)
        CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        logger.debug("Could not persist LLM cache: %s", exc)


def _make_cache_key(kind: str, model: str, payload_hash: str) -> str:
    raw = f"{CACHE_SCHEMA_VERSION}|{kind}|{model}|{payload_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _get_cached_item(kind: str, model: str, payload_hash: str) -> dict[str, Any] | None:
    if not settings.llm_cache_enabled or not payload_hash:
        return None
    key = _make_cache_key(kind, model, payload_hash)
    with _CACHE_LOCK:
        cache = _load_cache()
        item = cache.get(key)
        return dict(item) if isinstance(item, dict) else None


def _set_cached_item(kind: str, model: str, payload_hash: str, value: dict[str, Any]) -> None:
    if not settings.llm_cache_enabled or not payload_hash:
        return
    key = _make_cache_key(kind, model, payload_hash)
    with _CACHE_LOCK:
        cache = _load_cache()
        cache[key] = dict(value)
        _save_cache()


def _parse_retry_after_seconds(exc: Exception) -> float:
    msg = str(exc)
    match = re.search(r"try again in\s+(\d+(?:\.\d+)?)\s*(ms|s)", msg, re.IGNORECASE)
    if match:
        val = float(match.group(1))
        unit = match.group(2).lower()
        return max(0.5, min(val / 1000.0 if unit == "ms" else val, 20.0))
    return 2.0


def _is_payload_too_large_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "413" in msg or "request too large" in msg or "context_length_exceeded" in msg


def _compact_card_for_llm(card: dict[str, Any]) -> dict[str, Any]:
    """Build a minimal token-efficient semantic representation of a product card."""
    compact: dict[str, Any] = {
        "card_index": card["card_index"],
    }
    if card.get("title_candidates"):
        compact["title_candidates"] = card["title_candidates"][:2]
    if card.get("primary_url"):
        compact["url"] = card["primary_url"]
    if card.get("price_texts"):
        compact["price_texts"] = card["price_texts"][:3]
    if card.get("monthly_payments"):
        compact["monthly_payments"] = card["monthly_payments"][:2]
    if card.get("upfront_payments"):
        compact["upfront_payments"] = card["upfront_payments"][:2]
    if card.get("storage_variants"):
        compact["storage_variants"] = card["storage_variants"][:4]
    if card.get("colour_variants"):
        compact["colour_variants"] = card["colour_variants"][:5]
    if card.get("related_offers"):
        compact["related_offers"] = card["related_offers"][:3]
    if card.get("availability_texts"):
        compact["availability_texts"] = card["availability_texts"][:2]
    if card.get("rating_texts"):
        compact["rating_texts"] = card["rating_texts"][:2]
    if card.get("images"):
        compact["images"] = [img.get("src") for img in card["images"][:2] if img.get("src")]
    if card.get("raw_text"):
        compact["text"] = card["raw_text"][:340]
    if card.get("matched_json_ld"):
        ld = card["matched_json_ld"]
        compact["json_ld"] = {
            k: v
            for k, v in ld.items()
            if k in {"title", "brand", "category", "price", "currency", "availability", "rating"}
            and v not in (None, "", [])
        }
    return compact


def _compact_detail_for_llm(detail: dict[str, Any]) -> dict[str, Any]:
    """Build a compact token-efficient semantic representation of a product detail page."""
    compact: dict[str, Any] = {
        "source_url": detail["source_url"],
    }
    if detail.get("title"):
        compact["title"] = detail["title"][:200]
    if detail.get("price_texts"):
        compact["price_texts"] = detail["price_texts"][:5]
    if detail.get("monthly_payments"):
        compact["monthly_payments"] = detail["monthly_payments"][:3]
    if detail.get("upfront_payments"):
        compact["upfront_payments"] = detail["upfront_payments"][:2]
    if detail.get("storage_variants"):
        compact["storage_variants"] = detail["storage_variants"][:5]
    if detail.get("colour_variants"):
        compact["colour_variants"] = detail["colour_variants"][:6]
    if detail.get("related_offers"):
        compact["related_offers"] = detail["related_offers"][:4]
    if detail.get("availability_texts"):
        compact["availability_texts"] = detail["availability_texts"][:2]
    if detail.get("rating_texts"):
        compact["rating_texts"] = detail["rating_texts"][:2]
    if detail.get("reviews_count"):
        compact["reviews_count"] = detail["reviews_count"]
    if detail.get("description"):
        compact["description"] = detail["description"][:450]
    if detail.get("specifications"):
        compact["specifications"] = dict(list(detail["specifications"].items())[:10])
    if detail.get("image_urls"):
        compact["image_urls"] = detail["image_urls"][:3]
    if detail.get("primary_json_ld"):
        ld = detail["primary_json_ld"]
        compact["json_ld"] = {
            k: v
            for k, v in ld.items()
            if k != "raw_json_ld" and v not in (None, "", [])
        }
    return compact


def _pack_batches(items: list[dict[str, Any]], max_items: int, max_chars: int) -> list[list[dict[str, Any]]]:
    """Pack compact semantic payloads into token-safe batches."""
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0

    for item in items:
        item_len = len(json.dumps(item, ensure_ascii=False))
        if current and (len(current) >= max_items or current_chars + item_len > max_chars):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(item)
        current_chars += item_len

    if current:
        batches.append(current)
    return batches


def _get_groq_client() -> tuple[Groq, str]:
    api_key = os.getenv("GROQ_API_KEY") or settings.groq_api_key
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is missing from backend/.env")
    return Groq(api_key=api_key), get_groq_model()


def _call_groq_structured(
    client: Groq,
    model: str,
    system_prompt: str,
    user_prompt: str,
    schema_cls: type[BaseModel],
    max_tokens: int,
    max_retries: int = 5,
) -> tuple[BaseModel, int]:
    """
    Call Groq with constrained JSON mode, Pydantic validation, and retry/backoff
    for invalid JSON responses and transient rate-limit errors.
    """
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    last_exc: Exception | None = None
    validation_failures = 0

    for attempt in range(max_retries):
        try:
            content = _execute_groq_call(
                client=client,
                model=model,
                messages=messages,
                max_tokens=max_tokens,
            )
            parsed = _extract_json_dict(content)
            validated = schema_cls.model_validate(parsed)
            return validated, attempt + 1
        except (ValueError, ValidationError, json.JSONDecodeError) as val_exc:
            last_exc = val_exc
            validation_failures += 1
            logger.warning("LLM structured validation failed (%d/3): %s", validation_failures, val_exc)
            if validation_failures >= 3:
                break
            messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": user_prompt
                    + f"\n\nPREVIOUS OUTPUT WAS INVALID ({str(val_exc)[:200]}). Return ONLY valid JSON matching the exact schema.",
                },
            ]
        except Exception as exc:
            last_exc = exc
            if _is_payload_too_large_error(exc):
                raise
            msg_lower = str(exc).lower()
            # Daily token quota (TPD) cannot be cleared in a few seconds; fail fast to deterministic fallback
            if "tokens per day" in msg_lower or "tpd" in msg_lower:
                logger.warning("Groq daily token limit (TPD) reached; using deterministic fallback for batch.")
                raise
            if _is_rate_or_size_error(exc):
                if attempt < max_retries - 1:
                    wait_s = _parse_retry_after_seconds(exc) + 1.0 + attempt * 0.5
                    if wait_s > 25.0:
                        raise
                    logger.warning("Groq rate limit hit (%s). Sleeping %.1fs before retry...", exc, wait_s)
                    time.sleep(min(wait_s, 20.0))
                    continue
            raise

    if last_exc:
        raise last_exc
    raise RuntimeError("Groq structured extraction failed")


def _build_listing_prompt(source_url: str, compact_cards: list[dict[str, Any]]) -> str:
    categories_str = ", ".join(settings.supported_product_categories)
    domain = urlsplit(source_url).netloc.lower()
    return (
        f"Classify and extract ONLY genuine purchasable products from these semantic cards.\n"
        f"SOURCE URL: {source_url} (website: {domain})\n"
        f"SUPPORTED CATEGORIES: {categories_str}\n\n"
        f"STRICT RULES:\n"
        f"- Extract ONLY genuine purchasable products or plans (phones, tablets, laptops, computers, broadband/internet plans, SIM plans, electronics, accessories, books).\n"
        f"- REJECT (set is_product=false, product_classification='non_product', and fill rejection_reason) any: terms & conditions, privacy/cookie/legal notices, support/help pages, company/about info, network investment/marketing pages, merger announcements, community/forum links, charity/partnership pages, blogs/news, general navigation/discount hubs, or generic basket/login links — EVEN IF they mention a currency amount (e.g. '£11bn investment', '£1.80 price increase').\n"
        f"- Return 1 output object per input card preserving card_index.\n"
        f"- Use null for unavailable fields. NEVER invent or guess missing values.\n"
        f"- Keep raw displayed price in `price`, monthly rate in `monthly_payment`, upfront cost in `upfront_payment`.\n"
        f"- Do NOT treat storage sizes (e.g. '256GB') as price.\n"
        f"- Provide `confidence_score` between 0.0 and 1.0.\n\n"
        f"SEMANTIC CARDS:\n{json.dumps(compact_cards, ensure_ascii=False)}\n\n"
        f"RETURN ONLY JSON in this exact shape:\n"
        f"{{\n"
        f'  "products": [\n'
        f"    {{\n"
        f'      "card_index": 0,\n'
        f'      "is_product": true,\n'
        f'      "product_classification": "smartphone or broadband_plan or non_product",\n'
        f'      "rejection_reason": null,\n'
        f'      "confidence_score": 0.95,\n'
        f'      "title": "string or null",\n'
        f'      "brand": "string or null",\n'
        f'      "category": "string or null",\n'
        f'      "product_url": "https://... or null",\n'
        f'      "image_urls": ["https://..."],\n'
        f'      "price": "raw price string or null",\n'
        f'      "numeric_price": null,\n'
        f'      "currency": "GBP or null",\n'
        f'      "monthly_payment": "string or null",\n'
        f'      "monthly_payment_numeric": null,\n'
        f'      "upfront_payment": "string or null",\n'
        f'      "upfront_payment_numeric": null,\n'
        f'      "description": "string or null",\n'
        f'      "specifications": {{}},\n'
        f'      "availability": "string or null",\n'
        f'      "rating": "string or null",\n'
        f'      "reviews_count": "string or null",\n'
        f'      "storage_variants": [],\n'
        f'      "colour_variants": [],\n'
        f'      "related_offers": [],\n'
        f'      "source_website": "{domain}"\n'
        f"    }}\n"
        f"  ]\n"
        f"}}"
    )


def _build_detail_prompt(compact_details: list[dict[str, Any]]) -> str:
    categories_str = ", ".join(settings.supported_product_categories)
    return (
        f"Classify and extract structured details from these semantic product detail pages.\n"
        f"SUPPORTED CATEGORIES: {categories_str}\n\n"
        f"STRICT RULES:\n"
        f"- Return 1 output object per input item preserving `source_url`.\n"
        f"- If a page is NOT a genuine purchasable product/plan (e.g. terms, merger news, support, community, partnership, general info), set is_product=false and product_classification='non_product'.\n"
        f"- Use null for unavailable fields. NEVER invent information.\n"
        f"- Extract brand, category, raw/numeric price, monthly_payment, upfront_payment, currency, description, specifications, availability, rating, reviews_count, storage_variants, colour_variants, related_offers, and image_urls.\n\n"
        f"SEMANTIC DETAIL PAGES:\n{json.dumps(compact_details, ensure_ascii=False)}\n\n"
        f"RETURN ONLY JSON in this exact shape:\n"
        f"{{\n"
        f'  "products": [\n'
        f"    {{\n"
        f'      "source_url": "https://...",\n'
        f'      "is_product": true,\n'
        f'      "product_classification": "smartphone or broadband_plan or non_product",\n'
        f'      "rejection_reason": null,\n'
        f'      "confidence_score": 0.95,\n'
        f'      "title": "string or null",\n'
        f'      "brand": "string or null",\n'
        f'      "category": "string or null",\n'
        f'      "product_url": "https://... or null",\n'
        f'      "image_urls": ["https://..."],\n'
        f'      "price": "raw price string or null",\n'
        f'      "numeric_price": null,\n'
        f'      "currency": "GBP or null",\n'
        f'      "monthly_payment": "string or null",\n'
        f'      "monthly_payment_numeric": null,\n'
        f'      "upfront_payment": "string or null",\n'
        f'      "upfront_payment_numeric": null,\n'
        f'      "description": "string or null",\n'
        f'      "specifications": {{}},\n'
        f'      "availability": "string or null",\n'
        f'      "rating": "string or null",\n'
        f'      "reviews_count": "string or null",\n'
        f'      "storage_variants": [],\n'
        f'      "colour_variants": [],\n'
        f'      "related_offers": [],\n'
        f'      "source_website": "string or null"\n'
        f"    }}\n"
        f"  ]\n"
        f"}}"
    )


def _deterministic_fallback_from_card(card: dict[str, Any]) -> dict[str, Any]:
    ld = card.get("matched_json_ld") or {}
    title = ld.get("title") or (card["title_candidates"][0] if card.get("title_candidates") else None)
    price = (card["price_texts"][0] if card.get("price_texts") else None) or (
        str(ld.get("price")) if ld.get("price") is not None else None
    )
    images = [img.get("src") for img in card.get("images", []) if img.get("src")]
    if not images and ld.get("image_urls"):
        images = ld["image_urls"]
    is_non_prod = bool(card.get("non_product_reason"))
    return {
        "card_index": card["card_index"],
        "is_product": not is_non_prod,
        "product_classification": "non_product" if is_non_prod else (ld.get("category") or "other_product"),
        "rejection_reason": card.get("non_product_reason"),
        "confidence_score": 0.0 if is_non_prod else 0.7,
        "title": title,
        "brand": ld.get("brand"),
        "category": ld.get("category"),
        "price": price,
        "numeric_price": None,
        "currency": ld.get("currency"),
        "monthly_payment": card["monthly_payments"][0] if card.get("monthly_payments") else None,
        "monthly_payment_numeric": None,
        "upfront_payment": card["upfront_payments"][0] if card.get("upfront_payments") else None,
        "upfront_payment_numeric": None,
        "description": ld.get("description"),
        "specifications": {},
        "image_urls": images,
        "product_url": card.get("primary_url") or ld.get("product_url"),
        "availability": (card["availability_texts"][0] if card.get("availability_texts") else None) or ld.get("availability"),
        "rating": (card["rating_texts"][0] if card.get("rating_texts") else None) or ld.get("rating"),
        "reviews_count": ld.get("reviews_count"),
        "storage_variants": card.get("storage_variants", []),
        "colour_variants": card.get("colour_variants", []),
        "related_offers": card.get("related_offers", []),
        "source_website": card.get("source_website"),
        "extraction_source": "deterministic_fallback",
    }


def _deterministic_fallback_from_detail(detail: dict[str, Any]) -> dict[str, Any]:
    ld = detail.get("primary_json_ld") or {}
    is_non_prod = bool(detail.get("non_product_reason"))
    return {
        "source_url": detail["source_url"],
        "is_product": not is_non_prod,
        "product_classification": "non_product" if is_non_prod else (ld.get("category") or "other_product"),
        "rejection_reason": detail.get("non_product_reason"),
        "confidence_score": 0.0 if is_non_prod else 0.7,
        "title": detail.get("title") or ld.get("title"),
        "brand": ld.get("brand"),
        "category": ld.get("category"),
        "price": (detail["price_texts"][0] if detail.get("price_texts") else None) or (
            str(ld.get("price")) if ld.get("price") is not None else None
        ),
        "numeric_price": None,
        "currency": ld.get("currency"),
        "monthly_payment": detail["monthly_payments"][0] if detail.get("monthly_payments") else None,
        "monthly_payment_numeric": None,
        "upfront_payment": detail["upfront_payments"][0] if detail.get("upfront_payments") else None,
        "upfront_payment_numeric": None,
        "description": detail.get("description") or ld.get("description"),
        "specifications": detail.get("specifications") or {},
        "image_urls": detail.get("image_urls") or ld.get("image_urls") or [],
        "product_url": detail["source_url"],
        "availability": (detail["availability_texts"][0] if detail.get("availability_texts") else None) or ld.get("availability"),
        "rating": (detail["rating_texts"][0] if detail.get("rating_texts") else None) or ld.get("rating"),
        "reviews_count": detail.get("reviews_count") or ld.get("reviews_count"),
        "storage_variants": detail.get("storage_variants", []),
        "colour_variants": detail.get("colour_variants", []),
        "related_offers": detail.get("related_offers", []),
        "source_website": detail.get("source_website"),
        "extraction_source": "deterministic_fallback",
    }


def _enrich_from_card(extracted: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    if not extracted.get("product_url") and card.get("primary_url"):
        extracted["product_url"] = card["primary_url"]
    if not extracted.get("image_urls") and card.get("images"):
        extracted["image_urls"] = [img["src"] for img in card["images"] if img.get("src")]
    if not extracted.get("monthly_payment") and card.get("monthly_payments"):
        extracted["monthly_payment"] = card["monthly_payments"][0]
    if not extracted.get("upfront_payment") and card.get("upfront_payments"):
        extracted["upfront_payment"] = card["upfront_payments"][0]
    if not extracted.get("storage_variants") and card.get("storage_variants"):
        extracted["storage_variants"] = card["storage_variants"]
    if not extracted.get("colour_variants") and card.get("colour_variants"):
        extracted["colour_variants"] = card["colour_variants"]
    if not extracted.get("related_offers") and card.get("related_offers"):
        extracted["related_offers"] = card["related_offers"]
    if not extracted.get("source_website") and card.get("source_website"):
        extracted["source_website"] = card["source_website"]
    if card.get("raw_html"):
        extracted["raw_html_audit"] = card["raw_html"][:1000]
    if card.get("matched_json_ld"):
        extracted["raw_json_ld"] = card["matched_json_ld"].get("raw_json_ld")
    return extracted


def _enrich_from_detail(extracted: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    if not extracted.get("specifications") and detail.get("specifications"):
        extracted["specifications"] = detail["specifications"]
    if not extracted.get("image_urls") and detail.get("image_urls"):
        extracted["image_urls"] = detail["image_urls"]
    if not extracted.get("description") and detail.get("description"):
        extracted["description"] = detail["description"]
    if not extracted.get("monthly_payment") and detail.get("monthly_payments"):
        extracted["monthly_payment"] = detail["monthly_payments"][0]
    if not extracted.get("upfront_payment") and detail.get("upfront_payments"):
        extracted["upfront_payment"] = detail["upfront_payments"][0]
    if not extracted.get("storage_variants") and detail.get("storage_variants"):
        extracted["storage_variants"] = detail["storage_variants"]
    if not extracted.get("colour_variants") and detail.get("colour_variants"):
        extracted["colour_variants"] = detail["colour_variants"]
    if not extracted.get("related_offers") and detail.get("related_offers"):
        extracted["related_offers"] = detail["related_offers"]
    if not extracted.get("reviews_count") and detail.get("reviews_count"):
        extracted["reviews_count"] = detail["reviews_count"]
    if not extracted.get("source_website") and detail.get("source_website"):
        extracted["source_website"] = detail["source_website"]
    return extracted


def _process_card_batch_with_split(
    client: Groq,
    model: str,
    source_url: str,
    batch_cards: list[dict[str, Any]],
    system_prompt: str,
) -> tuple[list[dict[str, Any]], int, list[str]]:
    compact = [_compact_card_for_llm(c) for c in batch_cards]
    prompt = _build_listing_prompt(source_url, compact)
    try:
        parsed, _ = _call_groq_structured(
            client=client,
            model=model,
            system_prompt=system_prompt,
            user_prompt=prompt,
            schema_cls=BatchProductExtractionSchema,
            max_tokens=settings.llm_max_tokens,
        )
        return [p.model_dump() for p in parsed.products], 1, []
    except Exception as exc:
        if _is_payload_too_large_error(exc) and len(batch_cards) > 1:
            mid = len(batch_cards) // 2
            left_res, left_batches, left_errs = _process_card_batch_with_split(
                client, model, source_url, batch_cards[:mid], system_prompt
            )
            right_res, right_batches, right_errs = _process_card_batch_with_split(
                client, model, source_url, batch_cards[mid:], system_prompt
            )
            return left_res + right_res, left_batches + right_batches, left_errs + right_errs
        err_msg = f"LLM listing batch failed ({type(exc).__name__}): {str(exc)[:220]}"
        logger.warning(err_msg)
        return [_deterministic_fallback_from_card(c) for c in batch_cards], 1, [err_msg]


def _process_detail_batch_with_split(
    client: Groq,
    model: str,
    batch_details: list[dict[str, Any]],
    system_prompt: str,
) -> tuple[list[dict[str, Any]], int, list[str]]:
    compact = [_compact_detail_for_llm(d) for d in batch_details]
    prompt = _build_detail_prompt(compact)
    try:
        parsed, _ = _call_groq_structured(
            client=client,
            model=model,
            system_prompt=system_prompt,
            user_prompt=prompt,
            schema_cls=DetailBatchExtractionSchema,
            max_tokens=settings.llm_max_tokens,
        )
        return [p.model_dump() for p in parsed.products], 1, []
    except Exception as exc:
        if _is_payload_too_large_error(exc) and len(batch_details) > 1:
            mid = len(batch_details) // 2
            left_res, left_batches, left_errs = _process_detail_batch_with_split(
                client, model, batch_details[:mid], system_prompt
            )
            right_res, right_batches, right_errs = _process_detail_batch_with_split(
                client, model, batch_details[mid:], system_prompt
            )
            return left_res + right_res, left_batches + right_batches, left_errs + right_errs
        err_msg = f"LLM detail batch failed ({type(exc).__name__}): {str(exc)[:220]}"
        logger.warning(err_msg)
        return [_deterministic_fallback_from_detail(d) for d in batch_details], 1, [err_msg]


def extract_products_with_llm(
    cards: list[dict[str, Any]],
    source_url: str,
) -> dict[str, Any]:
    """
    Classify and convert semantic product cards into structured product dictionaries.
    Pre-rejects deterministic non-products and filters LLM-rejected non-products cleanly.
    """
    if not cards:
        return {
            "records": [],
            "rejected_non_products": [],
            "llm_batches_processed": 0,
            "cache_hits": 0,
            "errors": [],
        }

    model = get_groq_model()
    results_by_index: dict[int, dict[str, Any]] = {}
    rejected_non_products: list[dict[str, Any]] = []
    uncached_cards: list[dict[str, Any]] = []
    cache_hits = 0

    for card in cards:
        # Deterministic pre-rejection saves LLM tokens on obvious non-product links/pages
        if card.get("non_product_reason"):
            rejected_non_products.append({
                "url": card.get("primary_url"),
                "title": card["title_candidates"][0] if card.get("title_candidates") else None,
                "reason": card["non_product_reason"],
                "stage": "deterministic_semantic_filter",
            })
            continue

        cached = _get_cached_item("card", model, card.get("card_hash", ""))
        if cached is not None:
            cached["card_index"] = card["card_index"]
            cached["extraction_source"] = "llm_cache"
            if not cached.get("is_product", True) or cached.get("product_classification") == "non_product":
                rejected_non_products.append({
                    "url": cached.get("product_url") or card.get("primary_url"),
                    "title": cached.get("title") or (card["title_candidates"][0] if card.get("title_candidates") else None),
                    "reason": cached.get("rejection_reason") or "llm_rejected_non_product",
                    "stage": "llm_cache",
                })
            else:
                results_by_index[card["card_index"]] = cached
            cache_hits += 1
        else:
            uncached_cards.append(card)

    batches_processed = 0
    errors: list[str] = []

    if uncached_cards:
        try:
            client, model = _get_groq_client()
        except Exception as exc:
            err_msg = f"Groq client unavailable: {exc}"
            errors.append(err_msg)
            for card in uncached_cards:
                results_by_index[card["card_index"]] = _deterministic_fallback_from_card(card)
            ordered = [results_by_index[c["card_index"]] for c in cards if c["card_index"] in results_by_index]
            return {
                "records": ordered,
                "rejected_non_products": rejected_non_products,
                "llm_batches_processed": 0,
                "cache_hits": cache_hits,
                "errors": errors,
            }

        system_prompt = (
            "You are a strict e-commerce product-only classifier and extractor. "
            "Extract ONLY genuine purchasable products and plans. Reject terms, privacy, "
            "support, company/merger info, network info, community, partnerships, and navigation hubs. "
            "Return strict JSON, use null for missing fields, and never invent facts."
        )

        packed_batches = _pack_batches(
            uncached_cards,
            max_items=max(1, settings.llm_batch_size),
            max_chars=max(1500, settings.llm_max_input_chars),
        )

        for batch in packed_batches:
            batch_products, batch_count, batch_errors = _process_card_batch_with_split(
                client=client,
                model=model,
                source_url=source_url,
                batch_cards=batch,
                system_prompt=system_prompt,
            )
            batches_processed += batch_count
            errors.extend(batch_errors)

            by_idx = {
                item.get("card_index"): item
                for item in batch_products
                if item.get("card_index") is not None
            }

            for pos, card in enumerate(batch):
                idx = card["card_index"]
                extracted = by_idx.get(idx)
                if extracted is None and pos < len(batch_products):
                    extracted = dict(batch_products[pos])
                    extracted["card_index"] = idx
                if extracted is None:
                    extracted = _deterministic_fallback_from_card(card)
                else:
                    extracted.setdefault("extraction_source", "llm")
                    extracted = _enrich_from_card(extracted, card)

                if extracted.get("extraction_source") == "llm":
                    _set_cached_item("card", model, card.get("card_hash", ""), extracted)

                if not extracted.get("is_product", True) or extracted.get("product_classification") == "non_product":
                    rejected_non_products.append({
                        "url": extracted.get("product_url") or card.get("primary_url"),
                        "title": extracted.get("title") or (card["title_candidates"][0] if card.get("title_candidates") else None),
                        "reason": extracted.get("rejection_reason") or "llm_rejected_non_product",
                        "stage": "llm_classifier",
                    })
                else:
                    results_by_index[idx] = extracted

    ordered_records = [results_by_index[c["card_index"]] for c in cards if c["card_index"] in results_by_index]
    return {
        "records": ordered_records,
        "rejected_non_products": rejected_non_products,
        "llm_batches_processed": batches_processed,
        "cache_hits": cache_hits,
        "errors": errors,
    }


def extract_details_with_llm(details: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Classify and extract structured details from product detail page summaries via Groq.
    """
    if not details:
        return {
            "details_by_url": {},
            "rejected_non_products": [],
            "llm_batches_processed": 0,
            "cache_hits": 0,
            "errors": [],
        }

    model = get_groq_model()
    details_by_url: dict[str, dict[str, Any]] = {}
    rejected_non_products: list[dict[str, Any]] = []
    uncached_details: list[dict[str, Any]] = []
    cache_hits = 0

    for detail in details:
        if detail.get("non_product_reason"):
            rejected_non_products.append({
                "url": detail["source_url"],
                "title": detail.get("title"),
                "reason": detail["non_product_reason"],
                "stage": "detail_deterministic_filter",
            })
            continue

        cached = _get_cached_item("detail", model, detail.get("detail_hash", ""))
        if cached is not None:
            cached["extraction_source"] = "llm_cache"
            if not cached.get("is_product", True) or cached.get("product_classification") == "non_product":
                rejected_non_products.append({
                    "url": detail["source_url"],
                    "title": cached.get("title") or detail.get("title"),
                    "reason": cached.get("rejection_reason") or "detail_llm_rejected_non_product",
                    "stage": "detail_llm_cache",
                })
            else:
                details_by_url[detail["source_url"]] = cached
            cache_hits += 1
        else:
            uncached_details.append(detail)

    batches_processed = 0
    errors: list[str] = []

    if uncached_details:
        try:
            client, model = _get_groq_client()
        except Exception as exc:
            err_msg = f"Groq client unavailable for detail extraction: {exc}"
            errors.append(err_msg)
            for detail in uncached_details:
                details_by_url[detail["source_url"]] = _deterministic_fallback_from_detail(detail)
            return {
                "details_by_url": details_by_url,
                "rejected_non_products": rejected_non_products,
                "llm_batches_processed": 0,
                "cache_hits": cache_hits,
                "errors": errors,
            }

        system_prompt = (
            "You are a strict e-commerce product detail-page classifier and extractor. "
            "Convert provided semantic detail summaries into strict JSON. "
            "Reject non-product pages (terms, support, merger, community, partnerships). "
            "Use null for missing fields and never invent data."
        )

        packed_batches = _pack_batches(
            uncached_details,
            max_items=max(1, settings.llm_detail_batch_size),
            max_chars=max(1500, settings.llm_max_input_chars),
        )

        for batch in packed_batches:
            batch_products, batch_count, batch_errors = _process_detail_batch_with_split(
                client=client,
                model=model,
                batch_details=batch,
                system_prompt=system_prompt,
            )
            batches_processed += batch_count
            errors.extend(batch_errors)

            by_url = {
                (item.get("source_url") or item.get("product_url") or "").rstrip("/"): item
                for item in batch_products
                if item.get("source_url") or item.get("product_url")
            }

            for pos, detail in enumerate(batch):
                src = detail["source_url"]
                extracted = by_url.get(src.rstrip("/"))
                if extracted is None and pos < len(batch_products):
                    extracted = dict(batch_products[pos])
                    extracted["source_url"] = src
                if extracted is None:
                    extracted = _deterministic_fallback_from_detail(detail)
                else:
                    extracted.setdefault("extraction_source", "llm")
                    extracted = _enrich_from_detail(extracted, detail)

                if extracted.get("extraction_source") == "llm":
                    _set_cached_item("detail", model, detail.get("detail_hash", ""), extracted)

                if not extracted.get("is_product", True) or extracted.get("product_classification") == "non_product":
                    rejected_non_products.append({
                        "url": src,
                        "title": extracted.get("title") or detail.get("title"),
                        "reason": extracted.get("rejection_reason") or "detail_llm_rejected_non_product",
                        "stage": "detail_llm_classifier",
                    })
                else:
                    details_by_url[src] = extracted

    return {
        "details_by_url": details_by_url,
        "rejected_non_products": rejected_non_products,
        "llm_batches_processed": batches_processed,
        "cache_hits": cache_hits,
        "errors": errors,
    }

import re
from bs4 import BeautifulSoup, Comment

from app.services.semantic_extractor import normalize_inline_text

ALLOWED_ATTRS = {
    "class", "id", "href", "src", "alt", "title",
    "itemprop", "data-testid", "data-component-type",
    "data-asin", "role", "aria-label"
}


def clean_element_attrs(element, keep_classes: int = 4):
    """Strip noisy attributes and trim verbose classes/URLs to save tokens."""
    for tag in [element] + element.find_all(True):
        tag.attrs = {k: v for k, v in tag.attrs.items() if k in ALLOWED_ATTRS}
        if "class" in tag.attrs and isinstance(tag.attrs["class"], list):
            # Strip pure layout/grid utility noise to preserve semantic classes
            filtered = [
                c for c in tag.attrs["class"]
                if not re.match(r"^sg-col|^puis-overflow|^s-widget-spacing|^celwidget|^w-|^h-|^p-|^m-|^css-", c)
            ]
            tag.attrs["class"] = filtered[:keep_classes] if filtered else tag.attrs["class"][:2]
        if "src" in tag.attrs and len(tag.attrs["src"]) > 80:
            tag.attrs["src"] = tag.attrs["src"][:80] + "..."
        if "href" in tag.attrs and len(tag.attrs["href"]) > 80:
            tag.attrs["href"] = tag.attrs["href"][:80] + "..."


def clean_html(html: str, max_chars: int = 18000) -> str:
    """Standard DOM cleaner for storage preview."""
    soup = BeautifulSoup(html, "lxml")
    for node in soup(["script", "style", "svg", "noscript", "iframe", "meta", "link"]):
        node.decompose()
    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()
    for tag in soup.find_all(True):
        tag.attrs = {k: v for k, v in tag.attrs.items() if k in ALLOWED_ATTRS}
        for text_node in tag.find_all(string=True):
            value = normalize_inline_text(str(text_node))
            if len(value) > 200:
                text_node.replace_with(value[:200])
            else:
                text_node.replace_with(value)
    result = str(soup)
    return result[:max_chars]


def extract_representative_html(html: str, target_chars: int = 4000, max_cards: int = 2) -> str:
    """
    Extract a compact, representative HTML snippet of product listings.
    Removes boilerplate, header/footer/nav/ads, and extracts 2-3 clean product cards
    inside their container to stay comfortably within strict LLM token limits (e.g. 8k TPM).
    """
    soup = BeautifulSoup(html, "lxml")

    # 1. Decompose non-content / boilerplate elements
    for tag in soup(["script", "style", "svg", "noscript", "iframe", "meta", "link", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()

    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()

    # Decompose common banners, navbars, ads, popups
    for noise in soup.find_all(attrs={"id": re.compile(r"nav-|navbar|header|footer|flyout|ad-|banner|cookie", re.I)}):
        noise.decompose()
    for noise in soup.find_all(attrs={"class": re.compile(r"nav-|navbar|site-header|site-footer|advertisement|cookie-notice", re.I)}):
        noise.decompose()

    # 2. Identify likely product card clusters
    candidate_selectors = [
        "article:has(a[href$='-deals/'])",
        "article:has(a[href*='deals'])",
        "[data-component-type='s-search-result']",
        "[data-asin]:not([data-asin=''])",
        "article.product_pod",
        ".product-item",
        ".product-card",
        ".product_pod",
        ".s-result-item[data-asin]",
        "li.col-xs-6.col-sm-4.col-md-3.col-lg-3",
        ".product",
        "article",
    ]

    cards = []
    for sel in candidate_selectors:
        found = soup.select(sel)
        if len(found) >= 2:
            cards = found
            break

    # Price pattern fallback across sibling cards
    if not cards:
        price_pattern = re.compile(r"[₹$£€]\s*[\d,]+(?:\.\d+)?|Rs\.?\s*[\d,]+")
        price_nodes = soup.find_all(string=price_pattern)
        parents_with_prices = []
        for p in price_nodes[:20]:
            parent = p.find_parent(["div", "li", "article", "tr", "section"])
            if parent and parent not in parents_with_prices:
                parents_with_prices.append(parent)
        if len(parents_with_prices) >= 2:
            cards = parents_with_prices

    # 3. Build representative container + cards
    if cards:
        sample_cards = cards[:max_cards]
        parent = sample_cards[0].parent
        wrapper_tag = parent.name if parent else "div"
        wrapper = BeautifulSoup(f"<{wrapper_tag}></{wrapper_tag}>", "lxml").find(wrapper_tag)
        if parent:
            clean_element_attrs(parent, keep_classes=3)
            wrapper.attrs = parent.attrs

        for card in sample_cards:
            card_copy = BeautifulSoup(str(card), "lxml").find(card.name)
            if card_copy:
                clean_element_attrs(card_copy, keep_classes=4)
                # Shorten long text
                for t in card_copy.find_all(string=True):
                    val = " ".join(t.split())
                    if len(val) > 60:
                        t.replace_with(val[:60] + "...")
                    else:
                        t.replace_with(val)
                # Remove empty containers
                for tag in list(card_copy.find_all(["div", "span"])):
                    if not tag.text.strip() and not tag.find("img"):
                        tag.decompose()
                wrapper.append(card_copy)

        # Include pagination/load-more element if present
        load_more_candidate = soup.select_one('[data-nerd-props*="load-more"], [class*="load-more"], button[class*="load-more"], li.next, a.next, [rel="next"]')
        if load_more_candidate:
            btn_copy = BeautifulSoup(str(load_more_candidate), "lxml").find(load_more_candidate.name)
            if btn_copy:
                clean_element_attrs(btn_copy, keep_classes=2)
                wrapper.append(btn_copy)

        res = str(wrapper)
        if len(res) > target_chars:
            res = res[:target_chars]
        return res

    # 4. Fallback: cleaned body
    body = soup.find("body") or soup
    clean_element_attrs(body, keep_classes=3)
    return str(body)[:target_chars]
 
from bs4 import BeautifulSoup, Comment

ALLOWED_ATTRS = {"class", "id", "href", "src", "alt", "title", "itemprop", "data-testid", "aria-label"}

def clean_html(html: str, max_chars: int = 18000) -> str:
    soup = BeautifulSoup(html, "lxml")
    for node in soup(["script", "style", "svg", "noscript", "iframe", "meta", "link"]):
        node.decompose()
    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()
    for tag in soup.find_all(True):
        tag.attrs = {k: v for k, v in tag.attrs.items() if k in ALLOWED_ATTRS}
        for text_node in tag.find_all(string=True):
            value = " ".join(str(text_node).split())
            if len(value) > 200:
                text_node.replace_with(value[:200])
            else:
                text_node.replace_with(value)
    result = str(soup)
    return result[:max_chars]

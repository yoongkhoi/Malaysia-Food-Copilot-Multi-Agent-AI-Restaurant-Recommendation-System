"""Live web search through Bing HTML. A blocked or empty page stays a failure."""

import re
from html import unescape
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

_BLOCK = re.compile(r'<li class="b_algo".*?</li>', re.S)
_LINK = re.compile(r'<h2><a[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>', re.S)
_CITE = re.compile(r"<cite[^>]*>(?P<text>.*?)</cite>", re.S)
_CAPTION = re.compile(r'class="b_caption".*?<p[^>]*>(?P<text>.*?)</p>', re.S)
_TAGS = re.compile(r"<[^>]+>")
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def _text(value: str) -> str:
    return unescape(_TAGS.sub(" ", value))


def _source_url(href: str, cite: str) -> str:
    cleaned = " ".join(cite.split())
    if cleaned.startswith("http"):
        return cleaned.replace(" › ", "/").replace("›", "/").replace(" ", "")
    return unescape(href)


_JUNK = re.compile(
    r"airline|airlines|faq|wikipedia|boarding|enrich online|malaysia airlines|"
    r"language|learn korean|korean class|vocabulary|grammar|duolingo|topik|lesson|course|"
    r"dictionary|keyboard|translate|phrasebook|hangul|hiragana|katakana|input method|language school|한语|韩语",
    re.I,
)
_RESTAURANT_SOURCE = re.compile(
    r"restaurant|cafe|café|food|menu|bbq|barbecue|grill|bistro|kitchen|eatery|diner|makan|restoran|kedai|餐厅|美食",
    re.I,
)


def source_is_restaurant(item: dict) -> bool:
    """A keyword in a title is not a verified branch. Language pages are not restaurants."""
    blob = " ".join(str(item.get(key) or "") for key in ("title", "snippet", "url"))
    if _JUNK.search(blob):
        return False
    return bool(_RESTAURANT_SOURCE.search(blob))


_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_SECONDS = 600


def parse_bing_page(page: str, query: str, limit: int = 5) -> dict:
    """Read organic results from Bing HTML. A page with no result blocks is a parse failure."""
    blocks = _BLOCK.findall(page or "")
    if not blocks:
        return {"ok": False, "error": "parse_failed", "results": [], "query": query, "provider": "bing", "parsed_blocks": 0}
    parsed = 0
    results = []
    for block in blocks:
        match = _LINK.search(block)
        if not match:
            continue
        parsed += 1
        cite = _CITE.search(block)
        caption = _CAPTION.search(block)
        title = " ".join(_text(match.group("title")).split())
        snippet = " ".join(_text(caption.group("text")).split()) if caption else ""
        if not title or not source_is_restaurant({"title": title, "snippet": snippet, "url": match.group("url")}):
            continue
        results.append({
            "title": title,
            "url": _source_url(match.group("url"), _text(cite.group("text")) if cite else ""),
            "snippet": snippet,
        })
        if len(results) >= limit:
            break
    if parsed == 0:
        return {"ok": False, "error": "parse_failed", "results": [], "query": query, "provider": "bing", "parsed_blocks": 0}
    if not results:
        return {"ok": False, "error": "no_results", "results": [], "query": query, "provider": "bing", "parsed_blocks": parsed}
    return {"ok": True, "error": None, "results": results, "query": query, "provider": "bing", "parsed_blocks": parsed}


def search_web(query: str, limit: int = 5, timeout: float = 3.5) -> dict:
    """Return titles, source URLs, and captions actually present in the Bing results page."""
    import time

    cached = _CACHE.get(query)
    if cached and time.time() - cached[0] < _CACHE_SECONDS:
        stored = dict(cached[1])
        stored["cached"] = True
        return stored
    url = "https://www.bing.com/search?q=" + quote_plus(query)
    request = Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "text/html", "Accept-Language": "en"})
    try:
        with urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            page = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return {"ok": False, "error": exc.__class__.__name__, "results": [], "query": query, "provider": "bing"}
    if status != 200:
        return {"ok": False, "error": f"HTTP {status}", "results": [], "query": query, "provider": "bing"}
    payload = parse_bing_page(page, query, limit)
    payload["cached"] = False
    if payload.get("ok"):
        _CACHE[query] = (time.time(), payload)
    return payload

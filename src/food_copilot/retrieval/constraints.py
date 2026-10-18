"""Hard filters. An estimate is not a confirmed price, and a search link is not evidence."""

import re
from typing import Literal

from pydantic import BaseModel, Field

_SEARCH_URL = re.compile(r"google\.[^/\s]+/(search|maps/search)", re.I)
_FLEXIBLE = re.compile(
    r"around|about|approximately|preferably|roughly|左右|大约|大概|最好",
    re.I,
)
_HARD = re.compile(r"must not exceed|strictly|绝对|不超过|cannot exceed|no more than", re.I)
_CHEAP = re.compile(r"murah|cheap|affordable|便宜", re.I)


class QueryConstraints(BaseModel):
    city: str | None = None
    region: str | None = None
    max_budget_myr: float | None = None
    budget_mode: Literal["hard", "flexible", "none"] = "none"
    require_halal_verified: bool = False
    cuisine: str | None = None
    cuisines: list[str] = Field(default_factory=list)
    exclude_cuisines: list[str] = Field(default_factory=list)
    name_contains: str | None = None
    exclude_brands: list[str] = Field(default_factory=list)
    diet: str | None = None
    ambience: str | None = None
    family: bool = False
    text: str = ""


class SearchBuckets(BaseModel):
    matching: list[dict] = Field(default_factory=list)
    price_unknown: list[dict] = Field(default_factory=list)
    city_unverified: list[dict] = Field(default_factory=list)
    halal_unverified: list[dict] = Field(default_factory=list)
    excluded: list[dict] = Field(default_factory=list)
    exclusion_counts: dict[str, int] = Field(default_factory=dict)


_BUDGET = re.compile(r"(?:rm|myr|令吉)\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:rm|myr|令吉)", re.I)
_HALAL = re.compile(r"certified halal|verified halal|must be halal|only halal|halal yang disahkan|必须清真|只要清真", re.I)
_CUISINE_PATTERNS = (
    (re.compile(r"korean|韩国|韩式|韩餐|korea", re.I), "korean"),
    (re.compile(r"jepun|japanese|日本|寿司|拉面|ramen", re.I), "japanese"),
    (re.compile(r"\bbbq\b|barbecue|barbeque|barbeku|烧烤", re.I), "bbq"),
    (re.compile(r"mamak", re.I), "mamak"),
    (re.compile(r"cafe|café|咖啡", re.I), "cafe"),
    (re.compile(r"chinese|中餐|中式", re.I), "chinese"),
    (re.compile(r"indian|印度", re.I), "indian"),
    (re.compile(r"thai|泰国", re.I), "thai"),
    (re.compile(r"italian|意大利", re.I), "italian"),
    (re.compile(r"malay|马来", re.I), "malay"),
    (re.compile(r"seafood|海鲜", re.I), "seafood"),
    (re.compile(r"western|西餐|西式", re.I), "western"),
)
_FAMILY = re.compile(r"family|家庭|keluarga", re.I)
_VEGETARIAN = re.compile(r"vegetarian|vegan|素食|吃素", re.I)
_DATE = re.compile(r"\bdate\b|date night|romantic|cosy|cozy|约会", re.I)
_MOODY = re.compile(r"\bmoody\b|\bmood\b|氛围|气氛", re.I)
_BRANDS = (
    (re.compile(r"\bkfc\b", re.I), "kfc"),
    (re.compile(r"mcdonald", re.I), "mcdonald"),
    (re.compile(r"burger king", re.I), "burger king"),
    (re.compile(r"starbucks", re.I), "starbucks"),
    (re.compile(r"pizza hut", re.I), "pizza hut"),
    (re.compile(r"\bsubway\b", re.I), "subway"),
    (re.compile(r"texas chicken", re.I), "texas chicken"),
)
_OLD_KLANG = re.compile(r"old klang road|jalan klang lama|旧巴生路", re.I)
_KUALA_LUMPUR = re.compile(r"kuala lumpur|吉隆坡", re.I)


def parse_constraints(query: str) -> QueryConstraints:
    budget = None
    match = _BUDGET.search(query)
    if match:
        budget = float(match.group(1) or match.group(2))
    city = "Kulim" if re.search(r"kulim", query, re.I) else None
    if _OLD_KLANG.search(query):
        region = "old_klang_road"
    elif _KUALA_LUMPUR.search(query):
        region = "kuala_lumpur"
    else:
        region = None
    found = []
    for pattern, label in _CUISINE_PATTERNS:
        match = pattern.search(query)
        if match and label not in [item[1] for item in found]:
            found.append((match.start(), label))
    cuisines = [label for _, label in sorted(found)]
    joined = bool(re.search(r"\band\b|以及|和|,", query or "", re.I))
    if len(cuisines) > 1 and not joined and "bbq" in cuisines:
        cuisines = [label for label in cuisines if label != "bbq"]
    cuisine = cuisines[0] if len(cuisines) == 1 else None
    exclude_cuisines = _excluded_cuisines(query)
    cuisines = [label for label in cuisines if label not in exclude_cuisines]
    cuisine = cuisines[0] if len(cuisines) == 1 else None
    exclude_brands = _excluded_brands(query)
    brand = next((label for pattern, label in _BRANDS if pattern.search(query) and label not in exclude_brands), None)
    cheap = bool(_CHEAP.search(query))
    if budget is None and cheap:
        mode = "flexible"
    elif budget is None:
        mode = "none"
    elif _HARD.search(query):
        mode = "hard"
    elif _FLEXIBLE.search(query):
        mode = "flexible"
    else:
        mode = "hard"
    return QueryConstraints(
        city=city,
        region=region,
        max_budget_myr=budget,
        budget_mode=mode,
        require_halal_verified=bool(_HALAL.search(query)),
        cuisine=cuisine,
        cuisines=cuisines,
        exclude_cuisines=exclude_cuisines,
        name_contains=brand,
        exclude_brands=exclude_brands,
        diet="vegetarian" if _VEGETARIAN.search(query) else None,
        ambience="date" if _DATE.search(query) else ("moody" if _MOODY.search(query) else None),
        family=bool(_FAMILY.search(query)),
        text=query.strip(),
    )


def _price_url(record: dict) -> str:
    price = record.get("price_range_myr") or {}
    return str(price.get("source_url") or record.get("price_source_url") or "").strip()


def _search_link(url: str) -> bool:
    return bool(_SEARCH_URL.search(url or ""))


def price_support(record: dict) -> tuple[str, float | None]:
    """Return the price grade the evidence actually supports."""
    price = record.get("price_range_myr") or {}
    status = price.get("status") or "not_verified"
    url = _price_url(record)
    value = price.get("max")
    number = float(value) if value is not None else None
    if status == "verified":
        if number is None or not url or _search_link(url):
            return "unknown", None
        return "verified", number
    if status == "estimated":
        if number is None or not url or _search_link(url):
            return "unknown", None
        return "estimated", number
    if status == "price_range_only":
        return "price_range_only", None
    if status == "demo_example" and number is not None:
        return "demo_example", number
    return "unknown", None


def _price_max(record: dict) -> tuple[str, float | None]:
    return price_support(record)


def _halal_verified(record: dict) -> bool:
    halal = record.get("halal_status") or {}
    return halal.get("status") == "verified" and bool(str(halal.get("source_url") or "").strip())


def _labels_in(text: str, patterns: tuple) -> list[str]:
    found = []
    for pattern, label in patterns:
        if pattern.search(text or "") and label not in found:
            found.append(label)
    return found


def _except_clause(query: str) -> str:
    match = re.search(
        r"(?:other than|else than|besides|except|instead of|rather than|除了|不要|不包括)\s+(.{0,48})",
        query or "",
        re.I,
    )
    return match.group(1) if match else ""


def _excluded_cuisines(query: str) -> list[str]:
    return _labels_in(_except_clause(query), _CUISINE_PATTERNS)


def _excluded_brands(query: str) -> list[str]:
    return _labels_in(_except_clause(query), _BRANDS)


def exclusion_code(record: dict, constraints: QueryConstraints) -> str | None:
    """Return why a record is ineligible, or None when it passes hard constraints."""
    if not _region_ok(record, constraints.region):
        return "region_mismatch"
    city_state = _city_ok(record, constraints.city)
    if city_state == "reject":
        return "city_mismatch"
    if city_state == "unverified":
        return "required_evidence_missing"
    status, price_max = price_support(record)
    if (
        constraints.max_budget_myr is not None
        and price_max is not None
        and status in {"verified", "estimated", "demo_example"}
        and price_max > constraints.max_budget_myr
    ):
        return "price_over_budget"
    if constraints.require_halal_verified and not _halal_verified(record):
        if not (record.get("halal_status") or {}).get("demo_example"):
            return "halal_not_verified"
    wanted = list(constraints.cuisines or [])
    if not wanted and constraints.cuisine:
        wanted = [constraints.cuisine]
    if constraints.exclude_cuisines and any(_cuisine_matches(record, item) for item in constraints.exclude_cuisines):
        return "cuisine_excluded"
    if wanted and not any(_cuisine_matches(record, item) for item in wanted):
        return "cuisine_mismatch"
    folded = (record.get("name") or "").casefold()
    if constraints.exclude_brands and any(brand in folded for brand in constraints.exclude_brands):
        return "brand_excluded"
    if constraints.name_contains and constraints.name_contains not in folded:
        return "name_mismatch"
    if constraints.diet == "vegetarian" and not _cuisine_matches(record, "vegetarian"):
        return "diet_mismatch"
    return None


def _ambience_matches(record: dict, wanted: str) -> bool:
    """Cuisine is not atmosphere evidence. Only a stored ambience value or an explicit description counts."""
    values = [str(item).lower() for item in (record.get("ambience") or [])]
    if wanted in values:
        return True
    description = str(record.get("description") or "")
    if wanted == "moody":
        return bool(re.search(r"\bmoody\b|dim lighting|intimate atmosphere", description, re.I))
    if wanted == "date":
        return bool(re.search(r"\bdate night\b|\bromantic\b|\bcosy\b|\bcozy\b", description, re.I))
    return False


def _cuisine_matches(record: dict, wanted: str) -> bool:
    cuisines = [str(item).lower() for item in record.get("cuisine") or []]
    name = (record.get("name") or "").lower()
    diets = [str(item).lower() for item in record.get("diets") or []]
    if wanted == "cafe":
        return "coffee_shop" in cuisines or "cafe" in name or "café" in name
    if wanted == "malay":
        return any(token in {"malay", "malaysian"} for token in cuisines) or "malay" in name
    if wanted == "bbq":
        return any(token in {"bbq", "barbecue", "barbeque"} for token in cuisines) or any(
            token in name for token in ("bbq", "barbecue", "barbeque")
        )
    return any(wanted in item for item in cuisines) or wanted in name or wanted in diets


def _city_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _city_ok(record: dict, city: str | None) -> str:
    if not city:
        return "ok"
    actual = _city_key(record.get("city") or "")
    wanted = _city_key(city)
    if actual == wanted or actual.startswith(wanted + " "):
        return "ok"
    if not actual and _city_key(record.get("area_query") or "") == wanted:
        return "unverified"
    return "reject"


def _region_ok(record: dict, region: str | None) -> bool:
    if not region:
        return True
    return region in (record.get("regions") or [])


def apply_constraints(records: list[dict], constraints: QueryConstraints) -> SearchBuckets:
    buckets = SearchBuckets()
    counts: dict[str, int] = {}
    for record in records:
        code = exclusion_code(record, constraints)
        if code is None:
            buckets.matching.append(record)
            continue
        counts[code] = counts.get(code, 0) + 1
        if code == "price_unverified":
            buckets.price_unknown.append(record)
        elif code == "required_evidence_missing":
            buckets.city_unverified.append(record)
        elif code == "halal_not_verified":
            buckets.halal_unverified.append(record)
        else:
            buckets.excluded.append(record)
    buckets.exclusion_counts = counts
    return buckets

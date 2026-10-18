"""Deterministic discovery. Hard filters run before and after ranking."""

import logging
import re

from food_copilot.data.repository import LocalRestaurantRepository, get_default_repository
from food_copilot.domain.models import RecommendationResult, RestaurantCandidate, UserRequest
from food_copilot.retrieval.constraints import (
    QueryConstraints,
    SearchBuckets,
    _ambience_matches,
    _cuisine_matches,
    apply_constraints,
    parse_constraints,
    price_support,
)
from food_copilot.config.regions import PROJECT_REGION
from food_copilot.config.settings import feature_flags, web_search_enabled
from food_copilot.retrieval.rankers import BM25Retriever, BaselineRetriever

logger = logging.getLogger("food_copilot.discovery")
_BRANCH = re.compile(r"\bbranch\b|which location|分店|how many|berapa|多少|几家", re.I)


def _usable_name(record: dict) -> bool:
    name = str(record.get("name") or "").strip()
    return bool(name) and name.casefold() not in {"unnamed", "unnamed restaurant"}


def _distinct_names(rows: list[dict], query: str) -> list[dict]:
    if _BRANCH.search(query or ""):
        return rows
    seen: set[str] = set()
    kept = []
    for row in rows:
        key = re.sub(r"[^a-z0-9]+", " ", (row.get("name") or "").casefold()).strip()
        located = row.get("latitude") is not None and row.get("longitude") is not None
        if key and located and key in seen:
            continue
        if key and located:
            seen.add(key)
        kept.append(row)
    return kept

_COUNT_LABELS = {
    "price_unverified": "price is not verified",
    "price_over_budget": "the price evidence is over the budget",
    "price_estimate_not_guaranteed": "an estimate cannot guarantee a hard budget",
    "price_range_not_guaranteed": "a broad price band cannot guarantee a numeric budget",
    "halal_not_verified": "halal is not verified for this branch",
    "region_mismatch": "the region does not match",
    "city_mismatch": "the city does not match",
    "required_evidence_missing": "the city is only supported by the query area",
    "cuisine_mismatch": "the cuisine does not match",
    "diet_mismatch": "the requested diet is not recorded",
    "ambience_mismatch": "the requested occasion is not recorded",
}


def candidate_from_record(record: dict, constraints: QueryConstraints) -> RestaurantCandidate:
    price = record.get("price_range_myr") or {}
    halal = record.get("halal_status") or {}
    urls = []
    for source in record.get("sources") or []:
        url = str(source.get("source_url") or "").strip()
        if url:
            urls.append(url)
    halal_url = str(halal.get("source_url") or "").strip()
    if halal.get("status") == "verified" and halal_url:
        urls.append(halal_url)
    grade, supported_max = price_support(record)
    if grade == "unknown":
        price = {**price, "status": "unknown", "max": None, "min": None}
    reasons = []
    wanted = list(constraints.cuisines or [])
    if not wanted and constraints.cuisine:
        wanted = [constraints.cuisine]
    matched = [item for item in wanted if _cuisine_matches(record, item)]
    if matched:
        reasons.append("Stored cuisine matches " + " and ".join(matched) + ".")
    if constraints.name_contains and constraints.name_contains in (record.get("name") or "").casefold():
        reasons.append(f"The stored name matches {constraints.name_contains}.")
    if constraints.region and constraints.region in (record.get("regions") or []):
        reasons.append("The stored region tag matches the requested area. Coordinates were not used as proof of that area.")
    if constraints.ambience:
        if _ambience_matches(record, constraints.ambience):
            reasons.append("Stored description matches the requested atmosphere. Cuisine was not used as atmosphere evidence.")
        else:
            reasons.append("Ambience has not been verified. Cuisine was not used as atmosphere evidence.")
    if constraints.max_budget_myr is not None and price.get("max") is not None:
        if price.get("status") == "verified":
            reasons.append(
                f"verified price maximum RM{float(price['max']):g} is within RM{constraints.max_budget_myr:g}"
            )
        elif price.get("status") == "estimated" and constraints.budget_mode == "flexible":
            reasons.append(
                f"estimated price maximum RM{float(price['max']):g} is within RM{constraints.max_budget_myr:g}; "
                "this is not a confirmed current price"
            )
    family = record.get("suitable_for_family") or "not_verified"
    return RestaurantCandidate(
        restaurant_id=record["restaurant_id"],
        name=record.get("name"),
        stored_address=record.get("address"),
        location_verified=bool(record.get("location_verified")),
        price_status=price.get("status") or "not_verified",
        price_min_myr=price.get("min"),
        price_max_myr=price.get("max"),
        halal_status=halal.get("status") or "not_verified",
        halal_demo_example=bool(halal.get("demo_example")),
        family_friendly=family if family in {"verified", "not_verified", "unknown"} else "not_verified",
        dataset_origin=record.get("dataset_origin") or "canonical",
        evidence_urls=urls,
        match_reason="; ".join(reasons) or "Matched the requested area and cuisine.",
        map_url=_map_url(record),
        photo_url=record.get("photo_url"),
        cuisine_label=", ".join(record.get("cuisine") or []) or None,
        latitude=record.get("latitude") if isinstance(record.get("latitude"), (int, float)) else None,
        longitude=record.get("longitude") if isinstance(record.get("longitude"), (int, float)) else None,
    )


def _map_url(record: dict) -> str:
    from urllib.parse import quote_plus

    lat = record.get("latitude")
    lon = record.get("longitude")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=18/{lat}/{lon}"
    query = " ".join(
        part for part in (record.get("name"), record.get("address"), "Old Klang Road") if part
    )
    return "https://www.openstreetmap.org/search?query=" + quote_plus(query)


def build_answer(
    constraints: QueryConstraints,
    buckets: SearchBuckets,
    cards: list[RestaurantCandidate],
    clarification: str | None = None,
) -> str:
    if clarification:
        return clarification
    lines = []
    if constraints.region:
        lines.append(
            f"Region filter: {constraints.region}. "
            "A coordinate inside this query area does not verify the street address."
        )
    if constraints.city:
        lines.append(f"City filter: {constraints.city}.")
    if constraints.max_budget_myr is not None and constraints.budget_mode == "flexible":
        lines.append(
            f"Flexible budget: around RM{constraints.max_budget_myr:g}. "
            "A verified price or a labelled estimate can be shown. "
            "An estimate does not guarantee the bill. A broad price band cannot confirm the cap."
        )
    elif constraints.max_budget_myr is not None:
        lines.append(
            f"Budget cap: RM{constraints.max_budget_myr:g}. "
            "A known price above this cap is excluded. "
            "A restaurant without a price is still shown, and its price is omitted."
        )
    elif constraints.budget_mode == "flexible":
        lines.append(
            "A low price was requested without a numeric cap. "
            "No budget number was guessed. Verified prices, labelled estimates, and broad price bands can be shown."
        )
    if constraints.require_halal_verified:
        lines.append(
            "Verified-halal filter: only a branch-specific verified status with a source URL can pass. "
            "not_verified is not a claim that the restaurant is non-halal."
        )
    if constraints.family:
        lines.append(
            "Family-friendly was requested as a preference. "
            "A not_verified value is not treated as verified, and it is not treated as unsuitable."
        )
    if not cards:
        lines.append(
            "No restaurants in the current dataset can be confirmed to satisfy all requested constraints."
        )
        lines.append(
            "This describes the current dataset only. It does not mean no suitable restaurant exists elsewhere."
        )
        if not buckets.exclusion_counts and not buckets.matching:
            lines.append("No candidates were retrieved.")
        else:
            lines.append("Candidates were retrieved and then excluded by hard filters.")
        for code, label in _COUNT_LABELS.items():
            count = buckets.exclusion_counts.get(code, 0)
            if count:
                lines.append(f"Excluded because {label}: {count}.")
    else:
        lines.append(f"{len(cards)} restaurant(s) passed every requested hard constraint.")
        shown = cards[:20]
        for card in shown:
            if card.price_status == "verified" and card.price_max_myr is not None:
                price_text = f"verified price up to RM{card.price_max_myr:g}"
            elif card.price_status == "demo_example" and card.price_max_myr is not None:
                price_text = f"demo example price up to RM{card.price_max_myr:g}; not a verified menu price"
            elif card.price_status == "estimated" and card.price_max_myr is not None:
                price_text = f"estimated price up to RM{card.price_max_myr:g}; not a confirmed current price"
            elif card.price_status == "price_range_only":
                price_text = "broad price band only; exact price unknown"
            else:
                price_text = f"price {card.price_status}"
            address_text = "address verified" if card.location_verified else "street address not verified"
            halal_text = "demo example, not a certification" if card.halal_demo_example else card.halal_status
            lines.append(
                f"- {card.name or card.restaurant_id}: {price_text}; halal {halal_text}; "
                f"{address_text}. {card.match_reason}"
            )
        if len(cards) > len(shown):
            lines.append(f"Showing {len(shown)} of {len(cards)}.")
        if any(card.dataset_origin == "demo" for card in cards):
            lines.append(
                "Demonstration data: these prices and halal labels are examples, not verified restaurant facts."
            )
    return "\n".join(lines)

_CHINESE = re.compile(r"[\u4e00-\u9fff]")
_MALAY = re.compile(
    r"\b(restoran|kedai|makan|makanan|yang|bawah|disahkan|murah|bolehkah|boleh|kamu|saya|nak|ada|tak|jepun|punya|sesuai|satu|tolong|sila|kawasan)\b",
    re.I,
)
_LATIN = re.compile(r"[A-Za-z]")


def detect_language(text: str) -> str:
    has_zh = bool(_CHINESE.search(text))
    has_latin = bool(_LATIN.search(text))
    if has_zh and has_latin:
        return "mixed"
    if has_zh:
        return "zh"
    if _MALAY.search(text):
        return "ms"
    return "en"


def reply_language(query: str, history: list | None = None) -> str:
    """Use the user's language. A short place name keeps the previous turn's language."""
    current = detect_language(query or "")
    if current != "en":
        return current
    words = (query or "").split()
    if len(words) > 4:
        return "en"
    for item in reversed(history or []):
        if item.get("role") != "user":
            continue
        previous = detect_language(str(item.get("content") or ""))
        return previous if previous != "en" else "en"
    return "en"


class DeterministicIntentParser:
    """Parse a restaurant request. A missing area uses Old Klang Road."""

    def parse(self, query: str) -> UserRequest:
        constraints = parse_constraints(query or "")
        if constraints.region is None and constraints.city is None:
            constraints = constraints.model_copy(update={"region": PROJECT_REGION})
        return UserRequest(
            text=query or "",
            constraints=constraints,
            language=detect_language(query or ""),
            unresolved=[],
            clarification=None,
        )


class DiscoveryService:
    def __init__(self, records: list[dict] | None = None, ranker=None, repository=None):
        if repository is not None:
            self.repository = repository
        elif records is not None:
            self.repository = LocalRestaurantRepository(records=records)
        else:
            self.repository = get_default_repository()
        self.ranker = ranker or (BM25Retriever() if feature_flags()["ENABLE_BM25"] else BaselineRetriever())

    def from_text(self, query: str, parser=None) -> dict:
        request = (parser or DeterministicIntentParser()).parse(query)
        if request.clarification:
            empty = apply_constraints([], request.constraints)
            answer = build_answer(request.constraints, empty, [], clarification=request.clarification)
            return self._payload(request, [], empty, answer, needs_clarification=True)
        return self.from_constraints(request.constraints, query_text=request.text, request=request)

    def from_constraints(
        self,
        constraints: QueryConstraints,
        query_text: str = "",
        request: UserRequest | None = None,
        include_web: bool = True,
        exclude_names: list[str] | None = None,
        exclude_ids: list[str] | None = None,
    ) -> dict:
        if request is None:
            request = UserRequest(text=query_text, constraints=constraints, language=detect_language(query_text))
        candidates = self.repository.list_restaurants()
        filtered = apply_constraints(candidates, constraints)
        ranked = self.ranker.rank(list(filtered.matching), query_text or constraints.text)
        checked = apply_constraints(ranked, constraints)
        if constraints.name_contains or _BRANCH.search(query_text or constraints.text):
            distinct = list(checked.matching)
        else:
            distinct = _distinct_names(checked.matching, query_text or constraints.text)
        blocked_ids = {item for item in (exclude_ids or []) if item}
        blocked = {name.casefold() for name in (exclude_names or []) if name}
        if blocked_ids:
            distinct = [row for row in distinct if row.get("restaurant_id") not in blocked_ids]
        if blocked and not constraints.name_contains:
            distinct = [row for row in distinct if (row.get("name") or "").casefold() not in blocked]
        atmosphere = None
        if constraints.ambience:
            evidenced = [row for row in distinct if _ambience_matches(row, constraints.ambience)]
            if evidenced:
                distinct = evidenced
                atmosphere = "supported"
            else:
                named = [row for row in distinct if _usable_name(row)]
                distinct = named[:5]
                atmosphere = "unverified"
        cuisines = list(constraints.cuisines or [])
        cuisine_counts = {label: sum(1 for row in distinct if _cuisine_matches(row, label)) for label in cuisines}
        if len(cuisines) > 1:
            shown = []
            seen = set()
            for label in cuisines:
                group = [row for row in distinct if _cuisine_matches(row, label)]
                for row in group[:4]:
                    if row.get("restaurant_id") not in seen:
                        shown.append(row)
                        seen.add(row.get("restaurant_id"))
        else:
            limit = 20 if constraints.name_contains else 8
            shown = distinct[:limit]
        cards = [candidate_from_record(row, constraints) for row in shown]
        answer = build_answer(constraints, filtered, cards)
        if len(distinct) > len(shown):
            answer = (
                f"Showing {len(shown)} of {len(distinct)} restaurants that match the stated conditions. "
                "A missing price is omitted and is not described as confirmed.\n"
                + answer
            )
        tools: list[str] = []
        if include_web and web_search_enabled():
            from food_copilot.retrieval.web_search import search_web

            web = search_web(query_text or constraints.text)
            tools.append("web_search")
            if web.get("ok"):
                lines = ["Web sources, not treated as a confirmed branch:"]
                for item in web["results"]:
                    lines.append(f"- {item['title']}: {item['url']}")
            else:
                lines = [f"Web search failed ({web.get('error')}). Local restaurant matches are still listed."]
            answer = answer + "\n" + "\n".join(lines)
        logger.info(
            "discovery retriever=%s candidates=%s eligible=%s",
            getattr(self.ranker, "name", "unknown"),
            len(candidates),
            len(cards),
        )
        payload = self._payload(request, checked.matching, filtered, answer, needs_clarification=False, cards=cards)
        payload["match_count"] = len(distinct)
        payload["candidate_count"] = len(candidates)
        payload["atmosphere"] = atmosphere
        payload["cuisine_counts"] = cuisine_counts
        if tools:
            payload["tools_called"] = tools
        return payload

    def _payload(self, request, raw_results, buckets, answer, needs_clarification, cards=None) -> dict:
        result = RecommendationResult(
            answer=answer,
            constraints=request.constraints.model_dump(),
            results=cards or [],
            exclusion_counts=dict(buckets.exclusion_counts),
            needs_clarification=needs_clarification,
        )
        payload = result.model_dump()
        payload["raw_results"] = raw_results
        payload["constraints_model"] = request.constraints
        payload["language"] = request.language
        payload["retriever"] = getattr(self.ranker, "name", "baseline")
        return payload

"""Carry the previous area into a follow-up. A new sentence is not a new city."""

import re

from food_copilot.retrieval.constraints import parse_constraints

_MORE = re.compile(
    r"other|another|more|else|how about|how bout|what about|还有|其他|别的|再推荐|换一",
    re.I,
)
_OTHER_CUISINE = re.compile(
    r"other cuisine|another cuisine|different cuisine|other type of cuisine|别的菜|其他菜系|换个菜系|换个菜",
    re.I,
)
_META = re.compile(r"what model|which model|大模型|什么模型|用的什么模型|llm", re.I)
_LISTED = re.compile(r"^- ([^:\n]+):", re.M)
_AREA = {
    "old_klang_road": "Old Klang Road",
    "kuala_lumpur": "Kuala Lumpur",
}


def is_model_question(query: str) -> bool:
    return bool(_META.search(query or ""))


def is_followup_phrase(query: str) -> bool:
    return bool(_MORE.search(query or ""))


def merge_context(saved: dict | None, incoming: dict | None) -> dict:
    """Fill gaps from the client. Empty fields do not wipe a saved restaurant search."""
    merged = dict(saved or {})
    incoming = incoming or {}
    for key in ("region", "city", "cuisine", "name_contains"):
        if incoming.get(key):
            merged[key] = incoming[key]
    for key in ("cuisines", "exclude_cuisines", "exclude_brands"):
        incoming_values = incoming.get(key)
        if isinstance(incoming_values, list) and any(incoming_values):
            merged[key] = [str(item) for item in incoming_values if item]
    names = incoming.get("shown_names")
    if isinstance(names, list) and any(names):
        prior = [str(item) for item in (merged.get("shown_names") or []) if item]
        extra = [str(item) for item in names if item]
        merged["shown_names"] = list(dict.fromkeys([*prior, *extra]))
    ids = incoming.get("shown_ids")
    if isinstance(ids, list) and any(ids):
        prior_ids = [str(item) for item in (merged.get("shown_ids") or []) if item]
        extra_ids = [str(item) for item in ids if item]
        merged["shown_ids"] = list(dict.fromkeys([*prior_ids, *extra_ids]))
    return merged


def next_session_context(previous: dict | None, payload: dict) -> dict | None:
    """Persist restaurant constraints. A general answer leaves the saved search untouched."""
    if (payload or {}).get("context_update") == "keep":
        return None
    if (payload or {}).get("context_update") == "partial":
        previous = previous or {}
        stated = (payload or {}).get("constraints") or {}
        cuisine = stated.get("cuisine") or previous.get("cuisine")
        if stated.get("cuisine") or stated.get("name_contains"):
            brand = stated.get("name_contains")
        else:
            brand = previous.get("name_contains")
        if not cuisine and not brand and not previous.get("region") and not previous.get("city"):
            return None
        return {
            "region": previous.get("region"),
            "city": previous.get("city"),
            "cuisine": cuisine,
            "cuisines": [cuisine] if cuisine else list(previous.get("cuisines") or []),
            "exclude_cuisines": list(previous.get("exclude_cuisines") or []),
            "name_contains": brand,
            "exclude_brands": list(previous.get("exclude_brands") or []),
            "shown_names": list(previous.get("shown_names") or []),
            "shown_ids": list(previous.get("shown_ids") or []),
        }
    previous = previous or {}
    constraints = (payload or {}).get("constraints") or {}
    names = [
        item.get("name")
        for item in ((payload or {}).get("results") or [])
        if isinstance(item, dict) and item.get("name")
    ]
    ids = [
        item.get("restaurant_id")
        for item in ((payload or {}).get("results") or [])
        if isinstance(item, dict) and item.get("restaurant_id")
    ]
    replacing = (payload or {}).get("context_update") != "accumulate"
    if not replacing:
        names = list(dict.fromkeys([*(previous.get("shown_names") or []), *names]))
        ids = list(dict.fromkeys([*(previous.get("shown_ids") or []), *ids]))
    region = constraints.get("region") or None
    city = constraints.get("city") or None
    cuisine = constraints.get("cuisine") or None
    brand = constraints.get("name_contains") or None
    stated_cuisines = [str(item) for item in (constraints.get("cuisines") or []) if item]
    if not stated_cuisines and cuisine:
        stated_cuisines = [cuisine]
    stated_exclude = [str(item) for item in (constraints.get("exclude_brands") or []) if item]
    stated_exclude_cuisines = [str(item) for item in (constraints.get("exclude_cuisines") or []) if item]
    if stated_exclude_cuisines and not stated_cuisines:
        kept_cuisine = None
        kept_cuisines = []
        kept_exclude_cuisines = stated_exclude_cuisines
    elif replacing:
        kept_cuisine = cuisine
        kept_cuisines = stated_cuisines
        kept_exclude_cuisines = [item for item in stated_exclude_cuisines if item not in stated_cuisines]
    else:
        kept_cuisine = cuisine or previous.get("cuisine")
        kept_cuisines = stated_cuisines or [str(item) for item in (previous.get("cuisines") or []) if item]
        kept_exclude_cuisines = stated_exclude_cuisines or [str(item) for item in (previous.get("exclude_cuisines") or []) if item]
    if replacing:
        kept_brand = brand
        if brand:
            kept_exclude = [item for item in stated_exclude if item != brand]
        elif stated_exclude:
            kept_exclude = stated_exclude
        else:
            kept_exclude = [str(item) for item in (previous.get("exclude_brands") or []) if item]
    else:
        kept_brand = brand or previous.get("name_contains")
        kept_exclude = stated_exclude or [str(item) for item in (previous.get("exclude_brands") or []) if item]
    if not region and not city and not kept_cuisine and not kept_cuisines and not kept_brand and not kept_exclude and not kept_exclude_cuisines and not names and not constraints.get("ambience") and not previous.get("ambience"):
        return None
    return {
        "region": region or previous.get("region"),
        "city": city or previous.get("city"),
        "cuisine": kept_cuisine,
        "cuisines": kept_cuisines,
        "exclude_cuisines": kept_exclude_cuisines,
        "name_contains": kept_brand,
        "exclude_brands": kept_exclude,
        "shown_names": names,
        "shown_ids": ids,
        "ambience": constraints.get("ambience") or previous.get("ambience"),
    }


def apply_history(query: str, history: list[dict] | None, context: dict | None = None) -> tuple[str, list[str]]:
    """Inherit area and cuisine unless this sentence sets them. Skip names already shown."""
    current = parse_constraints(query or "")
    context = context or {}
    history = history or []
    users = [str(item.get("content") or "") for item in history if item.get("role") == "user"]
    assistants = [str(item.get("content") or "") for item in history if item.get("role") == "assistant"]
    previous = parse_constraints(users[-1]) if users else None
    region = current.region or (previous.region if previous else None) or context.get("region")
    city = current.city or (previous.city if previous else None) or context.get("city")
    current_cuisines = [label for label in (current.cuisines or []) if label not in (current.exclude_cuisines or [])]
    other_type = bool(re.search(r"other type|别的类型|其他类型", query or "", re.I))
    switch_cuisine = bool(_OTHER_CUISINE.search(query or ""))
    prior_cuisines = list(previous.cuisines) if previous and previous.cuisines else [str(item) for item in (context.get("cuisines") or []) if item]
    if not prior_cuisines and context.get("cuisine"):
        prior_cuisines = [str(context["cuisine"])]
    if switch_cuisine or current.exclude_cuisines:
        cuisines = []
        excluded_cuisines = list(dict.fromkeys([*(current.exclude_cuisines or []), *prior_cuisines]))
    elif current_cuisines:
        cuisines = current_cuisines
        excluded_cuisines = []
    elif current.ambience and not current_cuisines:
        cuisines = []
        excluded_cuisines = []
    elif current.name_contains or other_type:
        cuisines = []
        excluded_cuisines = [str(item) for item in (context.get("exclude_cuisines") or []) if item]
    elif previous and previous.cuisines:
        cuisines = list(previous.cuisines)
        excluded_cuisines = list(previous.exclude_cuisines or [])
    else:
        cuisines = prior_cuisines
        excluded_cuisines = [str(item) for item in (context.get("exclude_cuisines") or []) if item]
    if current.name_contains and current.name_contains not in (current.exclude_brands or []):
        brand = current.name_contains
    elif current_cuisines or current.exclude_brands or switch_cuisine or current.exclude_cuisines or current.ambience:
        brand = None
    elif previous and previous.name_contains:
        brand = previous.name_contains
    else:
        brand = context.get("name_contains")
    if current.exclude_brands:
        excluded = list(current.exclude_brands)
    elif current.name_contains:
        excluded = []
    elif previous and previous.exclude_brands:
        excluded = list(previous.exclude_brands)
    else:
        excluded = [str(item) for item in (context.get("exclude_brands") or []) if item]
    ambience = current.ambience or (previous.ambience if previous else None) or context.get("ambience")
    cuisine = cuisines[0] if len(cuisines) == 1 else None
    extra = []
    for label in cuisines:
        if label not in current_cuisines:
            extra.append(label)
    if len(cuisines) > 1 and "and" not in (query or "").lower():
        extra.append("and")
    if brand and not current.name_contains:
        extra.append(str(brand))
    for label in excluded:
        if label not in (current.exclude_brands or []):
            extra.append(f"except {label}")
    for label in excluded_cuisines:
        if label not in (current.exclude_cuisines or []):
            extra.append(f"except {label}")
    if ambience and not current.ambience:
        extra.append("romantic" if ambience == "date" else str(ambience))
    if not current.region and not current.city:
        area = _AREA.get(str(region or ""), str(city or ""))
        if area:
            extra.append(area)
    names: list[str] = []
    if _MORE.search(query or "") and not current.name_contains and not current.exclude_brands:
        names.extend(str(item) for item in (context.get("shown_names") or []) if item)
        if assistants:
            names.extend(_LISTED.findall(assistants[-1]))
    text = query if not extra else f"{query}. {' '.join(extra)}"
    return text.strip(), list(dict.fromkeys(names))


def present_results(constraints: dict, cards: list[dict], total: int | None = None, cuisine_counts: dict | None = None) -> str:
    """User-facing list. Internal ids stay off the page."""
    brand = constraints.get("name_contains")
    cuisines = [str(item) for item in (constraints.get("cuisines") or []) if item]
    excluded_cuisines = [str(item) for item in (constraints.get("exclude_cuisines") or []) if item]
    asked = " and ".join(cuisines) if len(cuisines) > 1 else (constraints.get("cuisine") or brand or "restaurants")
    region = _AREA.get(constraints.get("region") or "", constraints.get("city") or "the requested area")
    count = total if total is not None else len(cards)
    counts = cuisine_counts or {}
    if len(cuisines) > 1:
        lines = []
        for label in cuisines:
            found = counts.get(label)
            if found is None:
                found = sum(1 for card in cards if label in str(card.get("cuisine_label") or "").lower() or label in str(card.get("name") or "").lower())
            if not found:
                lines.append(f"No stored {label} records in {region}.")
            else:
                lines.append(f"{label}: {found} stored records in {region}.")
        if not cards:
            return "\n".join(lines)
    elif not cards:
        if constraints.get("ambience") and not cuisines:
            return (
                f"No stored restaurants in {region} are available for this request. "
                f"No stored {constraints['ambience']} atmosphere evidence was found. "
                "Cuisine alone is not treated as mood."
            )
        if excluded_cuisines and not cuisines:
            return f"No stored restaurants in {region} outside {', '.join(excluded_cuisines)}."
        return f"No stored {asked} in {region} match this request."
    elif excluded_cuisines and not cuisines:
        lines = [f"Here are {len(cards)} restaurants in {region} outside {', '.join(excluded_cuisines)}."]
    elif brand and not constraints.get("cuisine") and len(cuisines) <= 1:
        lines = [f"{count} {_place_title(brand, cards)} in {region}."]
        if len(cards) < count:
            lines.append(f"Showing {len(cards)} of {count}.")
    elif constraints.get("ambience") and not _atmosphere_supported(cards):
        lines = [
            f"No stored {constraints['ambience']} atmosphere evidence in {region}. Cuisine alone is not treated as mood.",
            f"These {len(cards)} stored restaurants are in the area. Their ambience has not been verified.",
        ]
    elif constraints.get("ambience"):
        lines = [f"Here are {len(cards)} restaurants in {region} with stored {constraints['ambience']} atmosphere evidence."]
    else:
        lines = [f"Here are {len(cards)} {asked} options in {region}."]
    missing_address = sum(1 for card in cards if not str(card.get("stored_address") or "").strip())
    if missing_address == len(cards):
        lines.append("Street addresses are not on file.")
    elif missing_address:
        lines.append("Some of these have no street address on file.")
    shared_cuisine = _shared_cuisine(cards)
    if shared_cuisine:
        lines.append(f"Cuisine on file: {shared_cuisine}.")
    for index, card in enumerate(cards, start=1):
        lines.append(f"{index}. {_place_line(card, include_cuisine=not shared_cuisine)}")
    return "\n".join(lines)


def _shared_cuisine(cards: list[dict]) -> str | None:
    labels = [str(card.get("cuisine_label") or "").strip() for card in cards]
    if labels and labels[0] and all(label == labels[0] for label in labels):
        return labels[0]
    return None


def _place_title(brand: str, cards: list[dict]) -> str:
    names = list(dict.fromkeys(str(card.get("name")).strip() for card in cards if str(card.get("name") or "").strip()))
    if len(names) == 1:
        return names[0]
    return brand


def _place_line(card: dict, include_cuisine: bool = True) -> str:
    name = str(card.get("name") or "").strip() or "Unnamed restaurant"
    parts = [name]
    cuisine = str(card.get("cuisine_label") or "").strip()
    if include_cuisine and cuisine and cuisine.casefold() not in name.casefold():
        parts.append(cuisine)
    address = str(card.get("stored_address") or "").strip()
    if address:
        parts.append(address)
    return " — ".join(parts)


def _atmosphere_supported(cards: list[dict]) -> bool:
    return any("matches the requested atmosphere" in str(card.get("match_reason") or "") for card in cards)


def _search_place(constraints: dict) -> str:
    region = constraints.get("region")
    if region == "old_klang_road":
        return "Old Klang Road Kuala Lumpur"
    if region == "kuala_lumpur":
        return "Kuala Lumpur"
    return constraints.get("city") or "Kuala Lumpur"


def web_query(constraints: dict) -> str:
    cuisines = [str(item) for item in (constraints.get("cuisines") or []) if item]
    cuisine = " and ".join(cuisines) if cuisines else (constraints.get("cuisine") or constraints.get("name_contains") or "")
    ambience = constraints.get("ambience")
    if ambience == "date":
        lead = "romantic dinner"
    elif ambience == "moody":
        lead = "moody dining"
    else:
        lead = ""
    parts = [lead, cuisine, "restaurant", _search_place(constraints)]
    return " ".join(part for part in parts if part)


def alternative_web_query(constraints: dict) -> str:
    """One broader restaurant query. It does not repeat the word date, which Bing treats as a calendar."""
    return f"restaurants in {_search_place(constraints)}"

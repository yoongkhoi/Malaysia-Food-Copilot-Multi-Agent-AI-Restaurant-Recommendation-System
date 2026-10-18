"""Review-backed shortlist. Only a unique in-area name can be cited."""

from food_copilot.config.settings import ROOT
from food_copilot.retrieval.constraints import QueryConstraints, exclusion_code
from food_copilot.reviews.retrieve import CONFIRMED_MATCH, UNCONFIRMED_MATCH, load_jsonl

_PILOT = ROOT / "data" / "processed" / "reviews" / "pilot_corpus.jsonl"


def _usable_name(row: dict) -> bool:
    name = str(row.get("name") or "").strip()
    return bool(name) and name.casefold() not in {"unnamed", "unnamed restaurant"}


def _clip(text: str) -> str:
    return " ".join(str(text or "").split())[:180]


def recommend_from_reviews(docs: list[dict], constraints: dict, canonical_rows: list[dict]) -> dict:
    """Group confirmed reviews. Ambiguous and unmatched rows are not citations."""
    by_id = {row.get("restaurant_id"): row for row in canonical_rows if row.get("restaurant_id")}
    checked = QueryConstraints(
        region=constraints.get("region"),
        city=constraints.get("city"),
        cuisine=constraints.get("cuisine"),
        cuisines=list(constraints.get("cuisines") or []),
        exclude_cuisines=list(constraints.get("exclude_cuisines") or []),
        name_contains=constraints.get("name_contains"),
        exclude_brands=list(constraints.get("exclude_brands") or []),
    )
    excluded = {str(item) for item in (constraints.get("exclude_ids") or [])}
    groups: dict[str, list[dict]] = {}
    saw_unconfirmed = False
    for doc in docs:
        status = doc.get("match_status")
        if status in UNCONFIRMED_MATCH:
            saw_unconfirmed = True
            continue
        if status not in CONFIRMED_MATCH or not doc.get("restaurant_id"):
            continue
        if doc.get("likely_duplicate"):
            continue
        restaurant_id = doc["restaurant_id"]
        if restaurant_id in excluded:
            continue
        record = by_id.get(restaurant_id)
        if exclusion_code(record or {}, checked):
            continue
        if not record or not _usable_name(record):
            continue
        groups.setdefault(restaurant_id, []).append(doc)
    if not groups:
        if saw_unconfirmed:
            note = "Review evidence does not identify one canonical branch, so no review was attached."
        else:
            note = (
                "No confirmed review is attached to a named canonical restaurant in this area. "
                "Review-based ranking was not applied."
            )
        return {"ok": False, "note": note, "restaurants": [], "evidence": []}
    ranked = sorted(groups, key=lambda restaurant_id: (-len(groups[restaurant_id]), str(by_id[restaurant_id].get("name") or "")))
    restaurants = []
    evidence = []
    lines = [
        "Review opinions from the pilot corpus. Only a unique restaurant name inside the canonical area is cited.",
        "These are not verified facts, and they are not a ranking of every restaurant.",
    ]
    for restaurant_id in ranked[:3]:
        record = by_id[restaurant_id]
        reviews = groups[restaurant_id]
        ratings = [float(item["rating"]) for item in reviews if isinstance(item.get("rating"), (int, float))]
        sources = sorted({str(item.get("source") or "unknown") for item in reviews})
        average = round(sum(ratings) / len(ratings), 2) if ratings else None
        liked = next((item for item in reviews if isinstance(item.get("rating"), (int, float)) and item["rating"] >= 4 and item.get("review_text")), None)
        mixed = next((item for item in reviews if isinstance(item.get("rating"), (int, float)) and item["rating"] <= 3 and item.get("review_text")), None)
        address = record.get("address") or "street address is not on file"
        lines.append(f"- {record.get('name')} — {address}.")
        if average is None:
            lines.append(f"  Pilot reviews: {len(reviews)}. No numeric rating was stored. Sources: {', '.join(sources)}.")
        else:
            lines.append(
                f"  Pilot reviews: {len(reviews)}. Average of stored ratings: {average}. Sources: {', '.join(sources)}. "
                "Scope: unique-name matches in the pilot corpus, not every published review."
            )
        lines.append("  No dish list was tagged on these reviews, so no dish is named here.")
        if liked:
            lines.append(f"  Higher-rated opinion: {_clip(liked.get('review_text'))}")
            evidence.append(_view(liked, "higher_rated_opinion"))
        if mixed:
            lines.append(f"  Mixed or lower-rated opinion: {_clip(mixed.get('review_text'))}")
            evidence.append(_view(mixed, "mixed_or_lower_opinion"))
        restaurants.append({
            "restaurant_id": restaurant_id,
            "name": record.get("name"),
            "stored_address": record.get("address"),
            "location_verified": bool(record.get("location_verified")),
            "dataset_origin": record.get("dataset_origin") or "canonical",
            "cuisine_label": ", ".join(record.get("cuisine") or []) or None,
            "latitude": record.get("latitude") if isinstance(record.get("latitude"), (int, float)) else None,
            "longitude": record.get("longitude") if isinstance(record.get("longitude"), (int, float)) else None,
            "price_status": "not_verified",
            "halal_status": "not_verified",
            "family_friendly": "not_verified",
            "evidence_urls": [],
            "match_reason": "Shown because confirmed pilot reviews name this canonical restaurant. Cuisine was not used as review evidence.",
        })
    return {"ok": True, "note": "", "restaurants": restaurants, "evidence": evidence, "answer": "\n".join(lines)}


def _view(doc: dict, kind: str) -> dict:
    return {
        "review_id": doc.get("review_id"),
        "restaurant_id": doc.get("restaurant_id"),
        "restaurant_name": doc.get("restaurant_name"),
        "source": doc.get("source"),
        "source_file": doc.get("source_file"),
        "rating": doc.get("rating"),
        "match_status": doc.get("match_status"),
        "span": _clip(doc.get("review_text")),
        "kind": kind,
        "opinion_not_verified_fact": True,
    }


def apply_review_recommendation(local: dict, query: str, constraints: dict, canonical_rows: list[dict], docs: list[dict] | None = None) -> None:
    """Replace the card list when confirmed reviews exist. Otherwise say ranking was not applied."""
    if docs is None:
        if not _PILOT.exists():
            local["review_note"] = "The pilot review corpus is not available. Review-based ranking was not applied."
            local["review_evidence"] = []
            local["answer"] = (local.get("answer") or "") + "\n" + local["review_note"]
            return
        docs = load_jsonl(_PILOT)
    found = recommend_from_reviews(docs, constraints, canonical_rows)
    web_lines = [
        line for line in str(local.get("answer") or "").splitlines()
        if line.startswith("Web search") or line.startswith("A second search") or line.startswith("Web sources")
    ]
    local["review_evidence"] = found.get("evidence") or []
    local["review_note"] = found.get("note") or ""
    if found.get("ok"):
        local["results"] = found["restaurants"]
        local["match_count"] = len(found["restaurants"])
        local["answer"] = found["answer"]
    else:
        named = [card for card in (local.get("results") or []) if _usable_name(card)]
        local["results"] = named[:5]
        local["match_count"] = len(local["results"])
        local["answer"] = found["note"] + "\nShowing stored restaurants without review ranking."
    if web_lines:
        local["answer"] = local["answer"] + "\n" + "\n".join(web_lines)

"""MCP tool implementations. Filtering and storage stay in the existing services."""

from food_copilot.agents.orchestrator import get_restaurant_details, handle_message
from food_copilot.config.regions import PROJECT_REGION
from food_copilot.data.repository import get_default_repository
from food_copilot.domain.models import UserRequest
from food_copilot.errors import ToolError
from food_copilot.memory.store import MemoryStore
from food_copilot.retrieval.constraints import parse_constraints
from food_copilot.services.discovery import DiscoveryService, detect_language

_PREFERENCE_NOTE = "This is a saved user preference. It is not a restaurant fact."
_MEMORY_FAILURE = "The memory store could not complete the request."


def discover_restaurants(query: str, service: DiscoveryService | None = None) -> dict:
    """Find restaurants with the existing hard filters. The budget and region are not relaxed."""
    if not isinstance(query, str) or len(query.strip()) < 2 or len(query) > 1000:
        return {"ok": False, "error": "invalid_input", "detail": "query must be 2 to 1000 characters"}
    outcome = handle_message(query.strip(), service)
    results = outcome.get("results") or []
    return {
        "ok": True,
        "answer": outcome.get("answer") or "",
        "constraints": outcome.get("constraints") or {},
        "results": results,
        "eligible_restaurant_ids": [item["restaurant_id"] for item in results],
        "exclusion_counts": outcome.get("exclusion_counts") or {},
        "needs_clarification": bool(outcome.get("needs_clarification")),
        "language": outcome.get("language") or "",
        "retriever": outcome.get("retriever") or "baseline",
        "sources_note": "Shown facts come from stored records. Unverified fields stay unverified.",
    }


def restaurant_details(restaurant_id: str, repository=None) -> dict:
    """Read one stored restaurant by its exact id."""
    try:
        return get_restaurant_details(restaurant_id, repository=repository or get_default_repository())
    except ToolError as exc:
        return {"ok": False, "error": "invalid_input", "detail": str(exc)}


def restaurant_evidence(restaurant_id: str, repository=None) -> dict:
    """Read stored price, address, and halal evidence for one restaurant."""
    details = restaurant_details(restaurant_id, repository=repository)
    if not details.get("ok"):
        return details
    row = details["restaurant"]
    price = row.get("price_range_myr") or {}
    halal = row.get("halal_status") or {}
    return {
        "ok": True,
        "restaurant_id": row.get("restaurant_id"),
        "address": row.get("address"),
        "location_verified": bool(row.get("location_verified")),
        "location_evidence": row.get("location_evidence"),
        "price_status": price.get("status") or "not_verified",
        "price_min_myr": price.get("min"),
        "price_max_myr": price.get("max"),
        "halal_status": halal.get("status") or "not_verified",
        "halal_source_url": halal.get("source_url"),
        "evidence": details.get("evidence") or [],
    }


def _memory(memory: MemoryStore | None):
    store = memory or MemoryStore()
    status = store.status()
    if not status.get("postgres") or not status.get("redis"):
        return None, {"ok": False, "error": "memory_unavailable", "status": status}
    return store, None


def _memory_call(memory: MemoryStore | None, method: str, *args):
    store, error = _memory(memory)
    if error:
        return error
    try:
        return getattr(store, method)(*args)
    except (RuntimeError, OSError, ValueError):
        return {"ok": False, "error": "memory_unavailable", "detail": _MEMORY_FAILURE}


def user_preferences(user_id: str, memory: MemoryStore | None = None) -> dict:
    """Read preferences the user has explicitly saved."""
    if not _id_ok(user_id):
        return {"ok": False, "error": "invalid_input", "detail": "user_id must be 1 to 80 characters"}
    result = _memory_call(memory, "preferences", user_id.strip())
    if isinstance(result, dict) and result.get("ok") is False:
        return result
    return {
        "ok": True,
        "user_id": user_id.strip(),
        "preferences": result,
        "note": _PREFERENCE_NOTE,
    }


def save_user_preference(
    user_id: str,
    key: str,
    value: str,
    confirmed: bool = False,
    memory: MemoryStore | None = None,
) -> dict:
    """Save a preference only when the caller sets confirmed to true."""
    if confirmed is not True:
        return {
            "ok": False,
            "error": "confirmation_required",
            "detail": "A one-off request is not saved. confirmed must be true.",
        }
    if not _id_ok(user_id) or not _id_ok(key) or not isinstance(value, str) or not value.strip() or len(value) > 500:
        return {
            "ok": False,
            "error": "invalid_input",
            "detail": "user_id and key must be 1 to 80 characters, and value must be 1 to 500 characters",
        }
    result = _memory_call(memory, "save_preference", user_id.strip(), key.strip(), value.strip(), True)
    if isinstance(result, dict) and result.get("ok") is False:
        return result
    saved = dict(result)
    saved["ok"] = True
    saved["note"] = _PREFERENCE_NOTE
    return saved


def conversation_summary(session_id: str, memory: MemoryStore | None = None) -> dict:
    """Read the stored messages for one session."""
    if not _id_ok(session_id):
        return {"ok": False, "error": "invalid_input", "detail": "session_id must be 1 to 80 characters"}
    return _memory_call(memory, "conversation_summary", session_id.strip())


def _id_ok(value: str) -> bool:
    return isinstance(value, str) and 1 <= len(value.strip()) <= 80


def search_restaurants(
    query: str,
    region: str = "",
    cuisine: str = "",
    max_budget_myr: float = 0,
    name_contains: str = "",
    service: DiscoveryService | None = None,
    exclude_ids: list[str] | None = None,
) -> dict:
    """Search the canonical dataset. A typed budget or area is not relaxed by the caller."""
    if not isinstance(query, str) or len(query.strip()) < 2 or len(query) > 1000:
        return {"ok": False, "error": "invalid_input", "detail": "query must be 2 to 1000 characters"}
    constraints = parse_constraints(query.strip())
    if constraints.region is None and region in {"old_klang_road", "kuala_lumpur"}:
        constraints.region = region
    if constraints.region is None and constraints.city is None:
        constraints.region = PROJECT_REGION
    if not constraints.cuisine and not constraints.cuisines and cuisine:
        constraints.cuisine = cuisine.strip().lower()
        constraints.cuisines = [constraints.cuisine]
    if constraints.max_budget_myr is None and max_budget_myr and max_budget_myr > 0:
        constraints.max_budget_myr = float(max_budget_myr)
        if constraints.budget_mode == "none":
            constraints.budget_mode = "hard"
    if not constraints.name_contains and name_contains:
        constraints.name_contains = name_contains.strip().lower()
    finder = service or DiscoveryService()
    request = UserRequest(text=query.strip(), constraints=constraints, language=detect_language(query))
    outcome = finder.from_constraints(
        constraints,
        query_text=query.strip(),
        request=request,
        include_web=False,
        exclude_ids=exclude_ids or [],
    )
    results = outcome.get("results") or []
    return {
        "ok": True,
        "constraints": outcome.get("constraints") or {},
        "results": results,
        "eligible_restaurant_ids": [item.get("restaurant_id") for item in results if item.get("restaurant_id")],
        "exclusion_counts": outcome.get("exclusion_counts") or {},
        "retriever": outcome.get("retriever") or "baseline",
        "match_count": outcome.get("match_count"),
        "sources_note": "Rows come from the canonical restaurant dataset. Unverified fields stay unverified.",
    }


def get_restaurant_reviews(restaurant_id: str = "", name: str = "", limit: int = 3) -> dict:
    """Return confirmed pilot-corpus excerpts. Unmatched reviews are not quoted."""
    from food_copilot.config.settings import ROOT
    from food_copilot.reviews.retrieve import CONFIRMED_MATCH, load_jsonl

    path = ROOT / "data" / "processed" / "reviews" / "pilot_corpus.jsonl"
    if not path.exists():
        return {"ok": False, "error": "review_corpus_missing", "reviews": [], "note": "The pilot review file is not on disk."}
    wanted_id = (restaurant_id or "").strip()
    wanted_name = (name or "").strip().casefold()
    if not wanted_id and not wanted_name:
        return {"ok": False, "error": "invalid_input", "detail": "restaurant_id or name is required", "reviews": []}
    matched = []
    for doc in load_jsonl(path):
        if doc.get("match_status") not in CONFIRMED_MATCH:
            continue
        if wanted_id and doc.get("restaurant_id") == wanted_id:
            matched.append(doc)
        elif wanted_name and wanted_name in str(doc.get("restaurant_name") or "").casefold():
            matched.append(doc)
    excerpts = []
    for doc in matched[: max(1, min(int(limit or 3), 5))]:
        excerpts.append({
            "restaurant_id": doc.get("restaurant_id"),
            "restaurant_name": doc.get("restaurant_name"),
            "source": doc.get("source") or "unknown",
            "rating": doc.get("rating"),
            "excerpt": " ".join(str(doc.get("review_text") or "").split())[:240],
            "match_status": doc.get("match_status"),
        })
    if not excerpts:
        return {
            "ok": True,
            "reviews": [],
            "note": "No confirmed review is attached to this restaurant in the pilot corpus.",
        }
    return {
        "ok": True,
        "reviews": excerpts,
        "note": "These excerpts are review opinions, not verified facts.",
    }

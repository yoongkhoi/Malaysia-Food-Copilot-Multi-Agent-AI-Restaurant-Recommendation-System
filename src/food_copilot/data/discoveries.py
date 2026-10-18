"""Sidecar for web discoveries. Canonical restaurants.json is never rewritten here."""

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from food_copilot.config.settings import DISCOVERED_RESTAURANTS_PATH, MERGE_CANDIDATES_PATH

_LISTICLE = re.compile(r"\b(best|top|guide|list|review|reviews|restaurants)\b|^\d+\b", re.I)
_PLACE = re.compile(r"\b(jalan|jln\.?|lorong|street|old klang road)\b", re.I)


def discovered_path() -> Path:
    override = os.environ.get("DISCOVERED_RESTAURANTS_PATH", "").strip()
    return Path(override) if override else DISCOVERED_RESTAURANTS_PATH


def merge_queue_path() -> Path:
    override = os.environ.get("MERGE_CANDIDATES_PATH", "").strip()
    return Path(override) if override else MERGE_CANDIDATES_PATH


def load_discovered() -> list[dict]:
    path = discovered_path()
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else []


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def _write(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def consider_web_result(result: dict, constraints: dict, existing_names: list[tuple[str, str]]) -> dict:
    """Store a source-backed candidate, or queue an uncertain duplicate. Never invent an address."""
    title = str(result.get("title") or "").strip()
    url = str(result.get("url") or "").strip()
    snippet = str(result.get("snippet") or "").strip()
    if not title or not url.startswith("http"):
        return {"action": "skipped", "reason": "missing_title_or_url"}
    if _LISTICLE.search(title):
        return {"action": "skipped", "reason": "listicle"}
    if not _PLACE.search(snippet) and not _PLACE.search(title):
        return {"action": "skipped", "reason": "no_place_signal"}
    region = constraints.get("region")
    blob = f"{title} {snippet}"
    if region == "old_klang_road" and not re.search(r"old klang road|jalan klang lama", blob, re.I):
        return {"action": "skipped", "reason": "region_not_in_source"}
    if region == "kuala_lumpur" and not re.search(r"kuala lumpur|old klang road", blob, re.I):
        return {"action": "skipped", "reason": "region_not_in_source"}
    cuisines = [str(item).lower() for item in (constraints.get("cuisines") or []) if item]
    if not cuisines and constraints.get("cuisine"):
        cuisines = [str(constraints["cuisine"]).lower()]
    if cuisines and not any(label in blob.lower() for label in cuisines):
        return {"action": "skipped", "reason": "cuisine_not_in_source"}
    needle = _norm(title)
    for restaurant_id, name in existing_names:
        current = _norm(name)
        if current and (current == needle or (len(needle) >= 6 and needle in current)):
            return {"action": "matched_existing", "restaurant_id": restaurant_id}
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    restaurant_id = f"WEB-{digest}"
    rows = load_discovered()
    if any(row.get("restaurant_id") == restaurant_id for row in rows):
        return {"action": "already_stored", "restaurant_id": restaurant_id}
    for row in rows:
        if _norm(row.get("name") or "") == needle and row.get("restaurant_id") != restaurant_id:
            queue = []
            path = merge_queue_path()
            if path.exists():
                loaded = json.loads(path.read_text(encoding="utf-8"))
                queue = loaded if isinstance(loaded, list) else []
            queue.append({
                "left_id": row.get("restaurant_id"),
                "right_url": url,
                "reason": "same_normalized_name",
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            })
            _write(path, queue)
            return {"action": "queued", "restaurant_id": row.get("restaurant_id")}
    region = constraints.get("region") or "kuala_lumpur"
    cuisine = cuisines[0] if cuisines else constraints.get("cuisine")
    record = {
        "restaurant_id": restaurant_id,
        "name": title[:160],
        "regions": [region],
        "location_verified": False,
        "address": None,
        "latitude": None,
        "longitude": None,
        "cuisine": [cuisine] if cuisine else [],
        "dataset_origin": "discovered",
        "description": snippet[:400] or None,
        "price_range_myr": {"status": "unknown"},
        "halal_status": {"status": "unknown"},
        "sources": [{
            "source_name": "web_search",
            "source_url": url,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "fields": ["name", "description"],
        }],
        "record_status": "needs_review",
    }
    rows.append(record)
    _write(discovered_path(), rows)
    return {"action": "inserted", "restaurant_id": restaurant_id}

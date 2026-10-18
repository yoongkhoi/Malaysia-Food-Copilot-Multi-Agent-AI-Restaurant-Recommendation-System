"""Audit a candidate restaurant file. This module does not write canonical data."""

import json
from collections import Counter
from pathlib import Path

from food_copilot.data.schema import LocationEvidence, Restaurant
from food_copilot.retrieval.constraints import _search_link, price_support


def audit_records(rows: list[dict], canonical_ids: set[str] | None = None) -> dict:
    ids = [row.get("restaurant_id") for row in rows if isinstance(row, dict)]
    counts = Counter(ids)
    duplicates = sorted(item for item, count in counts.items() if item and count > 1)
    names = Counter((row.get("name") or "").casefold() for row in rows if isinstance(row, dict) and row.get("name"))
    price_status = Counter()
    halal_status = Counter()
    location_verified = Counter()
    location_evidence = Counter()
    search_verified = 0
    missing_name = 0
    missing_coordinates = 0
    schema_errors = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        price = row.get("price_range_myr") or {}
        price_status[price.get("status")] += 1
        halal_status[(row.get("halal_status") or {}).get("status")] += 1
        location_verified[bool(row.get("location_verified"))] += 1
        location_evidence[row.get("location_evidence")] += 1
        if not row.get("name"):
            missing_name += 1
        if row.get("latitude") is None or row.get("longitude") is None:
            missing_coordinates += 1
        url = str(price.get("source_url") or "")
        if price.get("status") == "verified" and (not url or _search_link(url)):
            search_verified += 1
        if row.get("location_evidence") not in LocationEvidence.__args__:
            schema_errors += 1
        else:
            try:
                Restaurant.model_validate(row)
            except Exception:
                schema_errors += 1
    candidate_ids = {item for item in ids if item}
    report = {
        "records": len(rows),
        "unique_ids": len(candidate_ids),
        "duplicate_ids": duplicates,
        "duplicate_names": sorted(name for name, count in names.items() if count > 1),
        "missing_names": missing_name,
        "missing_coordinates": missing_coordinates,
        "price_status": dict(price_status),
        "halal_status": dict(halal_status),
        "location_verified": {str(key): value for key, value in location_verified.items()},
        "location_evidence": dict(location_evidence),
        "verified_price_without_supporting_source": search_verified,
        "schema_or_location_errors": schema_errors,
    }
    if canonical_ids is not None:
        report["missing_from_candidate"] = len(canonical_ids - candidate_ids)
        report["not_in_canonical"] = len(candidate_ids - canonical_ids)
        report["shared_ids"] = len(candidate_ids & canonical_ids)
    return report


def audit_file(path: Path, canonical: Path | None = None) -> dict:
    rows = json.loads(path.read_text(encoding="utf-8"))
    canonical_ids = None
    if canonical and canonical.exists():
        canonical_rows = json.loads(canonical.read_text(encoding="utf-8"))
        canonical_ids = {row.get("restaurant_id") for row in canonical_rows}
    report = audit_records(rows, canonical_ids)
    report["path"] = str(path)
    report["bytes"] = path.stat().st_size
    supported = Counter(price_support(row)[0] for row in rows if isinstance(row, dict))
    report["evidence_grade"] = dict(supported)
    return report

"""Human review sheet. not_verified means not checked, not a negative finding."""

import csv
from pathlib import Path

COLUMNS = [
    "restaurant_id",
    "name",
    "address",
    "latitude",
    "longitude",
    "source_url",
    "regions",
    "location_evidence",
    "location_verified",
    "price_min_myr",
    "price_max_myr",
    "price_status",
    "price_source_url",
    "halal_status",
    "halal_source_url",
    "family_friendly",
    "review_status",
    "inclusion_note",
]


def review_row(record: dict, inclusion_note: str = "") -> dict:
    price = record.get("price_range_myr") or {}
    halal = record.get("halal_status") or {}
    source = (record.get("sources") or [{}])[0]
    return {
        "restaurant_id": record.get("restaurant_id") or "",
        "name": record.get("name") or "",
        "address": record.get("address") or "",
        "latitude": "" if record.get("latitude") is None else record.get("latitude"),
        "longitude": "" if record.get("longitude") is None else record.get("longitude"),
        "source_url": source.get("source_url") or "",
        "regions": "|".join(record.get("regions") or []),
        "location_evidence": record.get("location_evidence") or "",
        "location_verified": "true" if record.get("location_verified") else "false",
        "price_min_myr": "" if price.get("min") is None else price.get("min"),
        "price_max_myr": "" if price.get("max") is None else price.get("max"),
        "price_status": price.get("status") or "not_verified",
        "price_source_url": "",
        "halal_status": halal.get("status") or "not_verified",
        "halal_source_url": halal.get("source_url") or "",
        "family_friendly": record.get("suitable_for_family") or "not_verified",
        "review_status": "pending",
        "inclusion_note": inclusion_note,
    }


def write_review_csv(kept: list[dict], rejected: list[dict], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [review_row(record) for record in kept]
    for item in rejected:
        note = item.get("diagnosis") or "; ".join(item.get("errors") or [])
        rows.append(review_row(item.get("record") or {}, inclusion_note=note or ""))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)

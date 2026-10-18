#!/usr/bin/env python3
"""Sample Old Klang Road rows for human review.

Batch 1 is 25 places. Batch 2 is those 25 plus 25 more, 50 in total.
Nothing is marked verified.
"""

import csv
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

random.seed(42)

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "data" / "staging" / "restaurant_review.csv"
OUT_BATCH1 = ROOT / "data" / "staging" / "okr_review_batch1_25.csv"
OUT_BATCH2 = ROOT / "data" / "staging" / "okr_review_batch2_50.csv"

REQUIRED_COLS = [
    "restaurant_id",
    "name",
    "regions",
    "location_evidence",
    "location_verified",
    "price_status",
    "halal_status",
    "review_status",
]

REVIEW_COLS = [
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
    "source_type",
    "address_evidence",
    "halal_evidence",
    "similar_name_note",
]


def parse_source_type(restaurant_id: str) -> str:
    match = re.search(r"MY-OSM-(node|way|relation)-", restaurant_id or "")
    return match.group(1) if match else "unknown"


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def names_look_similar(left: str, right: str) -> bool:
    """Flag only. Different branches are not merged."""
    if not left or not right or left == right:
        return False
    if left in right or right in left:
        return True
    left_tokens, right_tokens = set(left.split()), set(right.split())
    if len(left_tokens) < 2 or len(right_tokens) < 2:
        return False
    shared = len(left_tokens & right_tokens)
    return shared / len(left_tokens | right_tokens) >= 0.6


def load_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in REQUIRED_COLS if column not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit(f"Missing required columns: {', '.join(missing)}")
        return list(reader)


def filter_okr(rows: list[dict]) -> list[dict]:
    kept = []
    seen = set()
    duplicate_ids = []
    for row in rows:
        regions = row.get("regions") or ""
        if "old_klang_road" not in regions.split("|"):
            continue
        restaurant_id = row.get("restaurant_id") or ""
        if restaurant_id in seen:
            duplicate_ids.append(restaurant_id)
            continue
        seen.add(restaurant_id)
        kept.append(row)
    if duplicate_ids:
        print(f"Duplicate restaurant_id values skipped: {len(duplicate_ids)}")
    return kept


def stratify(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    buckets = defaultdict(list)
    for row in rows:
        source_type = parse_source_type(row["restaurant_id"])
        evidence = (row.get("location_evidence") or "").strip() or "(empty)"
        buckets[(source_type, evidence)].append(row)
    return buckets


def allocate(buckets: dict[tuple[str, str], list[dict]], total: int) -> dict[tuple[str, str], int]:
    """Largest-remainder quotas. No stratum is promised a seat it cannot fill."""
    sizes = {key: len(value) for key, value in buckets.items()}
    pool = sum(sizes.values())
    if pool == 0 or total <= 0:
        return {key: 0 for key in sizes}
    raw = {key: total * sizes[key] / pool for key in sizes}
    alloc = {key: min(sizes[key], int(raw[key])) for key in sizes}
    left = min(total, pool) - sum(alloc.values())
    order = sorted(sizes, key=lambda key: (raw[key] - int(raw[key]), sizes[key]), reverse=True)
    while left > 0:
        progressed = False
        for key in order:
            if left <= 0:
                break
            if alloc[key] < sizes[key]:
                alloc[key] += 1
                left -= 1
                progressed = True
        if not progressed:
            break
    return alloc


def pick_from_bucket(bucket, count, seen_names, seen_ids):
    named = [row for row in bucket if (row.get("name") or "").strip()]
    unnamed = [row for row in bucket if not (row.get("name") or "").strip()]
    random.shuffle(named)
    random.shuffle(unnamed)
    picked = []
    for row in named + unnamed:
        restaurant_id = row["restaurant_id"]
        if restaurant_id in seen_ids:
            continue
        name = normalize_name(row.get("name"))
        if name and name in seen_names:
            continue
        picked.append(row)
        seen_ids.add(restaurant_id)
        if name:
            seen_names.add(name)
        if len(picked) >= count:
            break
    return picked


def sample_stratified(rows, total, seen_ids=None, seen_names=None):
    seen_ids = set(seen_ids or [])
    seen_names = set(seen_names or [])
    available = [row for row in rows if row["restaurant_id"] not in seen_ids]
    buckets = {key: value for key, value in stratify(available).items() if value}
    if not buckets:
        return []
    alloc = allocate(buckets, total)
    picked = []
    for key, count in alloc.items():
        picked.extend(pick_from_bucket(buckets[key], count, seen_names, seen_ids))
    if len(picked) < total:
        rest = [row for value in buckets.values() for row in value]
        random.shuffle(rest)
        picked.extend(pick_from_bucket(rest, total - len(picked), seen_names, seen_ids))
    return picked[:total]


def flag_similar_names(rows: list[dict]) -> None:
    names = [(index, normalize_name(row.get("name"))) for index, row in enumerate(rows)]
    for index, name in names:
        matches = [
            rows[other]["restaurant_id"]
            for other, other_name in names
            if other != index and names_look_similar(name, other_name)
        ]
        rows[index]["similar_name_note"] = "|".join(matches)


def enrich(rows: list[dict]) -> list[dict]:
    prepared = []
    for row in rows:
        item = dict(row)
        item["source_type"] = parse_source_type(item["restaurant_id"])
        item.setdefault("address_evidence", "")
        item.setdefault("halal_evidence", "")
        item.setdefault("similar_name_note", "")
        prepared.append(item)
    flag_similar_names(prepared)
    return [{column: item.get(column, "") for column in REVIEW_COLS} for item in prepared]


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLS)
        writer.writeheader()
        writer.writerows(rows)


def print_distribution(title: str, rows: list[dict], key: str) -> None:
    counts = defaultdict(int)
    for row in rows:
        counts[row.get(key) or "(empty)"] += 1
    print(title)
    for name, count in sorted(counts.items()):
        print(f"  {name}: {count}")


def main() -> int:
    if not STAGING.exists():
        print(f"Missing {STAGING}")
        return 1
    okr = filter_okr(load_rows(STAGING))
    print(f"Old Klang Road rows: {len(okr)}")
    buckets = stratify(okr)
    print("Strata (source_type x location_evidence):")
    for key in sorted(buckets):
        print(f"  {key[0]:<10} {key[1]:<12} -> {len(buckets[key])}")

    batch1 = sample_stratified(okr, 25)
    batch1_ids = {row["restaurant_id"] for row in batch1}
    batch1_names = {normalize_name(row.get("name")) for row in batch1 if normalize_name(row.get("name"))}
    additional = sample_stratified(okr, 25, seen_ids=batch1_ids, seen_names=batch1_names)
    batch2 = batch1 + additional

    write_csv(OUT_BATCH1, enrich(batch1))
    write_csv(OUT_BATCH2, enrich(batch2))

    print(f"Batch 1 actual: {len(batch1)} (requested 25) -> {OUT_BATCH1}")
    print(f"Batch 2 cumulative actual: {len(batch2)} (requested 50) -> {OUT_BATCH2}")
    if len(batch1) < 25 or len(batch2) < 50:
        print("Shortfall after name and id checks. The files contain only the rows that could be sampled.")
    print_distribution("Batch 1 source types:", enrich(batch1), "source_type")
    print_distribution("Batch 1 location evidence:", enrich(batch1), "location_evidence")
    return 0 if batch1 and batch2 else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Milestone 2, step 1.

Copy data/staging/okr_review_batch1_25.csv to a work file and check that
the copy matches the baseline. Does not edit OSM files or status defaults.
"""

import csv
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "staging" / "okr_review_batch1_25.csv"
WORK = ROOT / "data" / "staging" / "okr_review_batch1_25_work.csv"

IMMUTABLE_FIELDS = [
    "restaurant_id",
    "name",
    "latitude",
    "longitude",
    "regions",
    "source_url",
    "location_evidence",
    "source_type",
]

EDITABLE_DEFAULTS = {
    "location_verified": "false",
    "price_status": "not_verified",
    "halal_status": "not_verified",
    "family_friendly": "not_verified",
    "review_status": "pending",
}


def load_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fields = reader.fieldnames
    return rows, fields


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if not SRC.exists():
        print(f"[FAIL] baseline file not found: {SRC}")
        sys.exit(1)

    src_rows, src_fields = load_csv(SRC)
    if not src_fields:
        print("[FAIL] baseline has no header")
        sys.exit(1)

    print(f"[INFO] baseline: {SRC}")
    print(f"[INFO] rows: {len(src_rows)}")
    print(f"[INFO] columns: {len(src_fields)}")

    missing = [name for name in IMMUTABLE_FIELDS if name not in src_fields]
    missing += [name for name in EDITABLE_DEFAULTS if name not in src_fields]
    if missing:
        print(f"[FAIL] missing columns: {missing}")
        sys.exit(1)

    if len(src_rows) != 25:
        print(f"[FAIL] expected 25 rows, found {len(src_rows)}")
        sys.exit(1)

    ids = [row["restaurant_id"] for row in src_rows]
    if len(set(ids)) != len(ids):
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        print(f"[FAIL] duplicate restaurant_id: {duplicates}")
        sys.exit(1)
    print("[OK] 25 restaurant_id values are unique")

    bad_region = []
    for row in src_rows:
        tokens = [part.strip() for part in (row.get("regions") or "").split("|")]
        if "old_klang_road" not in tokens:
            bad_region.append(row["restaurant_id"])
    if bad_region:
        print(f"[FAIL] missing old_klang_road token: {bad_region}")
        sys.exit(1)
    print("[OK] all 25 rows include old_klang_road")

    for field in ["restaurant_id", "latitude", "longitude", "source_url", "source_type"]:
        empty = [
            row["restaurant_id"]
            for row in src_rows
            if not (row.get(field) or "").strip()
        ]
        if empty:
            print(f"[FAIL] empty {field}: {empty}")
            sys.exit(1)
    print("[OK] key fields are present")

    for field, expected in EDITABLE_DEFAULTS.items():
        bad = [
            row["restaurant_id"]
            for row in src_rows
            if (row.get(field) or "").strip() != expected
        ]
        if bad:
            print(f"[WARN] {field} is not {expected}: {bad[:5]}")
        else:
            print(f"[OK] {field} is {expected} on every row")

    WORK.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SRC, WORK)
    print(f"[OK] work copy written: {WORK}")

    work_rows, work_fields = load_csv(WORK)
    if work_fields != src_fields:
        print("[FAIL] work copy columns differ from the baseline")
        sys.exit(1)
    if len(work_rows) != len(src_rows):
        print("[FAIL] work copy row count differs from the baseline")
        sys.exit(1)

    work_ids = [row["restaurant_id"] for row in work_rows]
    if work_ids != ids:
        print("[FAIL] work copy restaurant_id order differs from the baseline")
        sys.exit(1)

    for field in IMMUTABLE_FIELDS:
        for src_row, work_row in zip(src_rows, work_rows):
            if src_row.get(field) != work_row.get(field):
                print(f"[FAIL] {field} differs for {src_row['restaurant_id']}")
                sys.exit(1)
    print("[OK] work copy matches the baseline (columns, row count, id order)")

    print()
    print("First 5 rows in the work copy (this order is the review order):")
    for index, row in enumerate(work_rows[:5], start=1):
        print(f"  {index}. {row['restaurant_id']} | {row.get('name') or '(no name)'}")


if __name__ == "__main__":
    main()

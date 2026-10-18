"""Normalize Old Klang Road and Kuala Lumpur snapshots. Kulim files are archived, not deleted."""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8")

from food_copilot.config.regions import PROJECT_REGION, REGIONS, regions_for_point
from food_copilot.config.settings import DATA, PROCESSED, RAW
from food_copilot.ingestion.normalize import normalize_osm_snapshot
from food_copilot.ingestion.review_export import write_review_csv
from food_copilot.ingestion.validators import split_valid

REVIEW_PATH = DATA / "staging" / "restaurant_review.csv"


def archive_kulim() -> None:
    history = DATA / "history" / "kulim"
    history.mkdir(parents=True, exist_ok=True)
    copies = {
        RAW / "osm_kulim.json": history / "osm_kulim.json",
        PROCESSED / "restaurants.json": history / "restaurants.json",
        PROCESSED / "rejected.json": history / "rejected.json",
        DATA / "staging" / "restaurant_review.csv": history / "restaurant_review.csv",
        DATA / "eval" / "queries.jsonl": DATA / "eval" / "kulim_queries.jsonl",
    }
    for source, target in copies.items():
        if source.exists() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            print(f"Archived {source.name} -> {target}")


def load_snapshots() -> list[dict]:
    rows = []
    for region_key in REGIONS:
        path = RAW / region_key / "osm.json"
        if not path.exists():
            print(f"Missing {path}")
            continue
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        for raw in snapshot:
            regions = regions_for_point(raw.get("latitude"), raw.get("longitude"))
            label = REGIONS[regions[0]]["label"] if regions else None
            rows.append({**raw, "regions": regions, "area_query": label})
    return rows


def main() -> int:
    archive_kulim()
    raw = load_snapshots()
    if not raw:
        print("No regional snapshots found. Run: python scripts/collect_osm.py --all")
        return 1
    normalized = [item.model_dump() for item in normalize_osm_snapshot(raw)]
    kept, rejected = split_valid(normalized)
    kept.sort(key=lambda record: (PROJECT_REGION not in record.get("regions", []), record["restaurant_id"]))
    PROCESSED.mkdir(parents=True, exist_ok=True)
    (PROCESSED / "restaurants.json").write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
    (PROCESSED / "rejected.json").write_text(json.dumps(rejected, ensure_ascii=False, indent=2), encoding="utf-8")
    for region_key in REGIONS:
        subset = [record for record in kept if region_key in record.get("regions", [])]
        target = PROCESSED / region_key
        target.mkdir(parents=True, exist_ok=True)
        (target / "restaurants.json").write_text(json.dumps(subset, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{region_key}: {len(subset)} in-bounds records")
    review_count = write_review_csv(kept, rejected, REVIEW_PATH)
    print(f"Held {len(rejected)} out-of-bounds records -> {PROCESSED / 'rejected.json'}")
    print(f"Wrote {review_count} review rows -> {REVIEW_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Prepare review JSONL from the original city CSVs. Does not edit those CSVs."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from food_copilot.config.settings import RESTAURANTS_PATH
from food_copilot.reviews.prepare import prepare_reviews

PILOT_NAMES = {
    "Chambers Grill",
    "Chamber's Grill",
    "Chamber’s Grill",
    "Positano Risto @ Publika",
    "Iketeru",
    "Knowhere Bangsar",
    "Ishin Japanese Dining",
    "Sausage KL Cafe & Deli",
    "Canopy Lounge Rooftop Bar KL",
}


def main() -> int:
    report = prepare_reviews(
        ROOT,
        ROOT / "data" / "processed" / "reviews",
        RESTAURANTS_PATH,
        pilot_names=PILOT_NAMES,
    )
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Collect an OpenStreetMap snapshot for one configured region. Not the final database."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from food_copilot.config.regions import PROJECT_REGION, REGIONS, overpass_query

OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)


def collect(region_key: str) -> Path:
    if region_key not in REGIONS:
        raise SystemExit(f"Unknown region {region_key}. Choose from: {', '.join(REGIONS)}")
    output = ROOT / "data" / "raw" / region_key / "osm.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = None
    last_error = None
    for url in OVERPASS_URLS:
        try:
            response = requests.post(
                url,
                data={"data": overpass_query(region_key)},
                headers={"User-Agent": "MalaysiaFoodDiscovery/0.1 (educational project)"},
                timeout=120,
            )
            response.raise_for_status()
            payload = response.json()
            break
        except requests.RequestException as error:
            last_error = error
            print(f"{url} failed for {region_key}: {error}")
    if payload is None:
        raise SystemExit(f"Could not collect {region_key}: {last_error}")
    records = []
    for element in payload.get("elements", []):
        tags = element.get("tags", {})
        center = element.get("center", {})
        lat = element.get("lat", center.get("lat"))
        lon = element.get("lon", center.get("lon"))
        records.append({
            "source": "OpenStreetMap",
            "region_collected": region_key,
            "element_type": element["type"],
            "source_id": f'{element["type"]}/{element["id"]}',
            "source_url": f'https://www.openstreetmap.org/{element["type"]}/{element["id"]}',
            "name": tags.get("name"),
            "amenity": tags.get("amenity"),
            "cuisine_raw": tags.get("cuisine"),
            "address_raw": {
                "street": tags.get("addr:street"),
                "city": tags.get("addr:city"),
                "postcode": tags.get("addr:postcode"),
            },
            "latitude": lat,
            "longitude": lon,
            "opening_hours_raw": tags.get("opening_hours"),
            "phone": tags.get("phone"),
            "collected_at": datetime.now(timezone.utc).isoformat(),
        })
    output.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Collected {len(records)} raw records for {region_key} -> {output}")
    return output


def main() -> int:
    requested = sys.argv[1:] or [PROJECT_REGION]
    if requested == ["--all"]:
        requested = list(REGIONS)
    for region_key in requested:
        collect(region_key)
    print("Review coverage, source licensing, and data quality before publishing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

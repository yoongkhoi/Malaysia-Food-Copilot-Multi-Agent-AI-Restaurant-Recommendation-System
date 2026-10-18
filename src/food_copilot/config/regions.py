"""Geographic scope. A query area is not a verified street address.

Old Klang Road is a corridor around Jalan Klang Lama. It is not the
Kuala Lumpur administrative boundary. The boxes are approximate and
repeatable; they are not official boundaries.
"""

PROJECT_REGION = "old_klang_road"
EXPANSION_REGION = "kuala_lumpur"

# south, west, north, east
REGIONS = {
    "old_klang_road": {
        "label": "Old Klang Road",
        "bbox": (3.055, 101.635, 3.125, 101.700),
        "note": "Corridor around Jalan Klang Lama, including a short buffer. Not the whole of Kuala Lumpur.",
    },
    "kuala_lumpur": {
        "label": "Kuala Lumpur",
        "bbox": (3.030, 101.615, 3.230, 101.770),
        "note": "Approximate city box for the expansion pool. Not an official boundary.",
    },
}


def in_bbox(latitude: float | None, longitude: float | None, bbox: tuple[float, float, float, float]) -> bool:
    if latitude is None or longitude is None:
        return False
    south, west, north, east = bbox
    return south <= float(latitude) <= north and west <= float(longitude) <= east


def regions_for_point(latitude: float | None, longitude: float | None) -> list[str]:
    found = {
        key for key, spec in REGIONS.items()
        if in_bbox(latitude, longitude, spec["bbox"])
    }
    return [key for key in (PROJECT_REGION, EXPANSION_REGION) if key in found]


def overpass_query(region_key: str) -> str:
    south, west, north, east = REGIONS[region_key]["bbox"]
    # nwr covers nodes, ways, and relations. Ways and relations use center coordinates.
    return f"""
[out:json][timeout:90];
(
  nwr["amenity"~"^(restaurant|cafe|fast_food|food_court)$"]({south},{west},{north},{east});
);
out center tags;
"""

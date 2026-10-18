from food_copilot.config.regions import overpass_query, regions_for_point
from food_copilot.ingestion.normalize import normalize_osm_snapshot
from food_copilot.retrieval.constraints import apply_constraints, parse_constraints

RAW = {
    "source": "OpenStreetMap",
    "source_id": "way/10",
    "source_url": "https://www.openstreetmap.org/way/10",
    "name": "Roadside Cafe",
    "amenity": "cafe",
    "cuisine_raw": None,
    "address_raw": {"street": None, "city": None, "postcode": None},
    "latitude": 3.090,
    "longitude": 101.670,
    "collected_at": "2026-10-13T00:00:00+00:00",
    "area_query": "Old Klang Road",
    "regions": ["old_klang_road", "kuala_lumpur"],
}


def test_corridor_is_not_the_whole_city():
    on_road = regions_for_point(3.090, 101.670)
    in_kl_only = regions_for_point(3.150, 101.710)
    assert on_road == ["old_klang_road", "kuala_lumpur"]
    assert in_kl_only == ["kuala_lumpur"]
    assert "nwr" in overpass_query("old_klang_road")


def test_old_klang_road_query_keeps_budget_hard():
    parsed = parse_constraints("旧巴生路 RM20 以内适合家庭吃饭")
    assert parsed.region == "old_klang_road"
    assert parsed.max_budget_myr == 20
    priced = {
        **RAW,
        "price_range_myr": {"max": 18, "basis": "per person", "status": "verified", "source_url": "https://example.local/menu"},
        "halal_status": {"status": "not_verified"},
        "location_verified": False,
    }
    unchecked = {
        **priced,
        "restaurant_id": "unchecked",
        "source_id": "node/11",
        "price_range_myr": {"max": 15, "status": "not_verified"},
    }
    outside = {**priced, "restaurant_id": "kl-only", "regions": ["kuala_lumpur"]}
    rows = [osm.model_dump() for osm in normalize_osm_snapshot([RAW])]
    rows[0]["price_range_myr"] = priced["price_range_myr"]
    rows[0]["halal_status"] = priced["halal_status"]
    buckets = apply_constraints(rows + [unchecked, outside], parsed)
    assert [row["restaurant_id"] for row in buckets.matching] == ["MY-OSM-way-10", "unchecked"]
    assert buckets.matching[0]["location_verified"] is False
    assert buckets.matching[0]["city"] is None
    assert buckets.price_unknown == []
    assert outside["restaurant_id"] in [row["restaurant_id"] for row in buckets.excluded]


def test_duplicate_osm_object_is_merged():
    other = {**RAW, "regions": ["kuala_lumpur"], "area_query": "Kuala Lumpur"}
    rows = normalize_osm_snapshot([RAW, other])
    assert len(rows) == 1
    assert rows[0].regions == ["old_klang_road", "kuala_lumpur"]
    assert rows[0].price_range_myr.status == "not_verified"
    assert rows[0].halal_status.status == "not_verified"

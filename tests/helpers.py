def restaurant(restaurant_id="fixture-1", **overrides):
    record = {
        "restaurant_id": restaurant_id,
        "name": "Fixture Cafe",
        "regions": ["old_klang_road", "kuala_lumpur"],
        "location_verified": False,
        "address": None,
        "price_range_myr": {"min": None, "max": None, "basis": "unknown", "status": "not_verified"},
        "halal_status": {"status": "not_verified", "source_url": None},
        "suitable_for_family": "not_verified",
        "sources": [
            {
                "source_name": "fixture",
                "source_url": "https://example.local/fixture",
                "collected_at": "2026-01-01T00:00:00+00:00",
                "fields": ["name"],
            }
        ],
    }
    record.update(overrides)
    return record

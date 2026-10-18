from food_copilot.ingestion.normalize import osm_record_to_restaurant
from food_copilot.ingestion.review_export import write_review_csv
from food_copilot.ingestion.validators import coordinate_diagnosis, split_valid, validate_restaurant

RAW = {
    "source": "OpenStreetMap",
    "source_id": "node/1",
    "source_url": "https://www.openstreetmap.org/node/1",
    "name": "Example Kopitiam",
    "amenity": "restaurant",
    "cuisine_raw": "malaysian;coffee",
    "address_raw": {"street": "Jalan Example", "city": None, "postcode": "09000"},
    "latitude": 5.37,
    "longitude": 100.56,
    "collected_at": "2026-10-09T00:00:00+00:00",
    "area_query": "Kulim",
}


def test_osm_row_does_not_invent_city_price_or_halal():
    record = osm_record_to_restaurant(RAW)
    assert record.city is None
    assert record.area_query == "Kulim"
    assert record.location_evidence == "area_query"
    assert record.location_verified is False
    assert record.price_range_myr.status == "not_verified"
    assert record.halal_status.status == "not_verified"
    assert "city" not in record.sources[0].fields
    assert record.restaurant_id == "MY-OSM-node-1"
    assert record.sources[0].license == "ODbL"
    assert validate_restaurant(record.model_dump()) == []


def test_south_cluster_is_diagnosed_and_kept_for_review(tmp_path):
    raw = {**RAW, "source_id": "node/9", "latitude": 0.47, "longitude": 101.50, "name": "南边食阁"}
    record = osm_record_to_restaurant(raw).model_dump()
    assert coordinate_diagnosis(record) == "second_area_named_kulim_near_0.47N_101.5E"
    kept, rejected = split_valid([record])
    assert kept == []
    assert rejected[0]["record"]["latitude"] == 0.47
    path = tmp_path / "restaurant_review.csv"
    write_review_csv([], rejected, path)
    text = path.read_text(encoding="utf-8")
    assert "南边食阁" in text
    assert "not_verified" in text
    assert "second_area_named_kulim" in text


def test_verified_halal_without_source_is_rejected():
    record = osm_record_to_restaurant(RAW).model_dump()
    record["halal_status"] = {"status": "verified", "source_url": None}
    assert "verified halal status has no source_url" in validate_restaurant(record)

from food_copilot.config.settings import RESTAURANTS_PATH
from food_copilot.data.repository import LocalRestaurantRepository


def test_canonical_file_keeps_ids_and_unverified_prices():
    repository = LocalRestaurantRepository(RESTAURANTS_PATH)
    report = repository.summary()
    assert report.loaded >= 5000
    assert report.skipped == 0
    row = repository.get_by_id("MY-OSM-node-10039928475")
    assert row is not None
    assert row["restaurant_id"] == "MY-OSM-node-10039928475"
    assert row["price_range_myr"]["status"] == "not_verified"
    assert row["halal_status"]["status"] == "not_verified"
    assert "reviewer_note" not in row

import json
from pathlib import Path

from food_copilot.data.repository import LocalRestaurantRepository
from tests.helpers import restaurant


def test_ids_are_preserved_and_duplicates_keep_the_first(tmp_path: Path):
    first = restaurant("same-id", name="First")
    second = restaurant("same-id", name="Second")
    path = tmp_path / "rows.json"
    path.write_text(json.dumps([first, second, "bad"]), encoding="utf-8")
    repository = LocalRestaurantRepository(path)
    assert repository.get_by_id("same-id")["name"] == "First"
    assert repository.summary().duplicate_ids == ["same-id"]
    assert repository.summary().skipped == 1
    assert not hasattr(repository, "save")


def test_invalid_status_is_skipped_not_coerced(tmp_path: Path):
    row = restaurant("bad-status")
    row["price_range_myr"] = {"status": "false", "max": 10}
    path = tmp_path / "rows.json"
    path.write_text(json.dumps([row]), encoding="utf-8")
    repository = LocalRestaurantRepository(path)
    assert repository.get_by_id("bad-status") is None
    assert repository.summary().loaded == 0


def test_repository_module_does_not_read_unapproved_staging():
    source = Path(__file__).resolve().parents[2] / "src" / "food_copilot" / "data" / "repository.py"
    text = source.read_text(encoding="utf-8")
    assert "okr_review_batch1_25_work" not in text
    assert "researched" not in text

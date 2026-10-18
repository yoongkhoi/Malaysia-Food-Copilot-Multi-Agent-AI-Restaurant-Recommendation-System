import json

from food_copilot.evaluation.runner import evaluate, format_summary
from food_copilot.ingestion.review_audit import importable_claims, validate_review_rows
from food_copilot.ingestion.validators import validate_restaurant
from food_copilot.services.discovery import DiscoveryService
from tests.helpers import restaurant

BASE = {
    "restaurant_id": "MY-OSM-node-1",
    "name": "Fixture Cafe",
    "latitude": "3.1",
    "longitude": "101.6",
    "regions": "old_klang_road|kuala_lumpur",
    "source_url": "https://www.openstreetmap.org/node/1",
    "location_evidence": "area_query",
    "source_type": "node",
    "location_verified": "false",
    "price_status": "not_verified",
    "price_source_url": "",
    "halal_status": "not_verified",
    "halal_source_url": "",
    "family_friendly": "not_verified",
    "review_status": "pending",
    "address": "",
    "address_evidence": "",
    "inclusion_note": "",
    "similar_name_note": "",
}


def _row(**changes):
    row = dict(BASE)
    row.update(changes)
    return row


def test_valid_reviewed_price_keeps_its_source():
    row = _row(
        review_status="reviewed",
        price_status="verified",
        price_max_myr="18",
        price_source_url="https://example.local/menu",
    )
    claims, issues = importable_claims(row)
    assert issues == []
    assert claims["price"]["source_url"] == "https://example.local/menu"


def test_verified_price_without_a_url_is_rejected():
    issues = validate_review_rows([_row(price_status="verified")], [BASE])
    assert any(issue.field == "price_source_url" for issue in issues)
    claims, blocked = importable_claims(_row(review_status="reviewed", price_status="verified"))
    assert claims == {}
    assert blocked


def test_verified_halal_without_a_url_is_rejected():
    issues = validate_review_rows([_row(halal_status="verified", halal_source_url="")], [BASE])
    assert any(issue.field == "halal_source_url" for issue in issues)


def test_address_for_a_different_branch_is_rejected():
    row = _row(
        location_verified="true",
        location_evidence="address",
        address_evidence="https://example.local/other-branch",
        inclusion_note="this page is a different branch",
    )
    issues = validate_review_rows([row], [{**BASE, "location_evidence": "address"}])
    assert any("different branch" in issue.reason for issue in issues)


def test_duplicate_and_reordered_ids_are_rejected():
    first = _row()
    second = _row(restaurant_id="MY-OSM-node-2")
    issues = validate_review_rows([first, first], [first, second])
    assert any(issue.reason == "duplicate restaurant_id" for issue in issues)
    assert any("order" in issue.reason for issue in issues)


def test_changed_osm_field_and_bad_status_are_rejected():
    changed = _row(name="Renamed", review_status="approved")
    issues = validate_review_rows([changed], [BASE])
    assert any(issue.field == "name" for issue in issues)
    assert any(issue.field == "review_status" for issue in issues)


def test_unreviewed_row_cannot_be_imported():
    claims, issues = importable_claims(BASE)
    assert claims == {}
    assert issues[0].field == "review_status"


def test_json_verified_price_and_halal_without_urls_are_rejected():
    record = restaurant("MY-OSM-node-1")
    record["price_range_myr"] = {"min": None, "max": 20, "basis": "unknown", "status": "verified"}
    record["halal_status"] = {"status": "verified", "source_url": None}
    record["location_verified"] = True
    errors = validate_restaurant(record)
    assert "verified price has no source_url" in errors
    assert "verified halal status has no source_url" in errors
    assert "location_verified has no premises source_url" in errors


def test_matching_price_source_passes_the_json_check():
    record = restaurant(
        "MY-OSM-node-1",
        price_range_myr={"min": 8, "max": 12, "basis": "per_person", "status": "verified"},
        price_source_url="https://example.local/menu",
    )
    assert "verified price has no source_url" not in validate_restaurant(record)


def test_unknown_relevance_ids_are_not_scored():
    service = DiscoveryService(records=[restaurant("known")])
    result = evaluate(service, [{
        "query": "Old Klang Road under RM20",
        "relevant_restaurant_ids": ["MY-OSM-node-missing"],
    }])
    assert result.metrics_computed is False
    assert result.labeled_queries == []
    assert result.unlabeled_queries[0]["metrics"] is None
    assert "Recall@5=" not in format_summary(result)


def test_canonical_files_are_not_required_by_the_fixture(tmp_path):
    path = tmp_path / "draft.json"
    path.write_text(json.dumps([restaurant("draft")]), encoding="utf-8")
    assert path.exists()

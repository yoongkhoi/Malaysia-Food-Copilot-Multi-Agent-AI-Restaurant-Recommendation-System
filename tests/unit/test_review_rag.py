import json

from food_copilot.reviews.metrics import ndcg_at, recall_at
from food_copilot.reviews.prepare import (
    extract_aspects,
    match_restaurant,
    normalize_name,
    parse_rating,
    prepare_reviews,
    review_id,
)
from food_copilot.reviews.retrieve import apply_hard_constraints, bm25_reviews, fuse_reviews


def test_rating_and_stable_id_and_negation():
    assert parse_rating("Rated 5.0 out of 5,") == 5.0
    assert parse_rating("Rated 9.0 out of 5,") is None
    assert parse_rating("") is None
    assert review_id("a.csv", "Ann", "Cafe", "5.0", "Tasty") == review_id("a.csv", "Ann", "Cafe", "5.0", "Tasty")
    noisy = extract_aspects("Bit noisy, but they do have a private room")
    assert noisy[0]["negated"] is False
    negated = extract_aspects("Wasnt too noisy and drinks were good.")
    assert negated[0]["negated"] is True


def test_prepare_drops_exact_duplicates_and_does_not_touch_canonical(tmp_path):
    source = tmp_path / "data" / "Malaysia Restaurant Review Datasets" / "data" / "review"
    google = source / "GoogleReview"
    tripadvisor = source / "TripAdvisor"
    google.mkdir(parents=True)
    tripadvisor.mkdir()
    (google / "GoogleReview_KL.csv").write_text(
        "Author,Review,Rating,Restaurant,Location\n"
        "Ann,\"Cozy lights and great service\",\"Rated 5.0 out of 5,\",Only Name,Jalan Example Kuala Lumpur\n"
        "Ann,\"Cozy lights and great service\",\"Rated 5.0 out of 5,\",Only Name,Jalan Example Kuala Lumpur\n"
        "Ben,\"Same words\",\"Rated 4.0 out of 5,\",Only Name,Jalan Example Kuala Lumpur\n"
        "Cara,\"Same words\",\"Rated 3.0 out of 5,\",Only Name,Jalan Example Kuala Lumpur\n",
        encoding="utf-8",
    )
    (tripadvisor / "reviews_all_KL.csv").write_text(
        "Author,Title,Review,Rating,Dates,Restaurant\n",
        encoding="utf-8",
    )
    canonical = tmp_path / "restaurants.json"
    canonical.write_text(json.dumps([
        {
            "restaurant_id": "canon-1",
            "name": "Only Name",
            "regions": ["kuala_lumpur", "old_klang_road"],
            "address": "Jalan Example",
            "cuisine": ["western"],
        }
    ]), encoding="utf-8")
    before = canonical.read_text(encoding="utf-8")
    report = prepare_reviews(tmp_path, tmp_path / "out", canonical, pilot_names={"Only Name"}, pilot_extra=0)
    assert report["exact_duplicates_removed"] == 1
    assert report["likely_duplicates_flagged"] == 1
    assert report["canonical_written"] is False
    assert canonical.read_text(encoding="utf-8") == before
    rows = [json.loads(line) for line in (tmp_path / "out" / "reviews.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 3
    assert rows[0]["restaurant_id"] == "canon-1"
    assert rows[0]["match_status"] == "unique_name_in_area"
    summary = [json.loads(line) for line in (tmp_path / "out" / "rating_summary.jsonl").read_text(encoding="utf-8").splitlines()]
    assert summary[0]["valid_deduped_reviews"] == 2
    assert summary[0]["average_rating"] == 4.5


def test_street_overlap_does_not_attach_a_branch():
    by_name = {
        normalize_name("ABC Bistro Cafe"): [
            {
                "restaurant_id": "addressed",
                "name": "ABC Bistro Cafe",
                "regions": ["kuala_lumpur"],
                "address": "Jalan Tun Sambanthan, 50470",
            },
            {
                "restaurant_id": "blank",
                "name": "ABC Bistro Cafe",
                "regions": ["kuala_lumpur"],
                "address": "",
            },
        ]
    }
    matched = match_restaurant(
        "ABC Bistro Cafe",
        "Petaling Jaya",
        "106, Jalan Tun Sambanthan, Brickfields, Kuala Lumpur",
        by_name,
    )
    assert matched["restaurant_id"] is None
    assert matched["match_status"] == "street_overlap_unconfirmed"
    assert matched["candidate_ids"][:2] == ["addressed", "blank"]


def test_generic_area_words_do_not_choose_a_branch():
    by_name = {
        normalize_name("Nando's"): [
            {"restaurant_id": "a", "name": "Nando's", "regions": ["kuala_lumpur"], "address": "Jalan Kuala Lumpur"},
            {"restaurant_id": "b", "name": "Nando's", "regions": ["kuala_lumpur"], "address": "Jalan Ampang"},
        ]
    }
    matched = match_restaurant("Nando's", "KL", "Kuala Lumpur", by_name)
    assert matched["restaurant_id"] is None
    assert matched["match_status"] == "ambiguous_branch"


def test_ambiguous_branch_is_not_attached():
    by_name = {
        normalize_name("KFC"): [
            {"restaurant_id": "kfc-1", "name": "KFC", "regions": ["kuala_lumpur"], "address": "Jalan One"},
            {"restaurant_id": "kfc-2", "name": "KFC", "regions": ["kuala_lumpur"], "address": "Jalan Two"},
        ]
    }
    matched = match_restaurant("KFC", "KL", "Kuala Lumpur", by_name)
    assert matched["match_status"] == "ambiguous_branch"
    assert matched["restaurant_id"] is None


def test_hybrid_dedup_and_western_constraint():
    cozy = {"review_id": "r1", "restaurant_id": "west-1", "restaurant_name": "Grill", "review_text": "cozy lights", "aspects": []}
    japanese = {"review_id": "r2", "restaurant_id": "jp-1", "restaurant_name": "Sushi", "review_text": "cozy sushi", "aspects": []}
    fused = fuse_reviews([cozy, japanese], [japanese, cozy], limit=10)
    assert [item["review_id"] for item in fused] == ["r1", "r2"]
    canonical = {
        "west-1": {"restaurant_id": "west-1", "name": "Grill", "cuisine": ["western"], "regions": ["kuala_lumpur"]},
        "jp-1": {"restaurant_id": "jp-1", "name": "Sushi", "cuisine": ["japanese"], "regions": ["kuala_lumpur"]},
    }
    kept, rejected = apply_hard_constraints(
        fused,
        {"cuisines": ["western"], "exclude_cuisines": ["japanese"], "region": "kuala_lumpur"},
        canonical,
    )
    assert [item["review_id"] for item in kept] == ["r1"]
    assert rejected[0]["constraint_block"] == "cuisine_excluded"
    ranked = bm25_reviews([cozy, japanese], "cozy lights", limit=1)
    assert ranked[0]["review_id"] == "r1"


def test_precision_uses_k_and_empty_labels_are_not_scored():
    from food_copilot.reviews.metrics import precision_at, recall_at

    assert precision_at(["a"], {"a"}, 5) == 0.2
    assert recall_at(["a"], set(), 5) is None


def test_mixed_quote_keeps_the_complaint_and_ambiguous_branches_are_not_quoted():
    from food_copilot.reviews.prepare import extract_aspects
    from food_copilot.reviews.retrieve import quote_span, select_quotable

    text = "Food is delicious but can be seasoned a bit too much resulting in being a bit too salty."
    doc = {
        "review_id": "mixed",
        "restaurant_id": "positano",
        "match_status": "unique_name_in_area",
        "review_text": text,
        "aspects": extract_aspects(text),
    }
    span = quote_span(doc)
    assert "delicious" in span
    assert "salty" in span
    ambiguous = {"review_id": "branch", "restaurant_id": None, "match_status": "ambiguous_branch", "review_text": "good"}
    street = {"review_id": "street", "restaurant_id": "osm", "match_status": "street_overlap_unconfirmed", "review_text": "good"}
    assert select_quotable([doc, ambiguous, street]) == [doc]


def test_reviewed_answer_fixtures_match_their_expected_failures():
    from pathlib import Path

    from food_copilot.reviews.faithfulness import check_answer

    path = Path(__file__).resolve().parents[2] / "data" / "eval" / "review_answer_cases.jsonl"
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(cases) == 9
    for case in cases:
        assert check_answer(case) == case["expected_failures"]


def test_rrf_promotes_a_document_found_by_both_lists_once():
    first = {"review_id": "a", "restaurant_id": None, "restaurant_name": "A", "review_text": "a", "aspects": []}
    second = {"review_id": "b", "restaurant_id": None, "restaurant_name": "B", "review_text": "b", "aspects": []}
    third = {"review_id": "c", "restaurant_id": None, "restaurant_name": "C", "review_text": "c", "aspects": []}
    fused = fuse_reviews([first, second], [first, third], limit=10)
    assert [item["review_id"] for item in fused] == ["a", "b", "c"]


def test_unsupported_area_message_and_session_exclusion_do_not_leak():
    from food_copilot.reviews.retrieve import limitation_message

    assert "kulim" in limitation_message({"region": "kulim"}, []).lower()
    doc = {"review_id": "r", "restaurant_id": "west-1", "restaurant_name": "Grill", "review_text": "cozy", "aspects": []}
    canonical = {"west-1": {"restaurant_id": "west-1", "name": "Grill", "cuisine": ["western"], "regions": ["kuala_lumpur"]}}
    kept, _rejected = apply_hard_constraints([doc], {"exclude_ids": ["west-1"]}, canonical)
    assert kept == []
    kept_again, _rejected_again = apply_hard_constraints([doc], {}, canonical)
    assert kept_again == [doc]


def test_review_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("ENABLE_REVIEW_RAG", raising=False)
    from food_copilot.config.settings import feature_flags

    assert feature_flags()["ENABLE_REVIEW_RAG"] is False

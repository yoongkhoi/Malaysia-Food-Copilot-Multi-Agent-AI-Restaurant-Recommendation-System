import json

import pytest

pytest.importorskip("chromadb")

from food_copilot.reviews.chroma_store import open_collection, query_documents, upsert_documents


def test_index_upsert_is_idempotent_and_keeps_source_metadata(tmp_path):
    docs = [
        {
            "review_id": "RV-1",
            "review_text": "cozy lights and quiet tables",
            "restaurant_id": "r-1",
            "restaurant_name": "Grill",
            "source": "google",
            "source_file": "GoogleReview_KL.csv",
            "rating": 5.0,
            "language": "en",
            "match_status": "unique_name_in_area",
            "source_city": "KL",
        }
    ]
    path = tmp_path / "restaurant_reviews"
    _client, first = open_collection(path, rebuild=False)
    assert upsert_documents(first, docs) == 1
    assert upsert_documents(first, docs) == 1
    assert first.count() == 1
    hits = query_documents(first, "cozy quiet restaurant", limit=1)
    assert hits[0]["review_id"] == "RV-1"
    assert hits[0]["source_file"] == "GoogleReview_KL.csv"
    meta = json.loads((path / "index_meta.json").read_text(encoding="utf-8"))
    assert meta["embedding_model"] == "all-MiniLM-L6-v2"

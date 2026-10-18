"""BM25, vector, and hybrid review retrieval. Ranking does not replace hard constraints."""

from __future__ import annotations

import json
from pathlib import Path

from food_copilot.retrieval.constraints import QueryConstraints, exclusion_code
from food_copilot.retrieval.rankers import BM25Retriever, reciprocal_rank_fusion

CANDIDATE_K = 20
FINAL_K = 10
VECTOR_MODEL = "all-MiniLM-L6-v2"
INDEX_VERSION = "reviews-chroma-v1"


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _as_rank_rows(docs: list[dict]) -> list[dict]:
    return [
        {
            "restaurant_id": doc["review_id"],
            "name": doc.get("restaurant_name") or "",
            "cuisine": [],
            "description": doc.get("review_text") or "",
        }
        for doc in docs
    ]


def bm25_reviews(docs: list[dict], query: str, limit: int = FINAL_K) -> list[dict]:
    if not docs:
        return []
    ranked = BM25Retriever().rank(_as_rank_rows(docs), query)
    by_id = {doc["review_id"]: doc for doc in docs}
    return [by_id[row["restaurant_id"]] for row in ranked[:limit] if row["restaurant_id"] in by_id]


def fuse_reviews(bm25_docs: list[dict], vector_docs: list[dict], limit: int = FINAL_K) -> list[dict]:
    by_id = {}
    for doc in [*bm25_docs, *vector_docs]:
        by_id[doc["review_id"]] = doc
    fused = reciprocal_rank_fusion([
        [doc["review_id"] for doc in bm25_docs],
        [doc["review_id"] for doc in vector_docs],
    ])
    return [by_id[item_id] for item_id in fused[:limit] if item_id in by_id]


def _canonical_block(record: dict | None, constraints: dict) -> str | None:
    if not record:
        return "insufficient_identity_evidence"
    checked = QueryConstraints(
        region=constraints.get("region"),
        cuisine=constraints.get("cuisine"),
        cuisines=list(constraints.get("cuisines") or []),
        exclude_cuisines=list(constraints.get("exclude_cuisines") or []),
        name_contains=constraints.get("name_contains"),
        exclude_brands=list(constraints.get("exclude_brands") or []),
    )
    return exclusion_code(record, checked)


def apply_hard_constraints(docs: list[dict], constraints: dict, canonical_by_id: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """Cuisine, area, and exclusions stay mandatory. A similar review cannot bypass them."""
    kept = []
    rejected = []
    needs_identity = bool(
        constraints.get("region")
        or constraints.get("cuisine")
        or constraints.get("cuisines")
        or constraints.get("exclude_cuisines")
        or constraints.get("name_contains")
    )
    excluded_ids = {str(item) for item in (constraints.get("exclude_ids") or [])}
    for doc in docs:
        restaurant_id = doc.get("restaurant_id")
        if restaurant_id and restaurant_id in excluded_ids:
            rejected.append({**doc, "constraint_block": "previously_recommended"})
            continue
        if needs_identity:
            block = _canonical_block(canonical_by_id.get(restaurant_id or ""), constraints)
            if block:
                rejected.append({**doc, "constraint_block": block})
                continue
        kept.append(doc)
    return kept, rejected


CONFIRMED_MATCH = {"unique_name_in_area"}
UNCONFIRMED_MATCH = {"ambiguous_branch", "street_overlap_unconfirmed", "unique_street"}


def select_quotable(docs: list[dict]) -> list[dict]:
    """Only a unique in-area name can be quoted as that canonical restaurant."""
    return [
        doc for doc in docs
        if doc.get("restaurant_id") and doc.get("match_status") in CONFIRMED_MATCH
    ]


def limitation_message(constraints: dict, kept: list[dict]) -> str | None:
    if kept:
        return None
    region = constraints.get("region")
    if region and region not in {"old_klang_road", "kuala_lumpur"}:
        return (
            f"{region} is not a supported canonical area, so no review was treated as a match there."
        )
    if constraints:
        return "Review evidence: no retrieved review satisfied the requested constraints."
    return None


def quote_span(doc: dict) -> str:
    """Keep the words around a lexicon hit so a following complaint is not cut off."""
    text = doc.get("review_text") or ""
    aspects = [item for item in doc.get("aspects") or [] if not item.get("negated")]
    if not aspects or not isinstance(aspects[0].get("start"), int):
        return text[:180]
    start = int(aspects[0]["start"])
    end = int(aspects[0].get("end") or start)
    return text[max(0, start - 40):min(len(text), end + 90)].strip()


def evidence_view(doc: dict) -> dict:
    return {
        "review_id": doc.get("review_id"),
        "restaurant_id": doc.get("restaurant_id"),
        "restaurant_name": doc.get("restaurant_name"),
        "source": doc.get("source"),
        "source_file": doc.get("source_file"),
        "rating": doc.get("rating"),
        "match_status": doc.get("match_status"),
        "span": quote_span(doc),
        "opinion_not_verified_fact": True,
    }

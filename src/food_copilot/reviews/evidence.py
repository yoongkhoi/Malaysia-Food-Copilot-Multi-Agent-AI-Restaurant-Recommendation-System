"""Attach a few review quotes to an answer. Quotes stay separate from canonical facts."""

from pathlib import Path

from food_copilot.config.settings import ROOT
from food_copilot.reviews.retrieve import (
    apply_hard_constraints,
    bm25_reviews,
    evidence_view,
    limitation_message,
    load_jsonl,
    select_quotable,
)


def append_review_evidence(payload: dict, query: str, constraints: dict, canonical_rows: list[dict]) -> None:
    path = ROOT / "data" / "processed" / "reviews" / "pilot_corpus.jsonl"
    if not path.exists():
        payload["answer"] = (payload.get("answer") or "") + "\nReview corpus is not prepared, so no review evidence was added."
        return
    docs = load_jsonl(path)
    ranked = bm25_reviews(docs, query, limit=20)
    by_id = {row.get("restaurant_id"): row for row in canonical_rows if row.get("restaurant_id")}
    kept, _rejected = apply_hard_constraints(ranked, constraints, by_id)
    quotable = select_quotable(kept)
    views = [evidence_view(doc) for doc in quotable[:3]]
    payload["review_evidence"] = views
    if not views and any(doc.get("match_status") in {"ambiguous_branch", "street_overlap_unconfirmed", "unique_street"} for doc in kept):
        line = "Review evidence does not identify one canonical branch, so no review was attached."
    else:
        limit = limitation_message(constraints, views)
        if limit and not views:
            line = limit
        elif not views:
            line = "Review evidence: no retrieved review satisfied the requested constraints."
        else:
            lines = ["Review opinions, not verified facts:"]
            for item in views:
                lines.append(
                    f"- {item['restaurant_name']} [{item['source_file']} {item['review_id']}, match {item['match_status']}]: {item['span']}"
                )
            line = "\n".join(lines)
    payload["answer"] = (payload.get("answer") or "") + "\n" + line

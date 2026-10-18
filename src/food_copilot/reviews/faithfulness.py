"""Deterministic checks for review-backed answers. These are not retrieval metrics."""

from __future__ import annotations

_ABSTAIN_MARKERS = (
    "no review",
    "not identify one canonical branch",
    "not a supported canonical area",
    "no retrieved review satisfied",
)


def check_answer(case: dict) -> list[str]:
    """Return failure names for one manually reviewed answer fixture."""
    evidence = {item["review_id"]: item for item in case.get("evidence") or []}
    failures = []
    answer = case.get("answer") or ""
    claims = case.get("claims") or []
    if case.get("expect_abstain"):
        if claims:
            failures.append("abstain_has_claims")
        if not any(marker in answer.lower() for marker in _ABSTAIN_MARKERS):
            failures.append("missing_abstain_message")
        return failures
    if "opinion" not in answer.lower():
        failures.append("opinion_not_labeled")
    for claim in claims:
        review = evidence.get(claim.get("review_id"))
        if review is None:
            failures.append("unsupported_claim")
            continue
        if claim.get("text") and claim["text"] not in (review.get("review_text") or ""):
            failures.append("claim_not_in_review")
        if claim.get("restaurant_id") and claim["restaurant_id"] != review.get("restaurant_id"):
            failures.append("wrong_branch")
        if review.get("match_status") != "unique_name_in_area" or not review.get("restaurant_id"):
            failures.append("unconfirmed_branch_used")
        if claim.get("presented_as") == "fact":
            failures.append("opinion_stated_as_fact")
        if claim.get("polarity") == "negative" and claim.get("presented_as") == "positive":
            failures.append("negative_flipped")
        if claim.get("polarity") == "mixed" and claim.get("presented_as") == "positive":
            failures.append("mixed_collapsed")
    return failures

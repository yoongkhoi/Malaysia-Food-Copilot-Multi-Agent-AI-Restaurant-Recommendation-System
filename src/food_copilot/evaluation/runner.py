"""Evaluate retrievers. Empty relevance labels are not scored."""

import json
from pathlib import Path

from food_copilot.config.settings import EVAL_QUERIES_PATH, EVAL_REPORT_DIR
from food_copilot.domain.models import EvaluationResult
from food_copilot.retrieval.constraints import exclusion_code
from food_copilot.retrieval.metrics import ndcg_at_k, recall_at_k
from food_copilot.services.discovery import DiscoveryService


def load_queries(path: Path | None = None) -> list[dict]:
    source = path or EVAL_QUERIES_PATH
    rows = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _violations(raw_results: list[dict], constraints) -> dict[str, int]:
    counts = {"budget": 0, "region": 0, "halal": 0}
    for record in raw_results:
        code = exclusion_code(record, constraints)
        if code in {"price_unverified", "price_over_budget"}:
            counts["budget"] += 1
        elif code in {"region_mismatch", "city_mismatch"}:
            counts["region"] += 1
        elif code == "halal_not_verified":
            counts["halal"] += 1
    return counts


def evaluate(service: DiscoveryService, queries: list[dict] | None = None) -> EvaluationResult:
    rows = load_queries() if queries is None else queries
    labeled = []
    unlabeled = []
    violations = {"budget": 0, "region": 0, "halal": 0}
    empty = 0
    clarifications = 0
    for query in rows:
        text = query.get("query") or ""
        labels = [item for item in (query.get("relevant_restaurant_ids") or []) if item]
        outcome = service.from_text(text)
        constraints = outcome["constraints_model"]
        raw_results = outcome.get("raw_results") or []
        found = _violations(raw_results, constraints)
        for key in violations:
            violations[key] += found[key]
        if outcome.get("needs_clarification"):
            clarifications += 1
        elif not raw_results:
            empty += 1
        known_ids = {record.get("restaurant_id") for record in service.repository.list_restaurants()}
        unknown_ids = [item for item in labels if item not in known_ids]
        if not labels or unknown_ids:
            unlabeled.append({
                "query": text,
                "eligible_count": len(raw_results),
                "metrics": None,
                "invalid_ids": unknown_ids,
            })
            continue
        ids = [record.get("restaurant_id") for record in raw_results]
        labeled.append(
            {
                "query": text,
                "recall_at_5": recall_at_k(ids, labels, k=5),
                "ndcg_at_5": ndcg_at_k(ids, labels, k=5),
            }
        )
    invalid = [item for item in unlabeled if item.get("invalid_ids")]
    if invalid and not labeled:
        note = "Retrieval metrics are not computed for queries whose relevant_restaurant_ids are empty or unknown."
    elif invalid:
        note = "Queries with unknown relevant_restaurant_ids were left unscored."
    elif not labeled:
        note = "Retrieval metrics are not computed because relevant_restaurant_ids are empty."
    else:
        note = ""
    return EvaluationResult(
        retriever=getattr(service.ranker, "name", "baseline"),
        dataset_records=len(service.repository.list_restaurants()),
        labeled_queries=labeled,
        unlabeled_queries=unlabeled,
        unlabeled_count=len(unlabeled),
        metrics_computed=bool(labeled),
        constraint_violations=violations,
        empty_result_queries=empty,
        clarification_queries=clarifications,
        note=note,
    )


def format_summary(result: EvaluationResult) -> str:
    lines = [
        f"Retriever: {result.retriever}",
        f"Dataset records: {result.dataset_records}",
        f"Labeled queries: {len(result.labeled_queries)}",
        f"Unlabeled queries: {result.unlabeled_count}",
        f"Empty eligible sets: {result.empty_result_queries}",
        f"Clarification requests: {result.clarification_queries}",
        f"Budget violations in returned results: {result.constraint_violations.get('budget', 0)}",
        f"Region violations in returned results: {result.constraint_violations.get('region', 0)}",
        f"Verified-halal violations in returned results: {result.constraint_violations.get('halal', 0)}",
    ]
    if result.metrics_computed:
        for item in result.labeled_queries:
            lines.append(
                f"- {item.query}: Recall@5={item.recall_at_5:.3f} NDCG@5={item.ndcg_at_5:.3f}"
            )
    else:
        lines.append(result.note)
    return "\n".join(lines)


def write_report(result: EvaluationResult, path: Path | None = None) -> Path:
    EVAL_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    target = path or (EVAL_REPORT_DIR / "latest.json")
    target.write_text(json.dumps(result.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    return target

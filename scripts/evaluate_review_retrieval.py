"""Compare BM25, vector, and hybrid on the same labeled cases. Does not call a paid judge."""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from food_copilot.config.settings import RESTAURANTS_PATH
from food_copilot.reviews.metrics import mrr, ndcg_at, percentile, precision_at, recall_at
from food_copilot.reviews.prepare import normalize_name
from food_copilot.reviews.retrieve import (
    CANDIDATE_K,
    FINAL_K,
    apply_hard_constraints,
    bm25_reviews,
    fuse_reviews,
    load_jsonl,
)

CASES = ROOT / "data" / "eval" / "review_retrieval_cases.jsonl"
CORPUS = ROOT / "data" / "processed" / "reviews" / "pilot_corpus.jsonl"
INDEX = ROOT / "data" / "vector_store" / "restaurant_reviews"
OUT = ROOT / "docs" / "experiments"


def _cases():
    rows = []
    with CASES.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


MIN_LABELS = 5
MULTI_INDEX = ROOT / "data" / "vector_store" / "restaurant_reviews_multilingual_minilm"
MULTI_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def _relevant(case: dict, docs: list[dict]) -> tuple[set[str], str, str]:
    mode = case.get("label_mode")
    if mode in {"constraints_only", "none_expected"}:
        return set(), "not_a_relevance_set", "constraint_case"
    if mode == "restaurant_names":
        wanted = {normalize_name(name) for name in case.get("restaurant_names") or []}
        found = {doc["review_id"] for doc in docs if normalize_name(doc.get("restaurant_name")) in wanted}
        status = "in_corpus" if found else "missing_corpus_evidence"
        return found, f"name_field n={len(found)}", status
    if mode == "review_ids":
        wanted = set(case.get("relevant_review_ids") or [])
        present = {doc["review_id"] for doc in docs if doc["review_id"] in wanted}
        missing = sorted(wanted - present)
        note = "manually_read_review_ids"
        if missing:
            note += "; absent " + ",".join(missing)
        return present, note, "in_corpus" if present else "missing_corpus_evidence"
    return set(), "unknown_label_mode", "not_scored"


def _failure(status: str, ranked_ids: list[str], relevant: set[str]) -> str:
    if status != "in_corpus":
        return status
    if set(ranked_ids[:FINAL_K]) & relevant:
        return "retrieved"
    return "retrieval_miss"


def _constraint_rate(docs: list[dict], constraints: dict, canonical: dict[str, dict]) -> float | None:
    if not constraints:
        return None
    if not docs:
        return 1.0
    kept, _rejected = apply_hard_constraints(docs, constraints, canonical)
    return len(kept) / len(docs)


def _summarize(rows: list[dict]) -> dict:
    def mean(name):
        return _mean(rows, name)

    categories = _by_category(rows)
    return {
        "cases": len(rows),
        "recall@5": mean("recall@5"),
        "recall@10": mean("recall@10"),
        "precision@5": mean("precision@5"),
        "precision@10": mean("precision@10"),
        "mrr": mean("mrr"),
        "ndcg@10": mean("ndcg@10"),
        "constraint_pass_rate": mean("constraint_pass_rate"),
        "evidence_availability": mean("evidence_availability"),
        "duplicate_restaurant_rate": mean("duplicate_restaurant_rate"),
        "aggregation": "macro_mean_per_query",
        "comparable_note": "comparable_categories_only keeps categories with at least 5 relevance labels",
        "null_metrics_excluded": True,
        "precision_denominator": "k",
        "latency_p50_ms": percentile([row["latency_ms"] for row in rows], 0.5),
        "latency_p95_ms": None if len(rows) < 20 else percentile([row["latency_ms"] for row in rows], 0.95),
        "latency_p95_reason": None if len(rows) >= 20 else "fewer than 20 queries",
        "per_category": categories,
        "comparable_categories_only": _mean_rows([
            row for row in rows
            if categories.get(row["category"], {}).get("conclusion") == "comparable"
        ]),
    }


def _by_category(rows: list[dict]) -> dict:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["category"], []).append(row)
    summary = {}
    for category, items in grouped.items():
        labels = sum(item["relevant_count"] for item in items)
        summary[category] = {
            "cases": len(items),
            "relevant_labels": labels,
            "conclusion": "comparable" if labels >= MIN_LABELS else "insufficient_labels",
            "recall@10": _mean(items, "recall@10"),
            "precision@10": _mean(items, "precision@10"),
            "mrr": _mean(items, "mrr"),
            "failure_classes": sorted({item["failure_class"] for item in items}),
        }
    return summary


def _mean_rows(rows: list[dict]) -> dict:
    return {
        "cases": len(rows),
        "recall@5": _mean(rows, "recall@5"),
        "recall@10": _mean(rows, "recall@10"),
        "precision@5": _mean(rows, "precision@5"),
        "precision@10": _mean(rows, "precision@10"),
        "mrr": _mean(rows, "mrr"),
        "ndcg@10": _mean(rows, "ndcg@10"),
    }


def _mean(rows: list[dict], name: str):
    values = [row[name] for row in rows if row.get(name) is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _score_mode(name: str, search, cases, docs, canonical):
    rows = []
    for case in cases:
        started = time.perf_counter()
        ranked = search(case["query"])
        elapsed = (time.perf_counter() - started) * 1000
        relevant, label_note, label_status = _relevant(case, docs)
        ids = [doc["review_id"] for doc in ranked]
        restaurant_ids = [doc.get("restaurant_id") for doc in ranked if doc.get("restaurant_id")]
        duplicate_rate = 0.0
        if restaurant_ids:
            duplicate_rate = 1 - (len(set(restaurant_ids)) / len(restaurant_ids))
        constraints = dict(case.get("constraints") or {})
        if case.get("label_mode") == "none_expected":
            kept, _rejected = apply_hard_constraints(ranked, constraints, canonical)
            constraint_rate = 1.0 if not kept else 0.0
        else:
            constraint_rate = _constraint_rate(ranked, constraints, canonical)
        rows.append({
            "case_id": case["case_id"],
            "category": case["category"],
            "label_note": label_note,
            "relevant_count": len(relevant),
            "failure_class": _failure(label_status, ids, relevant),
            "latency_ms": round(elapsed, 3),
            "recall@5": recall_at(ids, relevant, 5),
            "recall@10": recall_at(ids, relevant, 10),
            "precision@5": precision_at(ids, relevant, 5),
            "precision@10": precision_at(ids, relevant, 10),
            "mrr": mrr(ids, relevant),
            "ndcg@10": ndcg_at(ids, relevant, 10),
            "constraint_pass_rate": constraint_rate,
            "evidence_availability": (sum(1 for doc in ranked if doc.get("review_text")) / len(ranked)) if ranked else 0.0,
            "duplicate_restaurant_rate": round(duplicate_rate, 4),
            "top_review_ids": ids[:5],
        })
    return {"summary": _summarize(rows), "cases": rows}


def main() -> int:
    if not CORPUS.exists():
        print(f"Missing {CORPUS}")
        return 1
    docs = load_jsonl(CORPUS)
    canonical = {row["restaurant_id"]: row for row in json.loads(RESTAURANTS_PATH.read_text(encoding="utf-8"))}
    cases = _cases()
    vector_docs = None
    vector_error = None
    if INDEX.exists():
        try:
            from food_copilot.reviews.chroma_store import open_collection, query_documents

            collection = open_collection(INDEX, rebuild=False)[1]
            vector_docs = lambda query: query_documents(collection, query, CANDIDATE_K)  # noqa: E731
        except Exception as exc:
            vector_error = exc.__class__.__name__ + ": " + str(exc)
    else:
        vector_error = "index directory is absent"
    modes = {
        "bm25": lambda query: bm25_reviews(docs, query, FINAL_K),
    }
    if vector_docs is not None:
        modes["vector"] = lambda query: vector_docs(query)[:FINAL_K]
        modes["hybrid"] = lambda query: fuse_reviews(
            bm25_reviews(docs, query, CANDIDATE_K),
            vector_docs(query)[:CANDIDATE_K],
            FINAL_K,
        )
    multi_error = None
    if (MULTI_INDEX / "index_meta.json").exists():
        try:
            import chromadb
            from fastembed import TextEmbedding

            multi_client = chromadb.PersistentClient(path=str(MULTI_INDEX))
            multi_collection = multi_client.get_collection("restaurant_reviews_multilingual")
            multi_embedder = TextEmbedding(MULTI_MODEL)

            def multi_search(query: str):
                vector = next(iter(multi_embedder.embed([query]))).tolist()
                count = multi_collection.count()
                result = multi_collection.query(query_embeddings=[vector], n_results=min(FINAL_K, count), include=["documents", "metadatas"])
                found = []
                for review_id, text, meta in zip(result["ids"][0], result["documents"][0], result["metadatas"][0]):
                    meta = meta or {}
                    found.append({
                        "review_id": review_id,
                        "review_text": text or "",
                        "restaurant_id": meta.get("restaurant_id") or None,
                        "restaurant_name": meta.get("restaurant_name") or None,
                        "source_file": meta.get("source_file") or None,
                        "rating": None if meta.get("rating") in (-1, -1.0, None) else meta.get("rating"),
                    })
                return found

            modes["multilingual_minilm"] = multi_search
        except Exception as exc:
            multi_error = exc.__class__.__name__ + ": " + str(exc)
    else:
        multi_error = "multilingual index is absent"
    report = {
        "corpus_reviews": len(docs),
        "final_k": FINAL_K,
        "candidate_k": CANDIDATE_K,
        "aggregation": "macro_mean_per_query",
        "precision_denominator": "k",
        "min_labels_for_category_conclusion": MIN_LABELS,
        "modes": {},
    }
    for name, search in modes.items():
        report["modes"][name] = _score_mode(name, search, cases, docs, canonical)
    if "vector" not in modes:
        report["modes"]["vector"] = {"unavailable": vector_error}
        report["modes"]["hybrid"] = {"unavailable": vector_error}
    if "multilingual_minilm" not in modes:
        report["modes"]["multilingual_minilm"] = {"unavailable": multi_error}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "review_retrieval_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({name: value.get("summary") or value for name, value in report["modes"].items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

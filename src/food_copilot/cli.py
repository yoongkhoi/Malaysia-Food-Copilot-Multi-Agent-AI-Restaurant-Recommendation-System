"""Command line for validation, discovery, evaluation, and flags."""

import argparse
import json
import logging
import sys
from pathlib import Path

from food_copilot.agents.orchestrator import build_optional_graph, handle_message
from food_copilot.config.settings import EVAL_QUERIES_PATH, RESTAURANTS_PATH, ROOT, WORK_REVIEW_PATH, feature_flags
from food_copilot.data.repository import LocalRestaurantRepository
from food_copilot.errors import FeatureDisabled
from food_copilot.evaluation.runner import evaluate, format_summary, write_report
from food_copilot.services.discovery import DiscoveryService


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


def cmd_flags() -> int:
    print(json.dumps(feature_flags(), indent=2))
    return 0


def cmd_review_check() -> int:
    from food_copilot.ingestion.review_audit import load_review_csv, validate_review_rows

    baseline_path = ROOT / "data" / "staging" / "okr_review_batch1_25.csv"
    rows, _fields = load_review_csv(WORK_REVIEW_PATH)
    baseline, _baseline_fields = load_review_csv(baseline_path)
    issues = validate_review_rows(rows, baseline)
    print(f"work: {WORK_REVIEW_PATH}")
    print(f"baseline: {baseline_path}")
    print(f"issues: {len(issues)}")
    for issue in issues:
        print(issue.format())
    return 1 if issues else 0


def cmd_evidence_check(path: str | None = None) -> int:
    import json

    from food_copilot.ingestion.validators import validate_restaurant

    target = Path(path) if path else RESTAURANTS_PATH
    records = json.loads(target.read_text(encoding="utf-8"))
    issues = []
    for index, record in enumerate(records, start=1):
        for reason in validate_restaurant(record):
            if "source_url" in reason or reason.startswith("verified"):
                issues.append(f"record {index} {record.get('restaurant_id') or '-'} price/address/halal: {reason}")
    print(f"path: {target}")
    print(f"records: {len(records)}")
    print(f"evidence_issues: {len(issues)}")
    for line in issues[:30]:
        print(line)
    if len(issues) > 30:
        print(f"... {len(issues) - 30} more")
    return 1 if issues else 0


def cmd_validate() -> int:
    repository = LocalRestaurantRepository(RESTAURANTS_PATH)
    report = repository.summary()
    print(f"path: {report.path}")
    print(f"loaded: {report.loaded}")
    print(f"skipped: {report.skipped}")
    print(f"duplicate_ids: {len(report.duplicate_ids)}")
    for reason in report.reasons[:20]:
        print(f"reason: {reason}")
    return 1 if report.loaded == 0 else 0


def cmd_discover(query: str) -> int:
    outcome = handle_message(query)
    print(outcome["answer"])
    print("---")
    public = {
        "constraints": outcome["constraints"],
        "language": outcome.get("language"),
        "needs_clarification": outcome.get("needs_clarification"),
        "exclusion_counts": outcome.get("exclusion_counts"),
        "tools_called": outcome.get("tools_called"),
        "result_ids": [item["restaurant_id"] for item in outcome.get("results") or []],
    }
    print(json.dumps(public, ensure_ascii=False, indent=2))
    return 0


def cmd_evaluate() -> int:
    result = evaluate(DiscoveryService())
    print(format_summary(result))
    path = write_report(result)
    print(f"report: {path}")
    return 0


def cmd_graph() -> int:
    try:
        build_optional_graph()
    except FeatureDisabled as exc:
        print(exc)
        return 0
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    _configure_logging()
    parser = argparse.ArgumentParser(description="Malaysia Food Copilot")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("flags")
    sub.add_parser("validate")
    sub.add_parser("review-check")
    evidence = sub.add_parser("evidence-check")
    evidence.add_argument("path", nargs="?")
    discover = sub.add_parser("discover")
    discover.add_argument("query")
    sub.add_parser("evaluate")
    sub.add_parser("graph")
    args = parser.parse_args(argv)
    if args.command == "flags":
        return cmd_flags()
    if args.command == "validate":
        return cmd_validate()
    if args.command == "review-check":
        return cmd_review_check()
    if args.command == "evidence-check":
        return cmd_evidence_check(args.path)
    if args.command == "discover":
        return cmd_discover(args.query)
    if args.command == "evaluate":
        return cmd_evaluate()
    if args.command == "graph":
        return cmd_graph()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

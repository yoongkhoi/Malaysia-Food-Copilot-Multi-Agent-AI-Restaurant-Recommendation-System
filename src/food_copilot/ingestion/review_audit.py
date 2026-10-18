"""Check a review sheet against the baseline. This module does not write canonical data."""

import csv
from pathlib import Path

from food_copilot.ingestion.validators import _http_url

PROTECTED_FIELDS = (
    "restaurant_id",
    "name",
    "latitude",
    "longitude",
    "regions",
    "source_url",
    "location_evidence",
    "source_type",
)
REVIEW_STATUSES = {"pending", "reviewed", "needs_more_info"}
EVIDENCE_STATUSES = {"verified", "not_verified", "unknown"}
BRANCH_CONFLICT = ("different branch", "another branch", "wrong branch", "另一家", "不是这家")


class ReviewIssue:
    def __init__(self, line: int, restaurant_id: str, field: str, reason: str):
        self.line = line
        self.restaurant_id = restaurant_id
        self.field = field
        self.reason = reason

    def format(self) -> str:
        return f"line {self.line} {self.restaurant_id or '-'} {self.field}: {self.reason}"


def load_review_csv(path: Path) -> tuple[list[dict], list[str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def _line(index: int) -> int:
    return index + 2


def _flag(value: str) -> bool:
    return str(value or "").strip().lower() == "true"


def validate_review_rows(rows: list[dict], baseline: list[dict]) -> list[ReviewIssue]:
    issues: list[ReviewIssue] = []
    baseline_ids = [row.get("restaurant_id") or "" for row in baseline]
    row_ids = [row.get("restaurant_id") or "" for row in rows]
    baseline_by_id = {row.get("restaurant_id"): row for row in baseline}

    seen: set[str] = set()
    for index, restaurant_id in enumerate(row_ids):
        if not restaurant_id:
            issues.append(ReviewIssue(_line(index), "", "restaurant_id", "missing restaurant_id"))
            continue
        if restaurant_id in seen:
            issues.append(ReviewIssue(_line(index), restaurant_id, "restaurant_id", "duplicate restaurant_id"))
        seen.add(restaurant_id)
        if restaurant_id not in baseline_by_id:
            issues.append(ReviewIssue(_line(index), restaurant_id, "restaurant_id", "id is not in the baseline"))

    if row_ids != baseline_ids:
        issues.append(ReviewIssue(1, "", "restaurant_id", "row order or id set differs from the baseline"))

    for index, row in enumerate(rows):
        restaurant_id = row.get("restaurant_id") or ""
        original = baseline_by_id.get(restaurant_id)
        if original is not None:
            for field in PROTECTED_FIELDS:
                if field in row and field in original and (row.get(field) or "") != (original.get(field) or ""):
                    issues.append(ReviewIssue(_line(index), restaurant_id, field, "protected OSM field changed"))
        for field, allowed in (
            ("price_status", EVIDENCE_STATUSES),
            ("halal_status", EVIDENCE_STATUSES),
            ("family_friendly", EVIDENCE_STATUSES),
            ("review_status", REVIEW_STATUSES),
        ):
            value = (row.get(field) or "").strip()
            if value and value not in allowed:
                issues.append(ReviewIssue(_line(index), restaurant_id, field, f"unsupported status {value}"))
        if (row.get("price_status") or "").strip() == "verified" and not _http_url(row.get("price_source_url")):
            issues.append(ReviewIssue(_line(index), restaurant_id, "price_source_url", "verified price has no source URL"))
        if (row.get("halal_status") or "").strip() == "verified" and not _http_url(row.get("halal_source_url")):
            issues.append(ReviewIssue(_line(index), restaurant_id, "halal_source_url", "verified halal status has no source URL"))
        if _flag(row.get("location_verified") or ""):
            if (row.get("location_evidence") or "") != "address" or not _http_url(row.get("address_evidence")):
                issues.append(ReviewIssue(_line(index), restaurant_id, "address_evidence", "location_verified has no premises source URL"))
        note = " ".join([row.get("inclusion_note") or "", row.get("similar_name_note") or ""]).casefold()
        if _flag(row.get("location_verified") or "") and any(phrase in note for phrase in BRANCH_CONFLICT):
            issues.append(ReviewIssue(_line(index), restaurant_id, "address_evidence", "evidence is marked as a different branch"))
    return issues


def importable_claims(row: dict) -> tuple[dict, list[ReviewIssue]]:
    """Return only claims that already passed review. Unverified fields are omitted."""
    restaurant_id = row.get("restaurant_id") or ""
    if (row.get("review_status") or "").strip() != "reviewed":
        return {}, [ReviewIssue(0, restaurant_id, "review_status", "unreviewed row cannot be imported")]
    blocked = [
        issue
        for issue in validate_review_rows([row], [row])
        if issue.field != "restaurant_id"
    ]
    if blocked:
        return {}, blocked
    claims = {}
    if (row.get("price_status") or "").strip() == "verified":
        claims["price"] = {
            "min": row.get("price_min_myr") or None,
            "max": row.get("price_max_myr") or None,
            "status": "verified",
            "source_url": row.get("price_source_url"),
        }
    if (row.get("halal_status") or "").strip() == "verified":
        claims["halal"] = {"status": "verified", "source_url": row.get("halal_source_url")}
    if _flag(row.get("location_verified") or ""):
        claims["address"] = {"address": row.get("address") or "", "source_url": row.get("address_evidence")}
    return claims, []

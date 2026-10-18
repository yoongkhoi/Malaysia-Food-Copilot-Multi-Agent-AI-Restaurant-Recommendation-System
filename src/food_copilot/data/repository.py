"""Read-only restaurant store. Staging files are not imported."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from food_copilot.config.settings import active_restaurant_path
from food_copilot.data.schema import Restaurant
from food_copilot.domain.models import EVIDENCE_STATUSES, PRICE_STATUSES, EvidenceRecord

_DEFAULT = None


@dataclass
class LoadReport:
    path: str
    loaded: int = 0
    skipped: int = 0
    duplicate_ids: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def _status_ok(record: dict) -> str | None:
    price = (record.get("price_range_myr") or {}).get("status")
    halal = (record.get("halal_status") or {}).get("status")
    family = record.get("suitable_for_family")
    if price is not None and price not in PRICE_STATUSES:
        return f"price status {price!r} is not allowed"
    for label, value in (("halal", halal), ("family", family)):
        if value is not None and value not in EVIDENCE_STATUSES:
            return f"{label} status {value!r} is not allowed"
    return None


def index_records(records: list, path: str = "<memory>") -> tuple[dict[str, dict], LoadReport]:
    report = LoadReport(path=path)
    indexed: dict[str, dict] = {}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            report.skipped += 1
            report.reasons.append(f"row {index} is not an object")
            continue
        restaurant_id = record.get("restaurant_id")
        if not isinstance(restaurant_id, str) or not restaurant_id.strip():
            report.skipped += 1
            report.reasons.append(f"row {index} is missing restaurant_id")
            continue
        problem = _status_ok(record)
        if problem:
            report.skipped += 1
            report.reasons.append(f"{restaurant_id}: {problem}")
            continue
        try:
            dumped = Restaurant.model_validate(record).model_dump()
        except Exception as exc:
            report.skipped += 1
            report.reasons.append(f"{restaurant_id}: {exc}")
            continue
        if restaurant_id in indexed:
            report.duplicate_ids.append(restaurant_id)
            report.reasons.append(f"duplicate restaurant_id kept first: {restaurant_id}")
            continue
        indexed[restaurant_id] = dumped
        report.loaded += 1
    return indexed, report


def load_restaurant_file(path: Path) -> tuple[dict[str, dict], LoadReport]:
    if not path.exists():
        report = LoadReport(path=str(path))
        report.reasons.append("file does not exist")
        return {}, report
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        report = LoadReport(path=str(path))
        report.skipped += 1
        report.reasons.append("top-level JSON is not a list")
        return {}, report
    return index_records(payload, path=str(path))


def evidence_for(record: dict) -> list[EvidenceRecord]:
    items: list[EvidenceRecord] = []
    restaurant_id = record.get("restaurant_id") or ""
    for source in record.get("sources") or []:
        url = str(source.get("source_url") or "").strip()
        if not url:
            continue
        items.append(
            EvidenceRecord(
                restaurant_id=restaurant_id,
                claim="source_record",
                source_url=url,
                source_name=source.get("source_name"),
                collected_at=source.get("collected_at"),
            )
        )
    halal = record.get("halal_status") or {}
    halal_url = str(halal.get("source_url") or "").strip()
    if halal.get("status") == "verified" and halal_url:
        items.append(
            EvidenceRecord(
                restaurant_id=restaurant_id,
                claim="halal",
                source_url=halal_url,
                collected_at=halal.get("verified_at"),
            )
        )
    price = record.get("price_range_myr") or {}
    price_url = str(record.get("price_source_url") or "").strip()
    if price.get("status") == "verified" and price_url:
        items.append(
            EvidenceRecord(
                restaurant_id=restaurant_id,
                claim="price",
                source_url=price_url,
            )
        )
    return items


class LocalRestaurantRepository:
    def __init__(self, path: Path | None = None, records: list[dict] | None = None):
        if records is not None:
            self.path = None
            self._by_id, self.report = index_records(records)
        else:
            self.path = Path(path) if path is not None else active_restaurant_path()
            self._by_id, self.report = load_restaurant_file(self.path)
            from food_copilot.data.discoveries import load_discovered

            extra, extra_report = index_records(load_discovered(), path="discovered")
            for item_id, row in extra.items():
                if item_id not in self._by_id:
                    self._by_id[item_id] = row
                    self.report.loaded += 1
            self.report.skipped += extra_report.skipped
        self._order = sorted(self._by_id)

    def get_by_id(self, restaurant_id: str) -> dict | None:
        return self._by_id.get(restaurant_id)

    def list_restaurants(self) -> list[dict]:
        return [self._by_id[item_id] for item_id in self._order]

    def search_by_name(self, name: str, limit: int = 20) -> list[dict]:
        needle = (name or "").casefold().strip()
        if not needle:
            return []
        found = [
            row
            for row in self.list_restaurants()
            if needle in (row.get("name") or "").casefold()
        ]
        return found[:limit]

    def summary(self) -> LoadReport:
        return self.report


def get_default_repository() -> LocalRestaurantRepository:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = LocalRestaurantRepository()
    return _DEFAULT

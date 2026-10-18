"""Normalize review CSVs without editing the source files or canonical restaurants."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

_RATING = re.compile(r"(\d+(?:\.\d+)?)")
_RELATIVE_DATE = re.compile(r"yesterday|today|\bago\b|last week|reviewed", re.I)
_PUNCT = re.compile(r"[^a-z0-9\u4e00-\u9fff]+")
_LEADING_NUMBER = re.compile(r"^\d+\.\s*")
_MALAY = re.compile(r"\b(yang|dan|sangat|makan|sedap|tidak|dengan|untuk|ini|itu)\b", re.I)
_CJK = re.compile(r"[\u4e00-\u9fff]")
_LATIN = re.compile(r"[A-Za-z]")
_NEGATION = re.compile(r"\b(?:not|never|wasnt|wasn't|isnt|isn't|n't)\b", re.I)
_ASPECTS = (
    ("ambience_cozy", re.compile(r"\b(?:cozy|cosy|intimate|romantic)\b", re.I)),
    ("ambience_noisy", re.compile(r"\b(?:noisy|loud|crowded)\b", re.I)),
    ("food_positive", re.compile(r"\b(?:delicious|tasty)\b", re.I)),
    ("service_positive", re.compile(r"\b(?:great|excellent|friendly|warm) service\b|\bfriendly staff\b", re.I)),
)
_STREET = re.compile(r"[a-z0-9]{5,}")
_GENERIC_PLACE = {
    "jalan", "kuala", "lumpur", "federal", "territory", "malaysia",
    "street", "avenue",
}

DATASET_NOTE = (
    "No license file is shipped with data/Malaysia Restaurant Review Datasets. "
    "The files are scraped Google and TripAdvisor reviews. Public availability is not "
    "permission for unrestricted commercial reuse."
)


def dataset_root(root: Path) -> Path:
    return root / "data" / "Malaysia Restaurant Review Datasets"


def source_files(root: Path) -> list[tuple[str, str, Path]]:
    base = dataset_root(root)
    rows = []
    for path in sorted((base / "data" / "review" / "GoogleReview").glob("*.csv")):
        city = path.stem.replace("GoogleReview_", "")
        rows.append(("google", city, path))
    for path in sorted((base / "data" / "review" / "TripAdvisor").glob("*.csv")):
        city = path.stem.replace("reviews_all_", "")
        rows.append(("tripadvisor", city, path))
    return rows


def normalize_name(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    text = text.replace("’", "'").replace("`", "'")
    text = _LEADING_NUMBER.sub("", text)
    text = _PUNCT.sub(" ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def parse_rating(raw: str | None) -> float | None:
    match = _RATING.search(raw or "")
    if not match:
        return None
    value = float(match.group(1))
    if value < 1 or value > 5:
        return None
    return value


def classify_date(raw: str | None) -> tuple[str | None, str]:
    text = (raw or "").strip()
    if not text:
        return None, "missing"
    if _RELATIVE_DATE.search(text):
        return text, "relative_unreliable"
    return text, "raw_unparsed"


def detect_language(text: str) -> str:
    if _CJK.search(text):
        return "zh"
    if _MALAY.search(text):
        return "ms"
    if _LATIN.search(text):
        return "en"
    return "unknown"


def review_id(source_file: str, author: str, restaurant: str, rating_raw: str, text: str) -> str:
    blob = "\n".join([source_file, author.strip(), restaurant.strip(), rating_raw.strip(), text.strip()])
    return "RV-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def extract_aspects(text: str) -> list[dict]:
    found = []
    for name, pattern in _ASPECTS:
        for match in pattern.finditer(text):
            window = text[max(0, match.start() - 24):match.start()]
            negated = bool(_NEGATION.search(window))
            found.append({
                "aspect": name,
                "span": text[match.start():match.end()],
                "start": match.start(),
                "end": match.end(),
                "negated": negated,
                "method": "lexicon_v1",
                "confidence": 0.2 if negated else 0.35,
            })
    return found


def _area_compatible(city: str, location: str, record: dict) -> bool:
    regions = {str(item) for item in record.get("regions") or []}
    blob = f"{city} {location}".lower()
    if "kuala lumpur" in blob or city == "KL":
        return "kuala_lumpur" in regions
    return False


def _street_tokens(value: str) -> set[str]:
    """Distinctive street words. Area words such as jalan or kuala are not identity evidence."""
    return {
        token for token in _STREET.findall((value or "").lower())
        if not token.isdigit() and token not in _GENERIC_PLACE
    }


def match_restaurant(name: str, city: str, location: str, by_name: dict[str, list[dict]]) -> dict:
    hits = by_name.get(normalize_name(name), [])
    if not hits:
        return {"match_status": "unmatched", "match_confidence": 0.0, "restaurant_id": None, "candidate_ids": []}
    compatible = [row for row in hits if _area_compatible(city, location, row)]
    if not compatible:
        return {
            "match_status": "name_outside_area",
            "match_confidence": 0.0,
            "restaurant_id": None,
            "candidate_ids": [],
        }
    if len(compatible) == 1:
        return {
            "match_status": "unique_name_in_area",
            "match_confidence": 0.7,
            "restaurant_id": compatible[0].get("restaurant_id"),
            "candidate_ids": [compatible[0].get("restaurant_id")],
        }
    location_tokens = _street_tokens(location)
    street_hits = []
    for row in compatible:
        if location_tokens & _street_tokens(row.get("address") or ""):
            street_hits.append(row)
    if len(street_hits) == 1:
        # One overlapping street does not prove which branch the review describes.
        ordered = street_hits + [row for row in compatible if row not in street_hits]
        return {
            "match_status": "street_overlap_unconfirmed",
            "match_confidence": 0.0,
            "restaurant_id": None,
            "candidate_ids": [row.get("restaurant_id") for row in ordered[:5]],
        }
    return {
        "match_status": "ambiguous_branch",
        "match_confidence": 0.0,
        "restaurant_id": None,
        "candidate_ids": [row.get("restaurant_id") for row in compatible[:5]],
    }


def load_canonical_names(path: Path) -> dict[str, list[dict]]:
    records = json.loads(path.read_text(encoding="utf-8"))
    by_name: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        key = normalize_name(record.get("name"))
        if key:
            by_name[key].append(record)
    return by_name


def _row_text(row: dict) -> str:
    title = (row.get("Title") or "").strip()
    body = (row.get("Review") or "").strip()
    if title and body:
        return f"{title}\n{body}"
    return body or title


def prepare_reviews(root: Path, output_dir: Path, canonical_path: Path, pilot_names: set[str] | None = None, pilot_extra: int = 1500) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    by_name = load_canonical_names(canonical_path)
    seen_ids: set[str] = set()
    text_keys: dict[tuple[str, str], str] = {}
    stats = Counter()
    languages = Counter()
    match_counts = Counter()
    ratings = Counter()
    summary: dict[str, list[float]] = defaultdict(list)
    pilot_names = {normalize_name(name) for name in (pilot_names or set())}
    pilot_extra_left = pilot_extra
    reviews_path = output_dir / "reviews.jsonl"
    pilot_path = output_dir / "pilot_corpus.jsonl"
    summary_path = output_dir / "rating_summary.jsonl"
    with reviews_path.open("w", encoding="utf-8") as reviews, pilot_path.open("w", encoding="utf-8") as pilot:
        for source, city, path in source_files(root):
            with path.open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    stats["rows_read"] += 1
                    text = _row_text(row)
                    if not text:
                        stats["empty_text"] += 1
                        continue
                    author = (row.get("Author") or "").strip()
                    restaurant = (row.get("Restaurant") or "").strip()
                    rating_raw = (row.get("Rating") or "").strip()
                    location = (row.get("Location") or "").strip()
                    identifier = review_id(path.name, author, restaurant, rating_raw, text)
                    if identifier in seen_ids:
                        stats["exact_duplicates_removed"] += 1
                        continue
                    seen_ids.add(identifier)
                    text_key = (normalize_name(restaurant), re.sub(r"\s+", " ", text.lower()).strip())
                    likely = text_key in text_keys
                    if likely:
                        stats["likely_duplicates_flagged"] += 1
                    else:
                        text_keys[text_key] = identifier
                    rating = parse_rating(rating_raw)
                    ratings["parsed" if rating is not None else "missing_or_invalid"] += 1
                    date_raw, date_status = classify_date(row.get("Dates"))
                    language = detect_language(text)
                    languages[language] += 1
                    matched = match_restaurant(restaurant, city, location, by_name)
                    match_counts[matched["match_status"]] += 1
                    if matched["restaurant_id"] and rating is not None and not likely:
                        summary[matched["restaurant_id"]].append(rating)
                    record = {
                        "review_id": identifier,
                        "restaurant_id": matched["restaurant_id"],
                        "candidate_ids": matched["candidate_ids"],
                        "restaurant_name": restaurant or None,
                        "review_text": text,
                        "rating": rating,
                        "rating_raw": rating_raw or None,
                        "review_date": date_raw,
                        "date_status": date_status,
                        "source": source,
                        "source_file": path.name,
                        "source_city": city,
                        "location_text": location or None,
                        "author": author or None,
                        "language": language,
                        "language_method": "script_and_function_word_heuristic",
                        "match_status": matched["match_status"],
                        "match_confidence": matched["match_confidence"],
                        "aspects": extract_aspects(text),
                        "likely_duplicate": likely,
                    }
                    reviews.write(json.dumps(record, ensure_ascii=False) + "\n")
                    stats["reviews_written"] += 1
                    named = normalize_name(restaurant) in pilot_names
                    if city == "KL" and (named or pilot_extra_left > 0):
                        pilot.write(json.dumps(record, ensure_ascii=False) + "\n")
                        stats["pilot_written"] += 1
                        if not named:
                            pilot_extra_left -= 1
    with summary_path.open("w", encoding="utf-8") as handle:
        for restaurant_id, values in sorted(summary.items()):
            handle.write(json.dumps({
                "restaurant_id": restaurant_id,
                "valid_deduped_reviews": len(values),
                "average_rating": round(sum(values) / len(values), 3),
                "display_ok": len(values) >= 5,
                "coverage_note": "Average of matched, deduplicated reviews in this dataset only. It is not every customer.",
            }, ensure_ascii=False) + "\n")
    report = {
        "license_note": DATASET_NOTE,
        "source_files": [path.name for _source, _city, path in source_files(root)],
        "cleaned_files_not_used": [
            "data_cleaned/GoogleReview_data_cleaned.csv",
            "data_cleaned/TripAdvisor_data_cleaned.csv",
        ],
        "rows_read": stats["rows_read"],
        "empty_text": stats["empty_text"],
        "exact_duplicates_removed": stats["exact_duplicates_removed"],
        "likely_duplicates_flagged": stats["likely_duplicates_flagged"],
        "reviews_written": stats["reviews_written"],
        "pilot_written": stats["pilot_written"],
        "ratings": dict(ratings),
        "languages": dict(languages),
        "match_status": dict(match_counts),
        "matched_restaurants_with_ratings": len(summary),
        "canonical_written": False,
    }
    (output_dir / "quality_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report

"""Search verified fields first. Semantic rank never overrides a hard constraint."""

import json

from food_copilot.config.settings import RESTAURANTS_PATH
from food_copilot.retrieval.constraints import QueryConstraints, apply_constraints, parse_constraints


def load_restaurants(path=RESTAURANTS_PATH) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def explain(constraints: QueryConstraints, buckets) -> str:
    parts = []
    if constraints.region:
        parts.append(
            f"Area filter: {constraints.region}. "
            "This only means the coordinate is inside the defined query area. It does not verify the street address."
        )
    if constraints.city:
        parts.append(f"City filter: {constraints.city}.")
    if constraints.max_budget_myr is not None:
        parts.append(f"Budget cap: RM{constraints.max_budget_myr:g} per stated basis. Higher prices are excluded.")
    if not buckets.matching:
        parts.append("No record satisfies every verified constraint.")
    else:
        parts.append(f"{len(buckets.matching)} record(s) satisfy the verified constraints.")
    if buckets.price_unknown:
        parts.append(
            f"{len(buckets.price_unknown)} place(s) match the location but have unknown price, so they are not budget matches."
        )
    if buckets.city_unverified:
        parts.append(
            f"{len(buckets.city_unverified)} OSM place(s) were collected inside the {constraints.city} area, but the city field is unverified."
        )
    if constraints.require_halal_verified:
        parts.append(
            f"Halal verified: {len(buckets.matching)}. "
            f"Not shown as certified: {len(buckets.halal_unverified)}. "
            "not_verified means not checked yet. unknown means the sources still do not prove certification. Neither means non-halal."
        )
    if constraints.family:
        parts.append("Family-friendly is unknown unless a record says verified. It is not treated as false.")
    return " ".join(parts)


def discover(query: str, records: list[dict] | None = None) -> dict:
    constraints = parse_constraints(query)
    rows = load_restaurants() if records is None else records
    buckets = apply_constraints(rows, constraints)
    return {
        "answer": explain(constraints, buckets),
        "constraints": constraints.model_dump(),
        "results": buckets.matching,
        "price_unknown": buckets.price_unknown,
        "city_unverified": buckets.city_unverified,
        "halal_unverified": buckets.halal_unverified,
        "sources_note": "Shown facts come from each record's sources. Unverified fields stay unknown.",
    }

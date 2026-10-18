"""Turn an OSM raw snapshot into canonical records. Does not invent missing facts."""

from food_copilot.data.schema import HalalStatus, PriceRange, Restaurant, Source


def _address(raw: dict) -> str | None:
    parts = raw.get("address_raw") or {}
    line = ", ".join(part for part in (parts.get("street"), parts.get("postcode")) if part)
    return line or None


def _city_is_kulim(city: str | None) -> bool:
    key = " ".join((city or "").lower().replace(",", " ").split())
    return key == "kulim" or key.startswith("kulim ")


def osm_record_to_restaurant(raw: dict) -> Restaurant:
    city = (raw.get("address_raw") or {}).get("city")
    cuisine_raw = raw.get("cuisine_raw")
    cuisine = [part.strip() for part in cuisine_raw.split(";") if part.strip()] if cuisine_raw else []
    source_id = str(raw["source_id"]).replace("/", "-")
    sourced_fields = ["name", "amenity", "latitude", "longitude", "cuisine_raw", "address_raw", "area_query"]
    if city:
        sourced_fields.append("city")
    regions = list(raw.get("regions") or [])
    return Restaurant(
        restaurant_id=f"MY-OSM-{source_id}",
        name=raw.get("name"),
        state="Kedah" if _city_is_kulim(city) else None,
        city=city,
        area_query=raw.get("area_query"),
        regions=regions,
        location_evidence="address" if city else "area_query",
        location_verified=False,
        address=_address(raw),
        latitude=raw.get("latitude"),
        longitude=raw.get("longitude"),
        cuisine=cuisine,
        cuisine_raw=cuisine_raw,
        price_range_myr=PriceRange(status="not_verified"),
        suitable_for_family="not_verified",
        halal_status=HalalStatus(status="not_verified"),
        description=None,
        sources=[
            Source(
                source_name="OpenStreetMap",
                source_url=raw["source_url"],
                license="ODbL",
                collected_at=raw["collected_at"],
                fields=sourced_fields,
            )
        ],
        record_status="needs_review",
    )


def merge_raw_records(records: list[dict]) -> list[dict]:
    """Same OSM type and id is one place, even if two region snapshots include it."""
    merged: dict[str, dict] = {}
    for raw in records:
        source_id = raw.get("source_id")
        if not source_id:
            continue
        current = merged.get(source_id)
        if current is None:
            merged[source_id] = dict(raw)
            continue
        regions = list(dict.fromkeys((current.get("regions") or []) + (raw.get("regions") or [])))
        current["regions"] = regions
    return list(merged.values())


def normalize_osm_snapshot(records: list[dict]) -> list[Restaurant]:
    restaurants = [osm_record_to_restaurant(raw) for raw in merge_raw_records(records)]
    restaurants.sort(key=lambda item: item.restaurant_id)
    return restaurants

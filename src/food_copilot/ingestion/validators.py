"""Quality checks. A failed check keeps the row out of the canonical file."""

MALAYSIA_LAT = (0.8, 7.6)
MALAYSIA_LON = (99.0, 119.5)


def _http_url(value) -> bool:
    text = str(value or "").strip()
    return text.startswith("https://") or text.startswith("http://")


def _price_source_url(record: dict) -> str:
    direct = str(record.get("price_source_url") or "").strip()
    if _http_url(direct):
        return direct
    for source in record.get("sources") or []:
        fields = set(source.get("fields") or [])
        if fields.intersection({"price", "price_range_myr", "price_max_myr"}) and _http_url(source.get("source_url")):
            return str(source.get("source_url")).strip()
    return ""


def _address_source_url(record: dict) -> str:
    direct = str(record.get("address_evidence") or "").strip()
    if _http_url(direct):
        return direct
    for source in record.get("sources") or []:
        fields = set(source.get("fields") or [])
        if "address" in fields and _http_url(source.get("source_url")):
            return str(source.get("source_url")).strip()
    return ""


def validate_restaurant(record: dict) -> list[str]:
    errors = []
    if not record.get("restaurant_id"):
        errors.append("missing restaurant_id")
    if not record.get("sources"):
        errors.append("missing sources")
    lat = record.get("latitude")
    lon = record.get("longitude")
    if lat is None or lon is None:
        errors.append("missing coordinates")
    else:
        if not (MALAYSIA_LAT[0] <= float(lat) <= MALAYSIA_LAT[1]):
            errors.append("latitude outside Malaysia bounds")
        if not (MALAYSIA_LON[0] <= float(lon) <= MALAYSIA_LON[1]):
            errors.append("longitude outside Malaysia bounds")
    price = (record.get("price_range_myr") or {})
    for key in ("min", "max"):
        value = price.get(key)
        if value is not None and float(value) < 0:
            errors.append(f"negative price {key}")
    halal_record = record.get("halal_status") or {}
    halal = halal_record.get("status")
    if halal == "verified" and not _http_url(halal_record.get("source_url")):
        errors.append("verified halal status has no source_url")
    if price.get("status") == "verified" and not _price_source_url(record):
        errors.append("verified price has no source_url")
    location_verified = record.get("location_verified")
    if location_verified is True or str(location_verified).strip().lower() == "true":
        if record.get("location_evidence") != "address" or not _address_source_url(record):
            errors.append("location_verified has no premises source_url")
    return errors


def coordinate_diagnosis(record: dict) -> str | None:
    """Explain an out-of-bounds point. The raw record is kept either way."""
    lat = record.get("latitude")
    lon = record.get("longitude")
    if lat is None or lon is None:
        return "missing_coordinates"
    lat, lon = float(lat), float(lon)
    # A tight cluster south of Peninsular Malaysia. Not a swapped lat/lon:
    # longitude stays near 101.5, which is a valid longitude.
    if 0.40 <= lat <= 0.60 and 101.40 <= lon <= 101.60:
        return "second_area_named_kulim_near_0.47N_101.5E"
    if not (MALAYSIA_LAT[0] <= lat <= MALAYSIA_LAT[1] and MALAYSIA_LON[0] <= lon <= MALAYSIA_LON[1]):
        return "outside_malaysia_bounds"
    return None


def split_valid(records: list[dict]) -> tuple[list[dict], list[dict]]:
    kept, rejected = [], []
    for record in records:
        errors = validate_restaurant(record)
        if errors:
            rejected.append({
                "restaurant_id": record.get("restaurant_id"),
                "errors": errors,
                "diagnosis": coordinate_diagnosis(record),
                "record": record,
            })
        else:
            kept.append(record)
    return kept, rejected

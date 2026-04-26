"""
Scrape STR-oriented Coachella Valley ZIP codes for single-family homes.

Modes:
- incremental (default): fetch previous-day window, append only new property_id rows
  into combined outputs.
- full: refresh per-ZIP exports and rebuild combined outputs.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Optional

import pandas as pd
from homeharvest import scrape_property

from str_enrichment import enrich_with_palm_springs_str_neighborhoods
from str_neighborhood_summary import build_neighborhood_zip_table

STR_FRIENDLY_ZIP_CODES = [
    "92258",  # North Palm Springs (Palm Springs)
    "92262",
    "92263",
    "92264",
    "92201",  # Indio
    "92202",  # Indio
    "92203",  # Indio / Bermuda Dunes postal area
]

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SUMMARY_PATH = PROJECT_ROOT / "regulation_data" / "Vacation Rental_Housing_All_Summary 4.9.26.xlsx"
CROSSWALK_PATH = SCRIPT_DIR / "data" / "palm_springs_organized_neighborhood_zips.csv"
ALIASES_PATH = SCRIPT_DIR / "data" / "palm_springs_neighborhood_aliases.json"
OUTPUT_DIR = SCRIPT_DIR / "zips"
COMBINED_XLSX_PATH = OUTPUT_DIR / "combined.xlsx"
COMBINED_CSV_PATH = OUTPUT_DIR / "combined.csv"

HOME_PROPERTY_TYPES = ["single_family"]
MIN_VALID_HOME_PRICE = 100000
POOL_DETECTION_COLUMNS = (
    "pool",
    "has_pool",
    "private_pool",
    "pool_private",
    "pool_features",
    "amenities",
    "description",
    "remarks",
    "features",
)
POOL_KEYWORDS = (" pool ", "swimming pool", "spa", "hot tub", "plunge pool")
POOL_PRIVATE_KEYWORDS = ("private", "pool private: yes", "private pool")
POOL_COMMUNITY_KEYWORDS = ("community", "shared", "hoa pool", "community pool", "community swimming pool")
POOL_GENERIC_KEYWORDS = ("pool", "swimming_pool", "swimming pool", "spa", "hot tub", "above_ground_pool")
POOL_DETAIL_CATEGORY_KEYWORDS = ("pool", "spa", "exterior")
ADDRESS_EXCLUDE_KEYWORDS = (
    "mobile",
    "manufactured",
    "trailer",
    "rv ",
    " motorhome",
    " coach",
    "space ",
    " lot ",
)
CO_OWNERSHIP_KEYWORDS = (
    "co-ownership",
    "co ownership",
    "fractional",
    "timeshare",
    "shared ownership",
    "tic",
)
UNIT_ADDRESS_TOKENS = ("unit", "apt", "apartment", "suite", "ste", "#", "lot", "space", "spc")

# Manual co-ownership exclusions.
# Add known co-ownership/fractional addresses or property_ids here when they
# cannot be detected reliably from listing metadata.
MANUAL_EXCLUDED_PROPERTY_IDS = {
    "1086968872",  # 470 E Avenida Olancha, Palm Springs, CA 92264
}
MANUAL_EXCLUDED_ADDRESSES = {
    ("470 e avenida olancha", "palm springs", "ca", "92264"),
}

# (listing_type, past_days) for full mode.
LISTING_SCRAPES: tuple[tuple[str, Optional[int]], ...] = (
    ("for_sale", None),
    ("pending", 365),
    ("sold", 365),
)

LISTING_TYPES_INCREMENTAL = ("for_sale",)
LA_TIMEZONE = "America/Los_Angeles"

STATUS_PRIORITY = {
    "SOLD": 3,
    "PENDING": 2,
    "CONTINGENT": 2,
    "FOR_SALE": 1,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export STR-oriented HomeHarvest datasets")
    parser.add_argument("--mode", choices=["incremental", "full"], default="incremental")
    parser.add_argument(
        "--run-date",
        help="Anchor date (YYYY-MM-DD) used for default incremental window. Default is local today.",
    )
    parser.add_argument("--date-from", help="Optional override start datetime/date (ISO 8601).")
    parser.add_argument("--date-to", help="Optional override end datetime/date (ISO 8601).")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=3,
        help="Incremental reliability window when no explicit dates are provided (default: 3).",
    )
    return parser.parse_args()


def _normalize_property_id(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _normalize_status(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip().upper()


def _contains_excluded_address_keyword(street: object) -> bool:
    if street is None or (isinstance(street, float) and pd.isna(street)):
        return False
    value = f" {str(street).strip().lower()} "
    return any(keyword in value for keyword in ADDRESS_EXCLUDE_KEYWORDS)


def _address_key(row: pd.Series) -> tuple[str, str, str, str]:
    return (
        str(row.get("street", "")).strip().lower(),
        str(row.get("city", "")).strip().lower(),
        str(row.get("state", "")).strip().lower(),
        str(row.get("zip_code", "")).strip(),
    )


def _is_manually_excluded_listing(row: pd.Series) -> bool:
    property_id = _normalize_property_id(row.get("property_id"))
    if property_id and property_id in MANUAL_EXCLUDED_PROPERTY_IDS:
        return True
    return _address_key(row) in MANUAL_EXCLUDED_ADDRESSES


def _contains_co_ownership_keyword(value: object) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    normalized = f" {str(value).strip().lower()} "
    return any(keyword in normalized for keyword in CO_OWNERSHIP_KEYWORDS)


def _has_unit_designator(street: object) -> bool:
    if street is None or (isinstance(street, float) and pd.isna(street)):
        return False
    normalized = str(street).strip().lower()
    return any(token in normalized for token in UNIT_ADDRESS_TOKENS)


def _looks_like_variant_share_listing(street: object, property_url: object) -> bool:
    if street is None or property_url is None:
        return False
    if (isinstance(street, float) and pd.isna(street)) or (isinstance(property_url, float) and pd.isna(property_url)):
        return False

    street_text = str(street).strip().lower()
    url_text = str(property_url).strip().lower()
    marker = "/realestateandhomes-detail/"
    if marker not in url_text:
        return False
    slug = url_text.split(marker, 1)[1].split("_", 1)[0]

    street_slug = re.sub(r"[^a-z0-9]+", "-", street_text).strip("-")
    if not street_slug or not slug.startswith(f"{street_slug}-"):
        return False
    if _has_unit_designator(street_text):
        return False

    suffix = slug[len(street_slug) + 1 :]
    if not suffix:
        return False
    # Realtor slugs that append a short token (e.g. -3 / -4 / -1-8) to an otherwise
    # non-unit address often represent co-ownership/fractional variants.
    return bool(re.fullmatch(r"[a-z0-9-]{1,8}", suffix))


def _is_co_ownership_listing(row: pd.Series) -> bool:
    street = row.get("street")
    property_url = row.get("property_url")
    return (
        _contains_co_ownership_keyword(street)
        or _contains_co_ownership_keyword(property_url)
        or _looks_like_variant_share_listing(street, property_url)
    )


def is_valid_home_listing(row: pd.Series, min_price: int = MIN_VALID_HOME_PRICE) -> bool:
    price = pd.to_numeric(row.get("list_price"), errors="coerce")
    beds = pd.to_numeric(row.get("beds"), errors="coerce")
    baths = pd.to_numeric(row.get("full_baths"), errors="coerce")
    sqft = pd.to_numeric(row.get("sqft"), errors="coerce")

    if pd.notna(price) and float(price) < float(min_price):
        return False
    if _is_manually_excluded_listing(row):
        return False
    if _contains_excluded_address_keyword(row.get("street")):
        return False
    if _is_co_ownership_listing(row):
        return False

    # Drop records that look like lots/mobile-space entries with no usable home specs.
    if pd.isna(beds) and pd.isna(baths) and pd.isna(sqft):
        return False

    return True


def filter_home_listings(df: pd.DataFrame, min_price: int = MIN_VALID_HOME_PRICE) -> pd.DataFrame:
    if df.empty:
        return df
    return df[df.apply(lambda row: is_valid_home_listing(row, min_price=min_price), axis=1)].copy()


def _normalize_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip().lower()


def _safe_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = _normalize_text(value)
    if text in {"true", "yes", "1", "y", "t"}:
        return True
    if text in {"false", "no", "0", "n", "f"}:
        return False
    return None


def _json_list(value: object) -> list:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _update_pool_signals_from_text(text: str, signals: dict[str, bool], evidence: list[str]) -> None:
    normalized = f" {text.strip().lower()} "
    if not normalized.strip():
        return
    if any(keyword in normalized for keyword in POOL_GENERIC_KEYWORDS):
        signals["generic"] = True
    if any(keyword in normalized for keyword in POOL_PRIVATE_KEYWORDS):
        signals["private"] = True
    if any(keyword in normalized for keyword in POOL_COMMUNITY_KEYWORDS):
        signals["community"] = True
    if "pool private:" in normalized and "yes" in normalized:
        signals["explicit_private_yes"] = True
    if "pool private:" in normalized and "no" in normalized:
        signals["explicit_private_no"] = True
    if any(keyword in normalized for keyword in POOL_GENERIC_KEYWORDS):
        evidence.append(text.strip())


def _extract_pool_mapping(row: pd.Series) -> dict[str, object]:
    signals = {
        "explicit_private_yes": False,
        "explicit_private_no": False,
        "private": False,
        "community": False,
        "generic": False,
    }
    evidence: list[str] = []
    sources: list[str] = []

    # Track where each signal was observed so we can apply an evidence ladder.
    private_sources: set[str] = set()
    community_sources: set[str] = set()
    explicit_yes_sources: set[str] = set()
    explicit_no_sources: set[str] = set()

    # Layer 1: details[] (highest trust)
    details_rows = _json_list(row.get("raw_details"))
    for detail in details_rows:
        if not isinstance(detail, dict):
            continue
        category = _normalize_text(detail.get("category"))
        parent_category = _normalize_text(detail.get("parent_category"))
        if not any(token in category or token in parent_category for token in POOL_DETAIL_CATEGORY_KEYWORDS):
            continue
        text_values = detail.get("text")
        if isinstance(text_values, list):
            iter_values = text_values
        elif text_values:
            iter_values = [text_values]
        else:
            iter_values = []
        for value in iter_values:
            text = str(value)
            before = signals.copy()
            _update_pool_signals_from_text(text, signals, evidence)
            sources.append("details")
            if signals["private"] and not before["private"]:
                private_sources.add("details")
            if signals["community"] and not before["community"]:
                community_sources.add("details")
            if signals["explicit_private_yes"] and not before["explicit_private_yes"]:
                explicit_yes_sources.add("details")
            if signals["explicit_private_no"] and not before["explicit_private_no"]:
                explicit_no_sources.add("details")

    # Layer 2: tags[]
    for tag in _json_list(row.get("raw_tags")):
        text = str(tag).replace("_", " ")
        before = signals.copy()
        _update_pool_signals_from_text(text, signals, evidence)
        sources.append("tags")
        if signals["private"] and not before["private"]:
            private_sources.add("tags")
        if signals["community"] and not before["community"]:
            community_sources.add("tags")
        if signals["explicit_private_yes"] and not before["explicit_private_yes"]:
            explicit_yes_sources.add("tags")
        if signals["explicit_private_no"] and not before["explicit_private_no"]:
            explicit_no_sources.add("tags")

    # Layer 3: photo tags + fallback columns
    photo_tags = _json_list(row.get("raw_photo_tags"))
    for item in photo_tags:
        if not isinstance(item, dict):
            continue
        for label in item.get("labels", []) or []:
            text = str(label).replace("_", " ")
            before = signals.copy()
            _update_pool_signals_from_text(text, signals, evidence)
            sources.append("photo_tags")
            if signals["private"] and not before["private"]:
                private_sources.add("photo_tags")
            if signals["community"] and not before["community"]:
                community_sources.add("photo_tags")
            if signals["explicit_private_yes"] and not before["explicit_private_yes"]:
                explicit_yes_sources.add("photo_tags")
            if signals["explicit_private_no"] and not before["explicit_private_no"]:
                explicit_no_sources.add("photo_tags")

    for col in POOL_DETECTION_COLUMNS:
        if col not in row.index:
            continue
        raw = row.get(col)
        bool_value = _safe_bool(raw)
        if bool_value is True:
            signals["generic"] = True
            evidence.append(f"{col}=true")
            sources.append(col)
        elif bool_value is False:
            sources.append(col)
        else:
            before = signals.copy()
            _update_pool_signals_from_text(str(raw), signals, evidence)
            if str(raw).strip():
                sources.append(col)
            if signals["private"] and not before["private"]:
                private_sources.add(col)
            if signals["community"] and not before["community"]:
                community_sources.add(col)
            if signals["explicit_private_yes"] and not before["explicit_private_yes"]:
                explicit_yes_sources.add(col)
            if signals["explicit_private_no"] and not before["explicit_private_no"]:
                explicit_no_sources.add(col)

    structured_sources = {"details", "tags", "photo_tags"}
    private_structured = bool(private_sources & structured_sources)
    community_structured = bool(community_sources & structured_sources)
    explicit_yes = signals["explicit_private_yes"]
    explicit_no = signals["explicit_private_no"]
    has_conflict = bool((explicit_yes and explicit_no) or (explicit_no and signals["private"]))
    community_only = bool(signals["community"] and not signals["private"] and not explicit_yes)
    inferred_private_high = bool(private_structured and not community_structured and not explicit_no)

    if has_conflict:
        is_private_pool = False
        is_private_pool_known = True
        pool_type = "unknown"
        confidence = "high"
    elif explicit_yes:
        is_private_pool = True
        is_private_pool_known = True
        pool_type = "private" if not signals["community"] else "both"
        confidence = "high"
    elif explicit_no:
        is_private_pool = False
        is_private_pool_known = True
        pool_type = "community" if signals["community"] else "unknown"
        confidence = "high"
    elif inferred_private_high:
        is_private_pool = True
        is_private_pool_known = True
        pool_type = "private"
        confidence = "high"
    elif signals["private"] and signals["community"]:
        is_private_pool = False
        is_private_pool_known = True
        pool_type = "both"
        confidence = "medium"
    elif signals["private"]:
        # Private-only in fallback free text is not strong enough to verify.
        is_private_pool = False
        is_private_pool_known = False
        pool_type = "private"
        confidence = "medium"
    elif community_only:
        is_private_pool = False
        is_private_pool_known = True
        pool_type = "community"
        confidence = "medium"
    elif signals["generic"]:
        is_private_pool = False
        is_private_pool_known = False
        pool_type = "unknown"
        confidence = "low"
    else:
        is_private_pool = False
        is_private_pool_known = False
        pool_type = "unknown"
        confidence = "low"

    pool_available = bool(
        signals["generic"] or signals["private"] or signals["community"] or signals["explicit_private_yes"]
    )
    unique_sources = sorted(set(sources))
    evidence_preview = "; ".join(dict.fromkeys(evidence).keys())[:1000] if evidence else ""
    private_pool_verified = bool(is_private_pool_known and is_private_pool and not has_conflict)

    return {
        "pool_available": pool_available,
        "pool_type": pool_type,
        "is_private_pool": is_private_pool,
        "is_private_pool_known": is_private_pool_known,
        "private_pool_verified": private_pool_verified,
        "pool_conflict": has_conflict,
        "pool_community_only": community_only,
        "pool_confidence": confidence,
        "pool_signal_sources": ",".join(unique_sources) if unique_sources else "none",
        "pool_evidence": evidence_preview if evidence_preview else pd.NA,
    }


def enrich_and_enforce_required_baseline_fields(df: pd.DataFrame, *, zip_code: str, listing_type: str) -> pd.DataFrame:
    if df.empty:
        return df

    enriched = df.copy()
    pool_mapping = enriched.apply(_extract_pool_mapping, axis=1)
    enriched["pool_available"] = pool_mapping.map(lambda x: bool(x["pool_available"]))
    enriched["pool_type"] = pool_mapping.map(lambda x: x["pool_type"])
    enriched["is_private_pool"] = pool_mapping.map(lambda x: bool(x["is_private_pool"]))
    enriched["is_private_pool_known"] = pool_mapping.map(lambda x: bool(x["is_private_pool_known"]))
    enriched["private_pool_verified"] = pool_mapping.map(lambda x: bool(x["private_pool_verified"]))
    enriched["pool_conflict"] = pool_mapping.map(lambda x: bool(x["pool_conflict"]))
    enriched["pool_community_only"] = pool_mapping.map(lambda x: bool(x["pool_community_only"]))
    enriched["pool_confidence"] = pool_mapping.map(lambda x: x["pool_confidence"])
    enriched["pool_signal_sources"] = pool_mapping.map(lambda x: x["pool_signal_sources"])
    enriched["pool_evidence"] = pool_mapping.map(lambda x: x["pool_evidence"])
    # Backward-compatible fields used by existing scripts/tests.
    enriched["has_pool_inferred"] = enriched["pool_available"]
    enriched["has_pool_source"] = enriched["pool_signal_sources"]

    list_price = pd.to_numeric(enriched.get("list_price"), errors="coerce")
    sqft = pd.to_numeric(enriched.get("sqft"), errors="coerce")
    enriched["price_per_sqft"] = (list_price / sqft).where(sqft > 0)

    lot_sqft = pd.to_numeric(enriched.get("lot_sqft"), errors="coerce")
    street = enriched.get("street", pd.Series(dtype="object")).map(_normalize_text)
    property_url = enriched.get("property_url", pd.Series(dtype="object")).map(_normalize_text)
    style = enriched.get("style", pd.Series(dtype="object")).map(_normalize_text)

    required_mask = (
        list_price.notna()
        & (list_price > 0)
        & sqft.notna()
        & (sqft > 0)
        & lot_sqft.notna()
        & (lot_sqft > 0)
        & (street != "")
        & (property_url != "")
        & style.str.contains("single", na=False)
    )

    kept = enriched[required_mask].copy()
    dropped = int(len(enriched) - len(kept))
    pool_detected = int(kept["pool_available"].sum()) if not kept.empty else 0
    private_known = int(kept["is_private_pool_known"].sum()) if not kept.empty else 0
    private_true = int(kept["is_private_pool"].sum()) if not kept.empty else 0
    private_verified = int(kept["private_pool_verified"].sum()) if not kept.empty else 0
    community_only = int(kept["pool_community_only"].sum()) if not kept.empty else 0
    pool_conflict = int(kept["pool_conflict"].sum()) if not kept.empty else 0
    if dropped > 0:
        print(
            f"[baseline-required] ZIP {zip_code} {listing_type}: dropped {dropped}/{len(enriched)} rows "
            "missing required baseline fields (price, sqft, address, url, lot_size, type)."
        )
    print(
        f"[baseline-required] ZIP {zip_code} {listing_type}: kept {len(kept)} rows; "
        f"pool_detected={pool_detected}; private_pool_true={private_true}; "
        f"private_pool_unknown={len(kept) - private_known}; private_pool_verified={private_verified}; "
        f"community_only={community_only}; conflict={pool_conflict}."
    )
    if (kept.get("pool_signal_sources", pd.Series(dtype="object")) == "none").any():
        print(
            f"[baseline-required] ZIP {zip_code} {listing_type}: warning -> some rows have no pool signals in "
            "details/tags/photo-tags or fallback text; private-pool remains unknown."
        )

    return kept


def compute_previous_day_window(
    *,
    run_date: date | None = None,
    tz_name: str = LA_TIMEZONE,
) -> tuple[datetime, datetime]:
    tz = ZoneInfo(tz_name)
    if run_date is None:
        run_date = datetime.now(tz).date()

    target_day = run_date - timedelta(days=1)
    window_start = datetime.combine(target_day, time(0, 0, 0), tzinfo=tz)
    window_end = datetime.combine(target_day, time(23, 59, 59), tzinfo=tz)
    return window_start, window_end


def compute_recent_window(
    *,
    run_date: date | None = None,
    lookback_days: int = 3,
    tz_name: str = LA_TIMEZONE,
) -> tuple[datetime, datetime]:
    if lookback_days < 1:
        raise ValueError("lookback_days must be >= 1.")

    tz = ZoneInfo(tz_name)
    if run_date is None:
        run_date = datetime.now(tz).date()

    end_day = run_date - timedelta(days=1)
    start_day = run_date - timedelta(days=lookback_days)
    window_start = datetime.combine(start_day, time(0, 0, 0), tzinfo=tz)
    window_end = datetime.combine(end_day, time(23, 59, 59), tzinfo=tz)
    return window_start, window_end


def _parse_cli_datetime(value: str, *, tz_name: str = LA_TIMEZONE, is_end: bool = False) -> datetime:
    tz = ZoneInfo(tz_name)
    if "T" in value:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)

    parsed_date = date.fromisoformat(value)
    parsed_time = time(23, 59, 59) if is_end else time(0, 0, 0)
    return datetime.combine(parsed_date, parsed_time, tzinfo=tz)


def resolve_window_from_args(args: argparse.Namespace) -> tuple[datetime, datetime]:
    if bool(args.date_from) != bool(args.date_to):
        raise ValueError("--date-from and --date-to must be provided together.")

    if args.date_from and args.date_to:
        start = _parse_cli_datetime(args.date_from, is_end=False)
        end = _parse_cli_datetime(args.date_to, is_end=True)
        if end < start:
            raise ValueError("--date-to must be greater than or equal to --date-from.")
        return start, end

    run_date = date.fromisoformat(args.run_date) if args.run_date else None
    lookback_days = getattr(args, "lookback_days", 3)
    return compute_recent_window(run_date=run_date, lookback_days=lookback_days)


def get_property_details(
    zip_code: str,
    listing_type: str,
    *,
    past_days: Optional[int] = 365,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> pd.DataFrame:
    scrape_kwargs: dict[str, object] = {
        "location": zip_code,
        "listing_type": listing_type,
        "property_type": HOME_PROPERTY_TYPES,
    }

    if date_from and date_to:
        scrape_kwargs["date_from"] = date_from
        scrape_kwargs["date_to"] = date_to
    else:
        scrape_kwargs["past_days"] = past_days

    properties = scrape_property(**scrape_kwargs)
    if properties.empty:
        return properties

    selected_columns = [
        "property_url",
        "property_id",
        "style",
        "status",
        "street",
        "city",
        "state",
        "zip_code",
        "county",
        "neighborhoods",
        "latitude",
        "longitude",
        "beds",
        "full_baths",
        "half_baths",
        "sqft",
        "year_built",
        "days_on_mls",
        "list_date",
        "last_sold_date",
        "list_price",
        "sold_price",
        "price_per_sqft",
        "lot_sqft",
        "lot_size_sqft",
        "text",
        "listing_description",
        "hoa_fee",
        "hoa_monthly_fee",
    ]
    optional_columns = [
        "raw_details",
        "raw_tags",
        "raw_photo_tags",
        "pool",
        "has_pool",
        "private_pool",
        "pool_private",
        "pool_features",
        "amenities",
        "description",
        "remarks",
        "features",
    ]
    missing = [c for c in selected_columns if c not in properties.columns]
    if missing:
        raise RuntimeError(f"Unexpected missing columns: {missing}")
    available_optional = [c for c in optional_columns if c in properties.columns]
    filtered = filter_home_listings(
        properties[selected_columns + available_optional],
        min_price=MIN_VALID_HOME_PRICE,
    )
    required_baseline_rows = enrich_and_enforce_required_baseline_fields(
        filtered,
        zip_code=zip_code,
        listing_type=listing_type,
    )
    return required_baseline_rows


def _event_timestamp(row: pd.Series) -> pd.Timestamp:
    status = str(row.get("status", "")).upper()
    raw_date = row.get("last_sold_date") if status == "SOLD" else row.get("list_date")
    dt = pd.to_datetime(raw_date, errors="coerce", utc=True)
    return pd.Timestamp.min.tz_localize("UTC") if pd.isna(dt) else dt


def dedupe_batch_by_property_id(batch_df: pd.DataFrame) -> pd.DataFrame:
    if batch_df.empty:
        return batch_df

    df = batch_df.copy()
    df["_property_id_key"] = df["property_id"].map(_normalize_property_id)
    df = df[df["_property_id_key"] != ""]
    if df.empty:
        return df

    df["_event_ts"] = df.apply(_event_timestamp, axis=1)
    df["_status_priority"] = df["status"].map(lambda x: STATUS_PRIORITY.get(str(x).upper(), 0))

    df = df.sort_values(
        by=["_property_id_key", "_event_ts", "_status_priority"],
        ascending=[True, False, False],
        kind="mergesort",
    )

    deduped = df.drop_duplicates(subset=["_property_id_key"], keep="first").copy()
    return deduped.drop(columns=["_property_id_key", "_event_ts", "_status_priority"])


def filter_new_property_rows(existing_df: pd.DataFrame, deduped_batch_df: pd.DataFrame) -> pd.DataFrame:
    """Keep rows whose property_id does not already exist in historical combined data."""
    existing_ids = {
        _normalize_property_id(v)
        for v in existing_df.get("property_id", pd.Series(dtype="object")).tolist()
        if _normalize_property_id(v)
    }

    if deduped_batch_df.empty:
        return deduped_batch_df.copy()

    candidate_df = deduped_batch_df.copy()
    candidate_df["_property_id_key"] = candidate_df["property_id"].map(_normalize_property_id)
    return candidate_df[~candidate_df["_property_id_key"].isin(existing_ids)].drop(columns=["_property_id_key"])


def summarize_incremental_batch(
    existing_df: pd.DataFrame,
    fetched_df: pd.DataFrame,
    deduped_batch_df: pd.DataFrame,
    new_rows_df: pd.DataFrame,
    status_updated_rows: int = 0,
    unchanged_overlap_rows: int = 0,
) -> dict[str, int]:
    existing_ids = {
        _normalize_property_id(v)
        for v in existing_df.get("property_id", pd.Series(dtype="object")).tolist()
        if _normalize_property_id(v)
    }
    deduped_ids = {
        _normalize_property_id(v)
        for v in deduped_batch_df.get("property_id", pd.Series(dtype="object")).tolist()
        if _normalize_property_id(v)
    }
    overlap_count = len(deduped_ids & existing_ids)
    return {
        "fetched_rows": len(fetched_df),
        "deduped_rows": len(deduped_batch_df),
        "existing_overlap_rows": overlap_count,
        "new_rows": len(new_rows_df),
        "status_updated_rows": status_updated_rows,
        "unchanged_overlap_rows": unchanged_overlap_rows,
    }


def _values_equal(lhs: object, rhs: object) -> bool:
    if lhs is None and rhs is None:
        return True
    lhs_missing = pd.isna(lhs) if not isinstance(lhs, (list, dict, tuple, set)) else False
    rhs_missing = pd.isna(rhs) if not isinstance(rhs, (list, dict, tuple, set)) else False
    if lhs_missing and rhs_missing:
        return True
    return lhs == rhs


def _row_needs_refresh(existing_row: pd.Series, incoming: dict[str, object]) -> bool:
    for col, incoming_value in incoming.items():
        existing_value = existing_row.get(col, pd.NA)
        if not _values_equal(existing_value, incoming_value):
            return True
    return False


def apply_incremental_upserts(
    existing_df: pd.DataFrame,
    deduped_batch_df: pd.DataFrame,
    *,
    batch_run_at: str,
    batch_window_start: str,
    batch_window_end: str,
) -> tuple[pd.DataFrame, pd.DataFrame, int, int]:
    """
    Upsert deduped batch into existing rows.

    - New property_id -> append as new row.
    - Existing property_id with changed status -> update existing row in place.
    - Existing property_id with same status -> refresh row if fields changed.
    """
    combined_df = existing_df.copy()

    if deduped_batch_df.empty:
        return combined_df, deduped_batch_df.copy(), 0, 0

    if "property_id" not in combined_df.columns:
        combined_df["property_id"] = pd.NA

    index_by_property_id: dict[str, int] = {}
    for idx, value in combined_df["property_id"].items():
        property_id = _normalize_property_id(value)
        if property_id:
            # Keep last occurrence so updates target the most recent row.
            index_by_property_id[property_id] = idx

    new_rows: list[dict[str, object]] = []
    status_updated_rows = 0
    unchanged_overlap_rows = 0

    for _, incoming_row in deduped_batch_df.iterrows():
        incoming_dict = incoming_row.to_dict()
        property_id = _normalize_property_id(incoming_dict.get("property_id"))
        if not property_id:
            continue

        existing_idx = index_by_property_id.get(property_id)
        incoming_status = _normalize_status(incoming_dict.get("status"))

        if existing_idx is None:
            incoming_dict["batch_run_at"] = batch_run_at
            incoming_dict["batch_window_start"] = batch_window_start
            incoming_dict["batch_window_end"] = batch_window_end
            incoming_dict["ingest_mode"] = "incremental"
            incoming_dict["is_new_in_batch"] = True
            incoming_dict["is_status_updated_in_batch"] = False
            incoming_dict["status_previous"] = pd.NA
            incoming_dict["status_updated_to"] = incoming_status if incoming_status else pd.NA
            new_rows.append(incoming_dict)
            continue

        previous_status = (
            _normalize_status(combined_df.at[existing_idx, "status"]) if "status" in combined_df.columns else ""
        )
        status_changed = bool(incoming_status and incoming_status != previous_status)
        needs_refresh = _row_needs_refresh(combined_df.loc[existing_idx], incoming_dict)

        if status_changed or needs_refresh:
            # Refresh existing row with incoming listing fields when status changed
            # or when other listing attributes changed (e.g., list_price updates).
            for col, value in incoming_dict.items():
                combined_df.at[existing_idx, col] = value

            combined_df.at[existing_idx, "batch_run_at"] = batch_run_at
            combined_df.at[existing_idx, "batch_window_start"] = batch_window_start
            combined_df.at[existing_idx, "batch_window_end"] = batch_window_end
            combined_df.at[existing_idx, "ingest_mode"] = "incremental"
            combined_df.at[existing_idx, "is_new_in_batch"] = False
            combined_df.at[existing_idx, "is_status_updated_in_batch"] = status_changed
            combined_df.at[existing_idx, "status_previous"] = (
                previous_status if status_changed and previous_status else pd.NA
            )
            combined_df.at[existing_idx, "status_updated_to"] = (
                incoming_status if status_changed and incoming_status else pd.NA
            )
            if status_changed:
                status_updated_rows += 1
        else:
            unchanged_overlap_rows += 1

    new_rows_df = pd.DataFrame(new_rows)
    if not new_rows_df.empty:
        combined_df = pd.concat([combined_df, new_rows_df], ignore_index=True, sort=False)

    return combined_df, new_rows_df, status_updated_rows, unchanged_overlap_rows


def output_zip_folder(zip_code: str, frames: dict[str, pd.DataFrame]) -> None:
    zip_folder = OUTPUT_DIR / zip_code
    zip_folder.mkdir(parents=True, exist_ok=True)
    for name, df in frames.items():
        base = zip_folder / f"{zip_code}_{name}"
        df.to_csv(f"{base}.csv", index=False)
        df.to_excel(f"{base}.xlsx", index=False)


def normalize_combined_export_columns(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    # Keep only the canonical neighborhood column in aggregate outputs.
    if "str_organized_neighborhood" in normalized.columns and "neighborhoods" in normalized.columns:
        normalized = normalized.drop(columns=["neighborhoods"])
    return normalized


def run_full_mode() -> None:
    combined_df = pd.DataFrame()
    for zip_code in STR_FRIENDLY_ZIP_CODES:
        frames = {lt: get_property_details(zip_code, lt, past_days=pdays) for lt, pdays in LISTING_SCRAPES}
        combined_df = pd.concat([combined_df, *frames.values()], ignore_index=True)
        output_zip_folder(zip_code, frames)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    neighborhood_zip_csv = OUTPUT_DIR / "palm_springs_neighborhood_cap_by_zip.csv"
    neighborhood_zip_xlsx = OUTPUT_DIR / "palm_springs_neighborhood_cap_by_zip.xlsx"

    combined_df = enrich_with_palm_springs_str_neighborhoods(
        combined_df,
        summary_path=SUMMARY_PATH,
        crosswalk_path=CROSSWALK_PATH,
        aliases_path=ALIASES_PATH,
    )
    combined_df = normalize_combined_export_columns(combined_df)
    neighborhood_zip_df = build_neighborhood_zip_table(SUMMARY_PATH, CROSSWALK_PATH)

    combined_df.to_csv(COMBINED_CSV_PATH, index=False)
    combined_df.to_excel(COMBINED_XLSX_PATH, index=False)
    neighborhood_zip_df.to_csv(neighborhood_zip_csv, index=False)
    neighborhood_zip_df.to_excel(neighborhood_zip_xlsx, index=False)

    status_counts = combined_df["status"].value_counts().to_dict() if not combined_df.empty else {}
    print(
        f"Wrote {len(combined_df)} rows to:\n"
        f"  {COMBINED_CSV_PATH}\n"
        f"  {COMBINED_XLSX_PATH}\n"
        f"  {neighborhood_zip_csv}\n"
        f"  {neighborhood_zip_xlsx}\n"
        f"Status column counts: {status_counts}"
    )


def run_incremental_mode(args: argparse.Namespace) -> None:
    window_start, window_end = resolve_window_from_args(args)

    frames: list[pd.DataFrame] = []
    for zip_code in STR_FRIENDLY_ZIP_CODES:
        for listing_type in LISTING_TYPES_INCREMENTAL:
            df = get_property_details(
                zip_code,
                listing_type,
                date_from=window_start,
                date_to=window_end,
            )
            if not df.empty:
                frames.append(df)

    fetched_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not fetched_df.empty:
        fetched_df = enrich_with_palm_springs_str_neighborhoods(
            fetched_df,
            summary_path=SUMMARY_PATH,
            crosswalk_path=CROSSWALK_PATH,
            aliases_path=ALIASES_PATH,
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    existing_df = pd.read_excel(COMBINED_XLSX_PATH) if COMBINED_XLSX_PATH.exists() else pd.DataFrame()

    deduped_batch = dedupe_batch_by_property_id(fetched_df)

    batch_run_at = datetime.now(ZoneInfo(LA_TIMEZONE)).isoformat()
    combined_df, incremental_new_rows, status_updated_rows, unchanged_overlap_rows = apply_incremental_upserts(
        existing_df,
        deduped_batch,
        batch_run_at=batch_run_at,
        batch_window_start=window_start.isoformat(),
        batch_window_end=window_end.isoformat(),
    )
    summary = summarize_incremental_batch(
        existing_df,
        fetched_df,
        deduped_batch,
        incremental_new_rows,
        status_updated_rows=status_updated_rows,
        unchanged_overlap_rows=unchanged_overlap_rows,
    )
    combined_df = normalize_combined_export_columns(combined_df)

    combined_df.to_csv(COMBINED_CSV_PATH, index=False)
    combined_df.to_excel(COMBINED_XLSX_PATH, index=False)

    print(
        f"Incremental window: {window_start.isoformat()} -> {window_end.isoformat()}\n"
        f"Fetched rows: {summary['fetched_rows']}\n"
        f"Rows after in-batch property_id dedupe: {summary['deduped_rows']}\n"
        f"Overlap with existing property_id rows: {summary['existing_overlap_rows']}\n"
        f"New rows appended: {summary['new_rows']}\n"
        f"Existing rows updated due to status change: {summary['status_updated_rows']}\n"
        f"Existing rows unchanged (same status): {summary['unchanged_overlap_rows']}\n"
        f"Skipped existing property_id rows: {max(0, summary['existing_overlap_rows'] - summary['status_updated_rows'])}\n"
        f"Combined total rows: {len(combined_df)}\n"
        f"Wrote: {COMBINED_CSV_PATH}\n"
        f"Wrote: {COMBINED_XLSX_PATH}"
    )


def main() -> None:
    args = parse_args()
    if args.mode == "full":
        run_full_mode()
    else:
        run_incremental_mode(args)


if __name__ == "__main__":
    main()

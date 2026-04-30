from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_INPUT_PATH = Path("examples/zips/combined.xlsx")
DEFAULT_OUTPUT_PATH = Path("examples/zips/str_suitability_filter.xlsx")
DEFAULT_ASSUMPTIONS_PATH = Path("examples/data/str_suitability_filters.json")
DEFAULT_CAP_WORKBOOK_PATH = Path("examples/zips/palm_springs_neighborhood_cap_by_zip.xlsx")
DEFAULT_COC_ASSUMPTIONS_PATH = Path("examples/data/coc_assumptions.json")

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
POOL_KEYWORDS = (" pool ", "swimming pool", "spa", "hot tub", "plunge pool")
POOL_PRIVATE_YES_KEYWORDS = ("pool private: yes", "private pool")
POOL_PRIVATE_NO_KEYWORDS = ("pool private: no", "community pool", "community swimming pool", "shared pool")
POOL_COLUMNS = (
    "private_pool_verified",
    "pool_conflict",
    "pool_community_only",
    "pool_confidence",
    "pool_signal_sources",
    "pool_evidence",
    "is_private_pool",
    "is_private_pool_known",
    "pool_available",
    "pool_type",
    "pool",
    "has_pool",
    "has_pool_inferred",
    "private_pool",
    "pool_private",
    "pool_features",
    "amenities",
    "description",
    "remarks",
    "features",
)
POOL_RAW_COLUMNS = ("raw_details", "raw_tags", "raw_photo_tags")

MANUAL_EXCLUDED_PROPERTY_IDS = {
    "1086968872",  # 470 E Avenida Olancha, Palm Springs, CA 92264
}
MANUAL_EXCLUDED_ADDRESSES = {
    ("470 e avenida olancha", "palm springs", "ca", "92264"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate STR suitability filter results from combined listings")
    parser.add_argument("--input", default=str(DEFAULT_INPUT_PATH), help="Input listings workbook path")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="Output STR suitability workbook path")
    parser.add_argument(
        "--assumptions",
        default=str(DEFAULT_ASSUMPTIONS_PATH),
        help="JSON assumptions path for STR suitability thresholds and scoring",
    )
    parser.add_argument("--top-n", type=int, default=50, help="Top N rows for STR-suitable-only sheet")
    return parser.parse_args()


def load_assumptions(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return _normalize_assumptions(raw)


def _normalize_assumptions(raw: dict[str, Any]) -> dict[str, Any]:
    thresholds = raw.get("thresholds", {})
    requirements = raw.get("requirements", {})
    location = raw.get("location", {})
    preferred_cities_default = ["Palm Springs", "Bermuda Dunes", "Indio"]
    preferred_cities = list(location.get("preferred_cities", preferred_cities_default))
    scope_zip_candidates = list(
        location.get("scope_zip_candidates", ["92258", "92262", "92263", "92264", "92201", "92202", "92203"])
    )

    hard_gates = raw.get("hard_gates", {})
    if not hard_gates:
        hard_gates = {
            "require_quality": True,
            "require_str_supported_neighborhood": bool(requirements.get("require_str_supported_neighborhood", True)),
            "require_private_pool": bool(requirements.get("require_pool", True)),
            "require_price_range": True,
            "require_beds_baths": True,
            "require_location": bool(location.get("enabled", True)),
            "require_geo_cap_zip": True,
            "min_beds": int(thresholds.get("min_beds", 2)),
            "min_full_baths": int(thresholds.get("min_full_baths", 2)),
            "min_list_price": float(thresholds.get("min_list_price", 100000)),
            "max_list_price": float(thresholds.get("max_list_price", 3000000)),
        }
    else:
        hard_gates.setdefault("require_private_pool", bool(requirements.get("require_pool", True)))

    pool_verification = raw.get("pool_verification", {})
    normalized_pool_verification = {
        "allow_high_conf_inferred_private": bool(pool_verification.get("allow_high_conf_inferred_private", True)),
        "high_conf_levels": list(pool_verification.get("high_conf_levels", ["high"])),
        "min_verified_coverage_warn": float(pool_verification.get("min_verified_coverage_warn", 0.05)),
        "fail_on_low_verified_coverage": bool(pool_verification.get("fail_on_low_verified_coverage", False)),
    }
    enrichment_workflow = raw.get("enrichment_workflow", {})
    normalized_enrichment_workflow = {
        "enabled": bool(enrichment_workflow.get("enabled", False)),
        "listing_type": str(enrichment_workflow.get("listing_type", "for_sale")),
        "past_days": int(enrichment_workflow.get("past_days", 365)),
    }

    ranking_weights = raw.get("ranking_weights", {})
    if not ranking_weights:
        legacy = raw.get("scoring_weights", {})
        ranking_weights = {
            "quality": int(legacy.get("quality", 30)),
            "str_support": int(legacy.get("str_support", 25)),
            "beds_baths": int(legacy.get("beds_baths", 15)),
            "price_range": int(legacy.get("price_range", 5)),
            "location": int(legacy.get("location", 5)),
            "geo_cap_zip": int(legacy.get("str_support", 10)),
            "pool_signal": int(legacy.get("pool", 20)),
        }

    shortlist = raw.get("shortlist", {})
    if not shortlist:
        shortlist = {
            "enabled": True,
            "target_pass_rate_min": 0.10,
            "target_pass_rate_max": 0.20,
            "target_pass_rate_target": 0.15,
            "ranking_metric": "coc_med",
            "ranking_direction": "desc",
            "coc_assumptions_path": str(DEFAULT_COC_ASSUMPTIONS_PATH),
        }

    priority_ranking = raw.get("priority_ranking", {})
    default_priority_weights = {
        "price_per_sqft": 0.40,
        "lot_size": 0.25,
        "neighborhood_support": 0.35,
    }
    raw_priority_weights = priority_ranking.get("factor_weights", {})
    normalized_priority_weights = {
        "price_per_sqft": _safe_float(
            raw_priority_weights.get("price_per_sqft"), default_priority_weights["price_per_sqft"]
        ),
        "lot_size": _safe_float(raw_priority_weights.get("lot_size"), default_priority_weights["lot_size"]),
        "neighborhood_support": _safe_float(
            raw_priority_weights.get("neighborhood_support"), default_priority_weights["neighborhood_support"]
        ),
    }
    total_weight = sum(max(0.0, v) for v in normalized_priority_weights.values())
    if total_weight <= 0:
        normalized_priority_weights = default_priority_weights
    else:
        normalized_priority_weights = {k: (max(0.0, v) / total_weight) for k, v in normalized_priority_weights.items()}

    target_city_raw = str(priority_ranking.get("target_city", "Palm Springs")).strip()
    target_cities_raw = priority_ranking.get("target_cities", [])
    normalized_target_cities: list[str] = []
    if isinstance(target_cities_raw, list):
        for city in target_cities_raw:
            c = _safe_str(city).strip()
            if c and c.lower() not in {v.lower() for v in normalized_target_cities}:
                normalized_target_cities.append(c)
    if not normalized_target_cities:
        city_key = target_city_raw.lower()
        if city_key in {"coachella valley", "coachella_valley", "coachella-valley", "all", "*"}:
            normalized_target_cities = [c for c in preferred_cities if _safe_str(c).strip()]
        elif target_city_raw:
            normalized_target_cities = [target_city_raw]
    if not normalized_target_cities:
        normalized_target_cities = [c for c in preferred_cities_default]

    region_label_default = (
        "Palm Springs • Bermuda Dunes • Indio" if len(normalized_target_cities) > 1 else normalized_target_cities[0]
    )
    region_label = _safe_str(priority_ranking.get("region_label"), region_label_default).strip() or region_label_default

    priority_ranking = {
        "enabled": bool(priority_ranking.get("enabled", True)),
        "target_city": target_city_raw or "Palm Springs",
        "target_cities": normalized_target_cities,
        "region_label": region_label,
        "require_for_sale_status": bool(priority_ranking.get("require_for_sale_status", True)),
        "require_str_fit_pass": bool(priority_ranking.get("require_str_fit_pass", True)),
        "factor_weights": normalized_priority_weights,
        "tie_break_metrics": list(
            priority_ranking.get("tie_break_metrics", ["coc_post_tax", "coc_pre_tax", "property_id"])
        ),
    }

    geography = raw.get("geography", {})
    if not geography:
        geography = {
            "enabled": True,
            "require_under_cap_zip": True,
            "cap_percentage_max": 0.20,
            "neighborhood_cap_workbook": str(DEFAULT_CAP_WORKBOOK_PATH),
            "zip_codes_column": "zip_codes",
            "primary_zip_column": "primary_zip",
            "percentage_column": "current_neighborhood_percentage",
            "fail_open_if_missing_cap_data": True,
            "strict_neighborhood_match": False,
        }
    geography.setdefault("strict_neighborhood_match", False)

    normalized_location = {
        "enabled": bool(location.get("enabled", True)),
        "preferred_cities": preferred_cities,
        "scope_zip_candidates": scope_zip_candidates,
    }

    return {
        "hard_gates": hard_gates,
        "location": normalized_location,
        "geography": geography,
        "ranking_weights": ranking_weights,
        "shortlist": shortlist,
        "pool_verification": normalized_pool_verification,
        "enrichment_workflow": normalized_enrichment_workflow,
        "priority_ranking": priority_ranking,
        # Keep legacy sections for compatibility/audit sheets.
        "thresholds": {
            "min_beds": hard_gates["min_beds"],
            "min_full_baths": hard_gates["min_full_baths"],
            "min_list_price": hard_gates["min_list_price"],
            "max_list_price": hard_gates["max_list_price"],
        },
        "requirements": {
            "require_str_supported_neighborhood": hard_gates["require_str_supported_neighborhood"],
            "require_pool": hard_gates.get("require_private_pool", True),
            "exclude_unknown_private_pool": hard_gates.get("require_private_pool", True),
        },
        "scoring_weights": {
            "quality": ranking_weights.get("quality", 30),
            "str_support": ranking_weights.get("str_support", 25),
            "pool": ranking_weights.get("pool_signal", 20),
            "beds_baths": ranking_weights.get("beds_baths", 15),
            "price_range": ranking_weights.get("price_range", 5),
            "location": ranking_weights.get("location", 5),
        },
    }


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_str(value: Any, default: str = "") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    return str(value)


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = _safe_str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "t"}:
        return True
    if text in {"0", "false", "no", "n", "f"}:
        return False
    number = _safe_float(value, float("nan"))
    if pd.notna(number):
        return number > 0
    return False


def _normalize_zip(value: Any) -> str:
    text = _safe_str(value).strip()
    if not text:
        return ""
    if text.endswith(".0") and text.replace(".", "", 1).isdigit():
        text = text.split(".", 1)[0]
    return text


def _canonicalize_neighborhood(value: Any) -> str:
    normalized = _safe_str(value).strip().lower()
    if not normalized:
        return ""
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _address_key(row: pd.Series) -> tuple[str, str, str, str]:
    return (
        _safe_str(row.get("street")).strip().lower(),
        _safe_str(row.get("city")).strip().lower(),
        _safe_str(row.get("state")).strip().lower(),
        _normalize_zip(row.get("zip_code")),
    )


def _contains_excluded_address_keyword(street: Any) -> bool:
    value = f" {_safe_str(street).strip().lower()} "
    return any(keyword in value for keyword in ADDRESS_EXCLUDE_KEYWORDS)


def _contains_co_ownership_keyword(value: Any) -> bool:
    normalized = f" {_safe_str(value).strip().lower()} "
    return any(keyword in normalized for keyword in CO_OWNERSHIP_KEYWORDS)


def _has_unit_designator(street: Any) -> bool:
    normalized = _safe_str(street).strip().lower()
    return any(token in normalized for token in UNIT_ADDRESS_TOKENS)


def _looks_like_variant_share_listing(street: Any, property_url: Any) -> bool:
    street_text = _safe_str(street).strip().lower()
    url_text = _safe_str(property_url).strip().lower()
    marker = "/realestateandhomes-detail/"
    if not street_text or marker not in url_text:
        return False
    slug = url_text.split(marker, 1)[1].split("_", 1)[0]
    street_slug = re.sub(r"[^a-z0-9]+", "-", street_text).strip("-")
    if not street_slug or not slug.startswith(f"{street_slug}-"):
        return False
    if _has_unit_designator(street_text):
        return False
    suffix = slug[len(street_slug) + 1 :]
    return bool(suffix and re.fullmatch(r"[a-z0-9-]{1,8}", suffix))


def _is_probable_co_ownership_row(row: pd.Series) -> bool:
    return (
        _contains_co_ownership_keyword(row.get("street"))
        or _contains_co_ownership_keyword(row.get("property_url"))
        or _looks_like_variant_share_listing(row.get("street"), row.get("property_url"))
    )


def _co_ownership_group_keys(df: pd.DataFrame) -> set[tuple[Any, Any, Any, Any, Any, Any]]:
    required = {"street", "city", "zip_code", "beds", "full_baths", "sqft", "property_id"}
    if not required.issubset(df.columns) or df.empty:
        return set()
    key_cols = ["street", "city", "zip_code", "beds", "full_baths", "sqft"]
    working = df.copy()
    working["_co_row_flag"] = working.apply(_is_probable_co_ownership_row, axis=1)
    grouped = working.groupby(key_cols, dropna=False).agg(
        property_id_count=("property_id", "nunique"),
        any_co_flag=("_co_row_flag", "max"),
        sample_street=("street", "first"),
    )
    grouped["no_unit"] = ~grouped["sample_street"].map(_has_unit_designator)
    grouped["exclude"] = grouped["no_unit"] & (
        (grouped["property_id_count"] >= 2) | (grouped["any_co_flag"].astype(bool))
    )
    return set(grouped[grouped["exclude"]].index.tolist())


def _is_manually_excluded_row(row: pd.Series) -> bool:
    property_id = _safe_str(row.get("property_id")).strip()
    if property_id and property_id in MANUAL_EXCLUDED_PROPERTY_IDS:
        return True
    return _address_key(row) in MANUAL_EXCLUDED_ADDRESSES


def _parse_json_like_list(value: Any) -> list[Any]:
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


def _text_contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _infer_pool(row: pd.Series) -> tuple[bool, bool, str]:
    generic_pool_source: str | None = None

    for column in POOL_RAW_COLUMNS:
        if column not in row.index:
            continue

        raw_values = _parse_json_like_list(row.get(column))
        for raw in raw_values:
            if isinstance(raw, dict):
                normalized = f" {json.dumps(raw, ensure_ascii=False).strip().lower()} "
            else:
                normalized = f" {_safe_str(raw).strip().lower()} "
            if not normalized.strip():
                continue
            if _text_contains_any(normalized, POOL_PRIVATE_YES_KEYWORDS):
                return True, True, column
            if _text_contains_any(normalized, POOL_PRIVATE_NO_KEYWORDS):
                return False, True, column
            if _text_contains_any(normalized, POOL_KEYWORDS):
                generic_pool_source = generic_pool_source or column

    for column in POOL_COLUMNS:
        if column not in row.index:
            continue
        value = row.get(column)
        if column == "is_private_pool":
            known_value = (
                _safe_bool(row.get("is_private_pool_known")) if "is_private_pool_known" in row.index else False
            )
            return _safe_bool(value), bool(known_value), "is_private_pool"
        if column == "is_private_pool_known":
            continue
        if column == "pool_available":
            available = _safe_bool(value)
            if available:
                generic_pool_source = generic_pool_source or column
            continue
        if isinstance(value, bool):
            if column in {"private_pool", "pool_private"}:
                return value, True, column
            if value:
                generic_pool_source = generic_pool_source or column
            continue
        if isinstance(value, (int, float)) and pd.notna(value):
            if value > 0:
                generic_pool_source = generic_pool_source or column
            continue
        text = f" {_safe_str(value).strip().lower()} "
        if _text_contains_any(text, POOL_PRIVATE_YES_KEYWORDS):
            return True, True, column
        if _text_contains_any(text, POOL_PRIVATE_NO_KEYWORDS):
            return False, True, column
        if _text_contains_any(text, POOL_KEYWORDS):
            generic_pool_source = generic_pool_source or column

    for column in ("street", "property_url", "neighborhoods"):
        text = f" {_safe_str(row.get(column)).strip().lower()} "
        if _text_contains_any(text, POOL_KEYWORDS):
            generic_pool_source = generic_pool_source or column

    if generic_pool_source:
        return False, False, generic_pool_source
    return False, False, "none"


def _resolve_private_pool(row: pd.Series, assumptions: dict[str, Any]) -> tuple[bool, bool, bool, str, float, str, str]:
    high_conf_levels = {
        str(level).strip().lower() for level in assumptions.get("pool_verification", {}).get("high_conf_levels", [])
    }
    allow_high_conf_inferred = bool(
        assumptions.get("pool_verification", {}).get("allow_high_conf_inferred_private", True)
    )

    if "private_pool_verified" in row.index:
        private_pool_verified = _safe_bool(row.get("private_pool_verified"))
        is_private_pool = _safe_bool(row.get("is_private_pool"))
        is_private_pool_known = _safe_bool(row.get("is_private_pool_known"))
        pool_conflict = _safe_bool(row.get("pool_conflict"))
        community_only = _safe_bool(row.get("pool_community_only"))
        pool_conf = _safe_str(row.get("pool_confidence")).strip().lower()

        if private_pool_verified:
            return True, True, True, "upstream_verified", 1.0, "high", "Private pool verified"
        if pool_conflict:
            return False, True, False, "upstream_conflict", 0.0, "high", "Pool signal conflict"
        if community_only:
            return False, True, False, "upstream_community_only", 0.0, "high", "Community pool only"
        if is_private_pool_known and not is_private_pool:
            return False, True, False, "upstream_private_no", 0.0, "high", "Private pool not present"
        if allow_high_conf_inferred and is_private_pool and pool_conf in high_conf_levels:
            return True, True, True, "upstream_high_conf_inferred", 1.0, "high", "Private pool verified"
        return (
            False,
            bool(is_private_pool_known),
            False,
            "upstream_unknown",
            0.0,
            pool_conf or "low",
            "Private pool unknown",
        )

    if "is_private_pool" in row.index and "is_private_pool_known" in row.index:
        is_private_pool = _safe_bool(row.get("is_private_pool"))
        is_private_pool_known = _safe_bool(row.get("is_private_pool_known"))
        source = "canonical"
    else:
        is_private_pool, is_private_pool_known, source = _infer_pool(row)
    if is_private_pool_known and is_private_pool:
        return True, True, True, source, 1.0, "high", "Private pool verified"
    if is_private_pool_known and not is_private_pool:
        return False, True, False, source, 0.0, "high", "Private pool not present"

    inferred_pool, inferred_known, inferred_source = _infer_pool(row)
    if inferred_pool:
        conf = "high" if (allow_high_conf_inferred and not inferred_known) else "medium"
        verified = bool(allow_high_conf_inferred and conf in high_conf_levels)
        return (
            verified,
            bool(inferred_known),
            verified,
            f"{source}|{inferred_source}",
            0.5,
            conf,
            ("Private pool verified" if verified else "Private pool unknown"),
        )
    return False, False, False, f"{source}:unknown_private_pool", 0.0, "low", "Private pool unknown"


def _quality_fail_reason(row: pd.Series, co_group_keys: set[tuple[Any, Any, Any, Any, Any, Any]]) -> str:
    price = _safe_float(row.get("list_price"), 0.0)
    beds = pd.to_numeric(row.get("beds"), errors="coerce")
    baths = pd.to_numeric(row.get("full_baths"), errors="coerce")
    sqft = pd.to_numeric(row.get("sqft"), errors="coerce")
    key = (
        row.get("street"),
        row.get("city"),
        row.get("zip_code"),
        row.get("beds"),
        row.get("full_baths"),
        row.get("sqft"),
    )

    if price <= 0:
        return "Missing list price"
    if _is_manually_excluded_row(row):
        return "Manually excluded co-ownership"
    if _contains_excluded_address_keyword(row.get("street")):
        return "Mobile/lot-style address keyword"
    if _is_probable_co_ownership_row(row):
        return "Co-ownership/fractional listing pattern"
    if key in co_group_keys and not _has_unit_designator(row.get("street")):
        return "Co-ownership cluster pattern"
    if pd.isna(beds) and pd.isna(baths) and pd.isna(sqft):
        return "Missing core home specs"
    return ""


def _compute_str_support(row: pd.Series, assumptions: dict[str, Any]) -> bool:
    under_cap = _safe_bool(row.get("str_nbhd_under_cap_current"))
    if not assumptions["hard_gates"].get("require_str_supported_neighborhood", True):
        return True

    geography = assumptions.get("geography", {})
    strict_neighborhood_match = bool(geography.get("strict_neighborhood_match", False))
    fail_open_if_missing_cap_data = bool(geography.get("fail_open_if_missing_cap_data", True))

    neighborhood = _canonicalize_neighborhood(row.get("str_organized_neighborhood") or row.get("neighborhoods"))
    cap_nbhd_keys = assumptions.get("_derived_cap_eligible_neighborhood_keys", set())

    if cap_nbhd_keys:
        if neighborhood:
            return neighborhood in cap_nbhd_keys
        return under_cap if not strict_neighborhood_match else False

    if fail_open_if_missing_cap_data and not strict_neighborhood_match:
        return under_cap
    return False


def _compute_location_fit(row: pd.Series, assumptions: dict[str, Any]) -> bool:
    location_cfg = assumptions.get("location", {})
    if not location_cfg.get("enabled", False):
        return True
    preferred = {str(city).strip().lower() for city in location_cfg.get("preferred_cities", [])}
    return _safe_str(row.get("city")).strip().lower() in preferred


def _derive_cap_eligible_zip_codes(assumptions: dict[str, Any]) -> tuple[set[str], str]:
    geography = assumptions.get("geography", {})
    if not geography.get("enabled", True):
        return set(), "geography_disabled"

    workbook_path = Path(str(geography.get("neighborhood_cap_workbook", DEFAULT_CAP_WORKBOOK_PATH)))
    if not workbook_path.exists():
        return set(), "missing_cap_workbook"

    percentage_col = str(geography.get("percentage_column", "current_neighborhood_percentage"))
    zip_codes_col = str(geography.get("zip_codes_column", "zip_codes"))
    primary_zip_col = str(geography.get("primary_zip_column", "primary_zip"))
    cap_max = float(geography.get("cap_percentage_max", 0.20))

    table = pd.read_excel(workbook_path)
    if percentage_col not in table.columns:
        return set(), "missing_cap_percentage_column"

    scope_candidates = {_normalize_zip(v) for v in assumptions.get("location", {}).get("scope_zip_candidates", []) if v}
    eligible: set[str] = set()

    for _, row in table.iterrows():
        pct = _safe_float(row.get(percentage_col), float("nan"))
        if pd.isna(pct) or pct >= cap_max:
            continue

        zip_candidates: set[str] = set()
        if zip_codes_col in table.columns:
            raw = _safe_str(row.get(zip_codes_col))
            for token in raw.split("|"):
                z = _normalize_zip(token)
                if z:
                    zip_candidates.add(z)
        z_primary = _normalize_zip(row.get(primary_zip_col))
        if z_primary:
            zip_candidates.add(z_primary)

        if scope_candidates:
            zip_candidates = {z for z in zip_candidates if z in scope_candidates}

        eligible.update(zip_candidates)

    return eligible, "ok"


def _derive_cap_eligible_neighborhood_keys(assumptions: dict[str, Any]) -> tuple[set[str], str]:
    geography = assumptions.get("geography", {})
    if not geography.get("enabled", True):
        return set(), "geography_disabled"

    workbook_path = Path(str(geography.get("neighborhood_cap_workbook", DEFAULT_CAP_WORKBOOK_PATH)))
    if not workbook_path.exists():
        return set(), "missing_cap_workbook"

    percentage_col = str(geography.get("percentage_column", "current_neighborhood_percentage"))
    neighborhood_key_col = str(geography.get("neighborhood_key_column", "neighborhood_key"))
    organized_neighborhood_col = str(geography.get("organized_neighborhood_column", "organized_neighborhood"))
    zip_codes_col = str(geography.get("zip_codes_column", "zip_codes"))
    primary_zip_col = str(geography.get("primary_zip_column", "primary_zip"))
    cap_max = float(geography.get("cap_percentage_max", 0.20))

    table = pd.read_excel(workbook_path)
    if percentage_col not in table.columns:
        return set(), "missing_cap_percentage_column"

    scope_candidates = {_normalize_zip(v) for v in assumptions.get("location", {}).get("scope_zip_candidates", []) if v}
    eligible: set[str] = set()

    for _, row in table.iterrows():
        pct = _safe_float(row.get(percentage_col), float("nan"))
        if pd.isna(pct) or pct >= cap_max:
            continue

        zip_candidates: set[str] = set()
        if zip_codes_col in table.columns:
            raw = _safe_str(row.get(zip_codes_col))
            for token in raw.split("|"):
                z = _normalize_zip(token)
                if z:
                    zip_candidates.add(z)
        z_primary = _normalize_zip(row.get(primary_zip_col))
        if z_primary:
            zip_candidates.add(z_primary)

        if scope_candidates and not (zip_candidates & scope_candidates):
            continue

        for source_col in (neighborhood_key_col, organized_neighborhood_col):
            if source_col in table.columns:
                key = _canonicalize_neighborhood(row.get(source_col))
                if key:
                    eligible.add(key)

    return eligible, "ok"


def _compute_geo_cap_zip(
    row: pd.Series, assumptions: dict[str, Any], cap_eligible_zips: set[str], cap_status: str
) -> tuple[bool, str]:
    geography = assumptions.get("geography", {})
    if not geography.get("enabled", True):
        return True, "geography_disabled"

    zip_code = _normalize_zip(row.get("zip_code"))
    if not zip_code:
        return False, "missing_zip"

    scope_candidates = {_normalize_zip(v) for v in assumptions.get("location", {}).get("scope_zip_candidates", []) if v}
    if scope_candidates and zip_code not in scope_candidates:
        return False, "zip_outside_scope"

    if not geography.get("require_under_cap_zip", True):
        return True, "cap_zip_not_required"

    if not cap_eligible_zips:
        if geography.get("fail_open_if_missing_cap_data", True):
            return True, "cap_data_unavailable_fail_open"
        return False, "cap_data_unavailable_fail_closed"

    if zip_code in cap_eligible_zips:
        return True, "zip_has_under_cap_neighborhood"
    return False, "zip_not_in_under_cap_set"


def _score_row(
    row: pd.Series,
    assumptions: dict[str, Any],
    co_group_keys: set[tuple[Any, Any, Any, Any, Any, Any]],
    cap_eligible_zips: set[str],
    cap_status: str,
) -> dict[str, Any]:
    hard_gates = assumptions["hard_gates"]
    ranking_weights = assumptions["ranking_weights"]

    quality_reason = _quality_fail_reason(row, co_group_keys)
    quality_pass = quality_reason == ""

    (
        has_private_pool,
        is_private_pool_known,
        private_pool_verified,
        pool_source,
        pool_signal_score,
        pool_signal_conf,
        pool_fail_reason,
    ) = _resolve_private_pool(row, assumptions)
    str_support = _compute_str_support(row, assumptions)
    location_fit = _compute_location_fit(row, assumptions)
    geo_cap_zip, geo_cap_zip_reason = _compute_geo_cap_zip(row, assumptions, cap_eligible_zips, cap_status)

    beds = pd.to_numeric(row.get("beds"), errors="coerce")
    baths = pd.to_numeric(row.get("full_baths"), errors="coerce")
    price = _safe_float(row.get("list_price"), 0.0)

    beds_baths_pass = (
        pd.notna(beds)
        and pd.notna(baths)
        and beds >= float(hard_gates["min_beds"])
        and baths >= float(hard_gates["min_full_baths"])
    )
    price_pass = float(hard_gates["min_list_price"]) <= price <= float(hard_gates["max_list_price"])

    # Balanced pool gate:
    # - Explicitly confirmed private pool always passes.
    # - Unknown private-pool status can pass when inferred pool evidence is strong.
    private_pool_pass = bool(
        private_pool_verified or (has_private_pool and (not is_private_pool_known) and pool_signal_score >= 0.5)
    )

    checks = {
        "quality": quality_pass if hard_gates.get("require_quality", True) else True,
        "str_support": str_support if hard_gates.get("require_str_supported_neighborhood", True) else True,
        "pool": private_pool_pass if hard_gates.get("require_private_pool", True) else True,
        "beds_baths": beds_baths_pass if hard_gates.get("require_beds_baths", True) else True,
        "price_range": price_pass if hard_gates.get("require_price_range", True) else True,
        "location": location_fit if hard_gates.get("require_location", True) else True,
        "geo_cap_zip": geo_cap_zip if hard_gates.get("require_geo_cap_zip", True) else True,
    }

    str_fit_pass = all(checks.values())

    str_fit_score = 0.0
    for key, passed in checks.items():
        if passed:
            str_fit_score += float(ranking_weights.get(key, 0))
    str_fit_score += float(ranking_weights.get("pool_signal", 0)) * float(pool_signal_score)

    pass_messages = {
        "quality": "Listing quality checks passed",
        "str_support": "STR-supported neighborhood confirmed",
        "pool": "Private pool verified",
        "beds_baths": f"Beds/Baths meets {hard_gates['min_beds']}+/{hard_gates['min_full_baths']}+",
        "price_range": f"List price in range [{int(hard_gates['min_list_price'])}, {int(hard_gates['max_list_price'])}]",
        "location": "Preferred location match",
        "geo_cap_zip": "ZIP has neighborhood under STR cap",
    }
    fail_messages = {
        "quality": "Listing quality checks failed",
        "str_support": "Neighborhood is not STR-supported under current cap",
        "pool": "Private pool verification required",
        "beds_baths": f"Beds/Baths below {hard_gates['min_beds']}+/{hard_gates['min_full_baths']}+ threshold",
        "price_range": f"List price outside [{int(hard_gates['min_list_price'])}, {int(hard_gates['max_list_price'])}]",
        "location": "Location outside preferred cities",
        "geo_cap_zip": "ZIP is not in under-cap STR geography",
    }

    reasons_pass: list[str] = []
    reasons_fail: list[str] = []
    for key, passed in checks.items():
        if passed:
            reasons_pass.append(pass_messages[key])
        else:
            reasons_fail.append(fail_messages[key])

    if private_pool_verified:
        reasons_pass.append("Private pool confirmed")
    else:
        reasons_fail.append(pool_fail_reason or "Private pool unknown")

    if not quality_pass and quality_reason:
        reasons_fail.append(quality_reason)

    output = row.to_dict()
    output["quality_pass"] = quality_pass
    output["quality_exclusion_reason"] = quality_reason if quality_reason else pd.NA
    output["eligible_str_supported"] = str_support
    output["has_pool_inferred"] = has_private_pool
    output["has_pool_source"] = pool_source
    output["is_private_pool"] = (
        has_private_pool if "is_private_pool" not in row.index else _safe_bool(row.get("is_private_pool"))
    )
    output["is_private_pool_known"] = (
        is_private_pool_known
        if "is_private_pool_known" not in row.index
        else _safe_bool(row.get("is_private_pool_known"))
    )
    output["private_pool_verified"] = private_pool_verified
    output["eligible_pool"] = private_pool_pass

    output["eligible_beds_baths"] = beds_baths_pass
    output["eligible_price_range"] = price_pass
    output["eligible_location"] = location_fit
    output["eligible_geo_cap_zip"] = geo_cap_zip
    output["geo_cap_zip_reason"] = geo_cap_zip_reason

    output["pool_signal_score"] = pool_signal_score
    output["pool_signal_confidence"] = pool_signal_conf

    output["str_fit_pass"] = str_fit_pass
    output["str_fit_score"] = round(str_fit_score, 2)
    output["str_fit_reasons_pass"] = "; ".join(reasons_pass)
    output["str_fit_reasons_fail"] = "; ".join(reasons_fail)

    output["is_shortlist_candidate"] = False
    output["shortlist_rank"] = pd.NA
    output["shortlist_reason"] = "Not evaluated for shortlist"
    output["is_palm_springs_priority_candidate"] = False
    output["priority_score"] = pd.NA
    output["priority_rank"] = pd.NA
    output["priority_reason_summary"] = "Not evaluated for Palm Springs/Bermuda Dunes/Indio priority ranking"
    return output


def _score_dataframe(rows: pd.DataFrame, assumptions: dict[str, Any]) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame()
    cap_eligible_zips, cap_status = _derive_cap_eligible_zip_codes(assumptions)
    cap_eligible_neighborhoods, cap_nbhd_status = _derive_cap_eligible_neighborhood_keys(assumptions)
    assumptions["_derived_cap_eligible_neighborhood_keys"] = cap_eligible_neighborhoods
    assumptions["_derived_cap_eligible_neighborhood_status"] = cap_nbhd_status
    co_group_keys = _co_ownership_group_keys(rows)
    scored_rows = [
        _score_row(
            row,
            assumptions,
            co_group_keys,
            cap_eligible_zips=cap_eligible_zips,
            cap_status=cap_status,
        )
        for _, row in rows.iterrows()
    ]
    scored_df = pd.DataFrame(scored_rows)
    if scored_df.empty:
        return scored_df
    scored_df["cap_eligible_zip_set"] = ",".join(sorted(cap_eligible_zips)) if cap_eligible_zips else pd.NA
    scored_df["cap_data_status"] = cap_status
    return scored_df


def _build_pool_enrichment_queue(scored_df: pd.DataFrame) -> pd.DataFrame:
    if scored_df.empty:
        return scored_df
    unresolved_pool = ~scored_df.get("private_pool_verified", pd.Series(False, index=scored_df.index)).fillna(
        False
    ).astype(bool) & ~scored_df.get("is_private_pool_known", pd.Series(False, index=scored_df.index)).fillna(
        False
    ).astype(
        bool
    )
    baseline_except_pool = (
        scored_df.get("quality_pass", pd.Series(False, index=scored_df.index)).fillna(False).astype(bool)
        & scored_df.get("eligible_str_supported", pd.Series(False, index=scored_df.index)).fillna(False).astype(bool)
        & scored_df.get("eligible_beds_baths", pd.Series(False, index=scored_df.index)).fillna(False).astype(bool)
        & scored_df.get("eligible_price_range", pd.Series(False, index=scored_df.index)).fillna(False).astype(bool)
        & scored_df.get("eligible_location", pd.Series(False, index=scored_df.index)).fillna(False).astype(bool)
        & scored_df.get("eligible_geo_cap_zip", pd.Series(False, index=scored_df.index)).fillna(False).astype(bool)
    )
    queue_mask = unresolved_pool & baseline_except_pool
    return scored_df[queue_mask].copy()


def _fetch_enriched_pool_rows(queue_df: pd.DataFrame, assumptions: dict[str, Any]) -> pd.DataFrame:
    if queue_df.empty:
        return pd.DataFrame()
    enrichment_cfg = assumptions.get("enrichment_workflow", {})
    listing_type = str(enrichment_cfg.get("listing_type", "for_sale")).strip().lower()
    past_days = int(enrichment_cfg.get("past_days", 365))

    try:
        from homeharvest import scrape_property
    except Exception:
        return pd.DataFrame()

    needed_ids = {str(pid) for pid in queue_df.get("property_id", pd.Series(dtype="object")).astype(str).tolist()}
    needed_address_keys = {_address_key(row) for _, row in queue_df.iterrows()}
    listing_types = [listing_type]
    if listing_type == "for_sale":
        # Fallback for stale inventory in combined snapshots.
        listing_types.extend(["pending", "sold"])
    fetched_rows: list[pd.DataFrame] = []
    for zip_code in sorted(
        {_normalize_zip(z) for z in queue_df.get("zip_code", pd.Series(dtype="object")) if _normalize_zip(z)}
    ):
        for lt in listing_types:
            try:
                fetched = scrape_property(
                    location=zip_code,
                    listing_type=lt,
                    property_type=["single_family"],
                    past_days=past_days,
                    extra_property_data=True,
                )
            except Exception:
                continue
            if fetched.empty:
                continue

            id_mask = fetched.get("property_id", pd.Series(dtype="object")).astype(str).isin(needed_ids)
            if {"street", "city", "state", "zip_code"}.issubset(fetched.columns):
                address_keys = fetched.apply(_address_key, axis=1)
                address_mask = address_keys.isin(needed_address_keys)
            else:
                address_mask = pd.Series(False, index=fetched.index)

            narrowed = fetched[id_mask | address_mask].copy()
            if narrowed.empty:
                continue
            narrowed["enrichment_attempted_at"] = datetime.now(timezone.utc).isoformat()
            narrowed["enrichment_source"] = f"homeharvest.scrape_property:{lt}"
            narrowed["enrichment_round"] = 2
            fetched_rows.append(narrowed)

    if not fetched_rows:
        return pd.DataFrame()
    all_fetched = pd.concat(fetched_rows, ignore_index=True)
    return all_fetched.drop_duplicates(subset=["property_id"], keep="last").copy()


def _apply_enrichment_updates(rows: pd.DataFrame, enriched_rows: pd.DataFrame) -> pd.DataFrame:
    if (
        rows.empty
        or enriched_rows.empty
        or "property_id" not in rows.columns
        or "property_id" not in enriched_rows.columns
    ):
        return rows
    updated = rows.copy()
    update_cols = [c for c in enriched_rows.columns if c in updated.columns or c.startswith("enrichment_")]
    for _, enriched_row in enriched_rows.iterrows():
        pid = str(enriched_row.get("property_id"))
        mask = updated["property_id"].astype(str) == pid
        if not mask.any():
            continue
        for col in update_cols:
            updated.loc[mask, col] = enriched_row.get(col)
    return updated


def _attach_pool_enrichment_status(
    scored_df: pd.DataFrame,
    queue_df: pd.DataFrame,
    enriched_rows: pd.DataFrame,
) -> pd.DataFrame:
    if scored_df.empty:
        return scored_df
    result = scored_df.copy()
    for col in ("enrichment_attempted_at", "enrichment_source", "enrichment_round"):
        if col not in result.columns:
            result[col] = pd.NA
    queue_ids = {str(pid) for pid in queue_df.get("property_id", pd.Series(dtype="object")).astype(str).tolist()}
    refreshed_ids = {
        str(pid) for pid in enriched_rows.get("property_id", pd.Series(dtype="object")).astype(str).tolist()
    }

    result["pool_enrichment_needed"] = result["property_id"].astype(str).map(lambda pid: pid in queue_ids)
    result["pool_enrichment_attempted"] = result["property_id"].astype(str).map(lambda pid: pid in queue_ids)
    result["pool_enrichment_result"] = "not_needed"
    needed_mask = result["pool_enrichment_needed"].fillna(False).astype(bool)
    refreshed_mask = result["property_id"].astype(str).map(lambda pid: pid in refreshed_ids)
    result.loc[needed_mask, "pool_enrichment_result"] = "attempted_no_data"
    verified_mask = result.get("private_pool_verified", pd.Series(False, index=result.index)).fillna(False).astype(bool)
    still_unknown_mask = (
        needed_mask
        & refreshed_mask
        & ~verified_mask
        & ~result.get("is_private_pool_known", pd.Series(False, index=result.index)).fillna(False).astype(bool)
    )
    resolved_not_private_mask = (
        needed_mask
        & refreshed_mask
        & ~verified_mask
        & result.get("is_private_pool_known", pd.Series(False, index=result.index)).fillna(False).astype(bool)
    )
    result.loc[needed_mask & refreshed_mask & verified_mask, "pool_enrichment_result"] = "verified_after_enrichment"
    result.loc[still_unknown_mask, "pool_enrichment_result"] = "still_unknown"
    result.loc[resolved_not_private_mask, "pool_enrichment_result"] = "resolved_not_private"
    return result


def _load_coc_scores(df: pd.DataFrame, assumptions: dict[str, Any]) -> pd.DataFrame:
    shortlist_cfg = assumptions.get("shortlist", {})
    metric = str(shortlist_cfg.get("ranking_metric", "coc_med"))

    if metric in df.columns and df[metric].notna().any():
        return df

    coc_assumptions_path = Path(str(shortlist_cfg.get("coc_assumptions_path", DEFAULT_COC_ASSUMPTIONS_PATH)))
    if not coc_assumptions_path.exists():
        return df

    examples_dir = str((Path(__file__).resolve().parent))
    if examples_dir not in sys.path:
        sys.path.insert(0, examples_dir)

    try:
        import coc_scorecard as coc
    except Exception:
        return df

    try:
        with coc_assumptions_path.open("r", encoding="utf-8") as fh:
            coc_assumptions = json.load(fh)
        scored = coc.score_properties(df.copy(), coc_assumptions, require_str_fit=False)
    except Exception:
        return df

    if scored.empty or "property_id" not in scored.columns:
        return df

    merge_cols = ["property_id", "coc_low", "coc_med", "coc_high", "annual_cash_flow_med"]
    available = [c for c in merge_cols if c in scored.columns]
    scored_small = scored[available].copy()
    return df.merge(scored_small, on="property_id", how="left", suffixes=("", "_calc"))


def _apply_shortlist(df: pd.DataFrame, assumptions: dict[str, Any]) -> pd.DataFrame:
    shortlist_cfg = assumptions.get("shortlist", {})
    if not shortlist_cfg.get("enabled", True) or df.empty:
        return df

    working = df.copy()
    eligible_mask = working["str_fit_pass"].fillna(False).astype(bool)
    eligible_count = int(eligible_mask.sum())
    if eligible_count == 0:
        working["is_shortlist_candidate"] = False
        working["shortlist_rank"] = pd.NA
        working["shortlist_reason"] = "No Stage-1 eligible listings"
        return working

    min_rate = float(shortlist_cfg.get("target_pass_rate_min", 0.10))
    max_rate = float(shortlist_cfg.get("target_pass_rate_max", 0.20))
    target_rate = float(shortlist_cfg.get("target_pass_rate_target", (min_rate + max_rate) / 2.0))

    min_count = max(1, int(math.ceil(eligible_count * min_rate)))
    max_count = max(min_count, int(math.floor(eligible_count * max_rate)))
    target_count = int(round(eligible_count * target_rate))
    target_count = max(min_count, min(max_count, max(1, target_count)))

    ranking_metric = str(shortlist_cfg.get("ranking_metric", "coc_med"))
    direction = str(shortlist_cfg.get("ranking_direction", "desc")).strip().lower()

    metric = pd.to_numeric(working.get(ranking_metric), errors="coerce")
    if metric.notna().sum() == 0:
        ranking_metric = "str_fit_score"
        metric = pd.to_numeric(working.get("str_fit_score"), errors="coerce")
        direction = "desc"

    eligible = working[eligible_mask].copy()
    eligible["_metric"] = metric[eligible_mask]

    if direction == "asc":
        eligible = eligible.sort_values(
            ["_metric", "str_fit_score", "property_id"], ascending=[True, False, True], kind="mergesort"
        )
    else:
        eligible = eligible.sort_values(
            ["_metric", "str_fit_score", "property_id"], ascending=[False, False, True], kind="mergesort"
        )

    shortlisted_ids = eligible.head(target_count)["property_id"].astype(str).tolist()
    id_to_rank = {pid: idx + 1 for idx, pid in enumerate(shortlisted_ids)}

    working["is_shortlist_candidate"] = working["property_id"].astype(str).map(lambda pid: pid in id_to_rank)
    working["shortlist_rank"] = working["property_id"].astype(str).map(id_to_rank)

    shortlist_note = (
        f"Top {target_count} by {ranking_metric} among {eligible_count} Stage-1 eligible listings "
        f"(target band {int(min_rate * 100)}-{int(max_rate * 100)}%)."
    )
    working["shortlist_reason"] = "Outside shortlist cutoff"
    working.loc[working["is_shortlist_candidate"].fillna(False).astype(bool), "shortlist_reason"] = shortlist_note
    working.loc[~eligible_mask, "shortlist_reason"] = "Not Stage-1 eligible"

    return working


def _norm_series(series: pd.Series, *, inverse: bool = False) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    min_val = values.min(skipna=True)
    max_val = values.max(skipna=True)
    if pd.isna(min_val) or pd.isna(max_val) or min_val == max_val:
        base = pd.Series(0.5, index=series.index, dtype="float64")
    else:
        base = (values - float(min_val)) / float(max_val - min_val)
        base = base.fillna(0.5)
    return 1.0 - base if inverse else base


def _resolve_neighborhood_support_metric(df: pd.DataFrame) -> pd.Series:
    candidates = (
        "str_nbhd_capacity_remaining_ratio",
        "str_nbhd_remaining_capacity_ratio",
        "str_nbhd_capacity_ratio",
        "str_nbhd_support_score",
        "str_nbhd_under_cap_current",
        "eligible_str_supported",
        "eligible_geo_cap_zip",
    )
    for col in candidates:
        if col in df.columns:
            return pd.to_numeric(df[col], errors="coerce")
    return pd.Series(0.0, index=df.index, dtype="float64")


def _priority_reason(row: pd.Series) -> str:
    parts: list[str] = []
    ppsf_score = _safe_float(row.get("_priority_ppsf_component"))
    lot_score = _safe_float(row.get("_priority_lot_component"))
    nbhd_score = _safe_float(row.get("_priority_nbhd_component"))
    if ppsf_score >= 0.6:
        parts.append("attractive price per sqft")
    if lot_score >= 0.6:
        parts.append("strong lot-size utility")
    if nbhd_score >= 0.6:
        parts.append("favorable under-cap STR neighborhood support")
    if not parts:
        parts.append("balanced value profile across STR factors")
    return "Ranked high for " + ", ".join(parts[:2]) + "."


def _apply_palm_springs_priority(df: pd.DataFrame, assumptions: dict[str, Any]) -> pd.DataFrame:
    priority_cfg = assumptions.get("priority_ranking", {})
    if not priority_cfg.get("enabled", True) or df.empty:
        return df

    working = df.copy()
    region_label = (
        _safe_str(
            priority_cfg.get("region_label"),
            "Palm Springs • Bermuda Dunes • Indio",
        ).strip()
        or "Palm Springs • Bermuda Dunes • Indio"
    )

    target_cities_cfg = priority_cfg.get("target_cities", [])
    target_cities: list[str] = []
    if isinstance(target_cities_cfg, list):
        target_cities = [str(c).strip().lower() for c in target_cities_cfg if str(c).strip()]
    target_city_fallback = str(priority_cfg.get("target_city", "")).strip().lower()
    if not target_cities:
        if target_city_fallback in {"coachella valley", "coachella_valley", "coachella-valley", "all", "*"}:
            target_cities = [
                str(c).strip().lower()
                for c in assumptions.get("location", {}).get("preferred_cities", [])
                if str(c).strip()
            ]
        elif target_city_fallback:
            target_cities = [target_city_fallback]

    city_series = working.get("city", pd.Series("", index=working.index)).astype(str).str.strip().str.lower()
    in_city = city_series.isin(set(target_cities)) if target_cities else pd.Series(True, index=working.index)
    for_sale = (
        working.get("status", pd.Series("", index=working.index)).astype(str).str.strip().str.upper().eq("FOR_SALE")
        if priority_cfg.get("require_for_sale_status", True)
        else pd.Series(True, index=working.index)
    )
    strict_pass = (
        working.get("str_fit_pass", pd.Series(False, index=working.index)).fillna(False).astype(bool)
        if priority_cfg.get("require_str_fit_pass", True)
        else pd.Series(True, index=working.index)
    )
    strict_components = (
        working.get("quality_pass", pd.Series(False, index=working.index)).fillna(False).astype(bool)
        & working.get("eligible_str_supported", pd.Series(False, index=working.index)).fillna(False).astype(bool)
        & working.get("eligible_geo_cap_zip", pd.Series(False, index=working.index)).fillna(False).astype(bool)
        & working.get("private_pool_verified", pd.Series(False, index=working.index)).fillna(False).astype(bool)
    )

    candidate_mask = in_city & for_sale & strict_pass & strict_components
    working["is_palm_springs_priority_candidate"] = candidate_mask
    working["priority_score"] = pd.NA
    working["priority_rank"] = pd.NA
    working["priority_reason_summary"] = f"Not eligible for {region_label} priority ranking"

    if not candidate_mask.any():
        return working

    candidates = working[candidate_mask].copy()
    list_price = pd.to_numeric(candidates.get("list_price"), errors="coerce")
    sqft = pd.to_numeric(candidates.get("sqft"), errors="coerce")
    candidates["_priority_price_per_sqft"] = (list_price / sqft).where(sqft > 0)
    candidates["_priority_ppsf_component"] = _norm_series(candidates["_priority_price_per_sqft"], inverse=True)
    candidates["_priority_lot_component"] = _norm_series(candidates.get("lot_sqft", pd.Series(index=candidates.index)))
    candidates["_priority_nbhd_component"] = _norm_series(_resolve_neighborhood_support_metric(candidates))

    weights = priority_cfg.get("factor_weights", {})
    ppsf_w = _safe_float(weights.get("price_per_sqft"), 0.40)
    lot_w = _safe_float(weights.get("lot_size"), 0.25)
    nbhd_w = _safe_float(weights.get("neighborhood_support"), 0.35)
    candidates["priority_score"] = (
        (ppsf_w * candidates["_priority_ppsf_component"])
        + (lot_w * candidates["_priority_lot_component"])
        + (nbhd_w * candidates["_priority_nbhd_component"])
    )

    coc_post_tax = pd.to_numeric(
        candidates.get("coc_post_tax", pd.Series(index=candidates.index, dtype="float64")),
        errors="coerce",
    )
    coc_pre_tax = pd.to_numeric(
        candidates.get("coc_pre_tax", pd.Series(index=candidates.index, dtype="float64")),
        errors="coerce",
    )
    coc_tie_break = coc_post_tax.fillna(coc_pre_tax).fillna(0.0)
    candidates["_priority_coc_tie_break"] = coc_tie_break

    candidates = candidates.sort_values(
        by=["priority_score", "_priority_coc_tie_break", "property_id"],
        ascending=[False, False, True],
        kind="mergesort",
    )
    candidates["priority_rank"] = range(1, len(candidates) + 1)
    candidates["priority_reason_summary"] = candidates.apply(_priority_reason, axis=1)

    update_cols = ["priority_score", "priority_rank", "priority_reason_summary", "is_palm_springs_priority_candidate"]
    for col in update_cols:
        working.loc[candidate_mask, col] = candidates[col]
    return working


def evaluate_str_fit(df: pd.DataFrame, assumptions: dict[str, Any]) -> pd.DataFrame:
    assumptions = _normalize_assumptions(assumptions)
    rows = df.copy()
    if "status" in rows.columns:
        rows = rows[rows["status"].astype(str).str.upper() == "FOR_SALE"].copy()

    required = ["property_id", "list_price", "street", "city", "state", "zip_code", "beds", "full_baths", "sqft"]
    for col in required:
        if col not in rows.columns:
            rows[col] = pd.NA

    rows = rows[rows["property_id"].notna()].copy()

    if "property_id" in rows.columns:
        sort_cols = [c for c in ["batch_run_at", "list_date"] if c in rows.columns]
        if sort_cols:
            rows = rows.sort_values(by=sort_cols, ascending=True, kind="mergesort")
        rows = rows.drop_duplicates(subset=["property_id"], keep="last").copy()
    scored_df = _score_dataframe(rows, assumptions)
    if scored_df.empty:
        return scored_df

    queue_df = _build_pool_enrichment_queue(scored_df)
    queue_df_stage1 = queue_df.copy()
    enriched_rows = pd.DataFrame()
    if assumptions.get("enrichment_workflow", {}).get("enabled", False) and not queue_df.empty:
        enriched_rows = _fetch_enriched_pool_rows(queue_df, assumptions)
        if not enriched_rows.empty:
            rows = _apply_enrichment_updates(rows, enriched_rows)
            scored_df = _score_dataframe(rows, assumptions)
            queue_df = _build_pool_enrichment_queue(scored_df)

    scored_df = _attach_pool_enrichment_status(scored_df, queue_df_stage1, enriched_rows)

    scored_df = _load_coc_scores(scored_df, assumptions)
    scored_df = _apply_shortlist(scored_df, assumptions)
    scored_df = _apply_palm_springs_priority(scored_df, assumptions)

    scored_df["_priority_rank_num"] = pd.to_numeric(scored_df.get("priority_rank"), errors="coerce").fillna(10**9)
    sort_cols = [
        "is_palm_springs_priority_candidate",
        "_priority_rank_num",
        "is_shortlist_candidate",
        "str_fit_pass",
        "str_fit_score",
        "property_id",
    ]
    ascending = [False, True, False, False, False, True]
    scored_df = scored_df.sort_values(by=sort_cols, ascending=ascending, kind="mergesort").reset_index(drop=True)
    return scored_df.drop(columns=["_priority_rank_num"])


def assumptions_to_df(assumptions: dict[str, Any]) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for section, payload in assumptions.items():
        if isinstance(payload, dict):
            for key, value in payload.items():
                records.append(
                    {
                        "section": section,
                        "key": key,
                        "value": json.dumps(value) if isinstance(value, (dict, list)) else value,
                    }
                )
        else:
            records.append({"section": "root", "key": section, "value": payload})
    return pd.DataFrame(records)


def write_scorecard(scored_df: pd.DataFrame, assumptions: dict[str, Any], output_path: str | Path, top_n: int) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fit_df = (
        scored_df[scored_df["str_fit_pass"].fillna(False).astype(bool)].copy() if not scored_df.empty else scored_df
    )
    top_df = fit_df.head(top_n).copy() if not fit_df.empty else fit_df
    assumptions_df = assumptions_to_df(assumptions)

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        top_df.to_excel(writer, index=False, sheet_name="Top_STR_Suitable")
        fit_df.to_excel(writer, index=False, sheet_name="STR_Suitable_Only")
        scored_df.to_excel(writer, index=False, sheet_name="All_Listings")
        assumptions_df.to_excel(writer, index=False, sheet_name="Assumptions")


def main() -> None:
    args = parse_args()
    assumptions = load_assumptions(args.assumptions)
    df = pd.read_excel(args.input)
    scored_df = evaluate_str_fit(df, assumptions)
    write_scorecard(scored_df, assumptions, args.output, args.top_n)

    fit_count = int(scored_df["str_fit_pass"].fillna(False).astype(bool).sum()) if not scored_df.empty else 0
    shortlist_count = int(
        scored_df.get("is_shortlist_candidate", pd.Series(dtype="bool")).fillna(False).astype(bool).sum()
    )
    verified_count = int(
        scored_df.get("private_pool_verified", pd.Series(dtype="bool")).fillna(False).astype(bool).sum()
    )
    known_false_count = int(
        (
            scored_df.get("is_private_pool_known", pd.Series(dtype="bool")).fillna(False).astype(bool)
            & ~scored_df.get("is_private_pool", pd.Series(dtype="bool")).fillna(False).astype(bool)
        ).sum()
    )
    community_only_count = int(
        scored_df.get("pool_community_only", pd.Series(dtype="bool")).fillna(False).astype(bool).sum()
    )
    conflict_count = int(scored_df.get("pool_conflict", pd.Series(dtype="bool")).fillna(False).astype(bool).sum())
    unknown_count = int(
        (~scored_df.get("is_private_pool_known", pd.Series(dtype="bool")).fillna(False).astype(bool)).sum()
    )
    verified_coverage = (verified_count / len(scored_df)) if len(scored_df) else 0.0
    pool_verification_cfg = assumptions.get("pool_verification", {})
    min_verified_coverage_warn = float(pool_verification_cfg.get("min_verified_coverage_warn", 0.05))
    fail_on_low_verified_coverage = bool(pool_verification_cfg.get("fail_on_low_verified_coverage", False))
    coverage_line = (
        f"Private pool verified rows: {verified_count} ({verified_coverage:.2%} coverage of for-sale evaluated rows)"
    )
    low_coverage_warn = verified_coverage < min_verified_coverage_warn
    print(
        f"Input rows: {len(df)}\n"
        f"For-sale evaluated rows: {len(scored_df)}\n"
        f"STR-fit pass rows (Stage 1): {fit_count}\n"
        f"Shortlist rows (Stage 2): {shortlist_count}\n"
        f"{coverage_line}\n"
        f"Pool state counts: private_pool_known_false={known_false_count}; "
        f"community_only={community_only_count}; conflict={conflict_count}; unknown={unknown_count}\n"
        f"Output workbook: {Path(args.output).resolve()}"
    )
    if low_coverage_warn:
        warning = (
            "[pool-verification-coverage-warning] "
            f"Coverage {verified_coverage:.2%} is below configured threshold {min_verified_coverage_warn:.2%}."
        )
        print(warning)
        if fail_on_low_verified_coverage:
            raise RuntimeError(warning)


if __name__ == "__main__":
    main()

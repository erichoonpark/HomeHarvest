from __future__ import annotations

import argparse
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
POOL_COLUMNS = (
    "is_private_pool",
    "is_private_pool_known",
    "pool_type",
    "pool_available",
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

    hard_gates = raw.get("hard_gates", {})
    if not hard_gates:
        hard_gates = {
            "require_quality": True,
            "require_str_supported_neighborhood": bool(requirements.get("require_str_supported_neighborhood", True)),
            "require_price_range": True,
            "require_beds_baths": True,
            "require_location": bool(location.get("enabled", True)),
            "require_geo_cap_zip": True,
            "min_beds": int(thresholds.get("min_beds", 2)),
            "min_full_baths": int(thresholds.get("min_full_baths", 2)),
            "min_list_price": float(thresholds.get("min_list_price", 100000)),
            "max_list_price": float(thresholds.get("max_list_price", 3000000)),
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
        }

    normalized_location = {
        "enabled": bool(location.get("enabled", True)),
        "preferred_cities": list(location.get("preferred_cities", ["Palm Springs", "Indio", "Bermuda Dunes"])),
        "scope_zip_candidates": list(
            location.get("scope_zip_candidates", ["92258", "92262", "92263", "92264", "92201", "92203"])
        ),
    }

    return {
        "hard_gates": hard_gates,
        "location": normalized_location,
        "geography": geography,
        "ranking_weights": ranking_weights,
        "shortlist": shortlist,
        # Keep legacy sections for compatibility/audit sheets.
        "thresholds": {
            "min_beds": hard_gates["min_beds"],
            "min_full_baths": hard_gates["min_full_baths"],
            "min_list_price": hard_gates["min_list_price"],
            "max_list_price": hard_gates["max_list_price"],
        },
        "requirements": {
            "require_str_supported_neighborhood": hard_gates["require_str_supported_neighborhood"],
            "require_pool": False,
            "exclude_unknown_private_pool": False,
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


def _infer_pool(row: pd.Series) -> tuple[bool, str]:
    for column in POOL_COLUMNS:
        if column not in row.index:
            continue
        value = row.get(column)
        if isinstance(value, bool):
            return value, column
        if isinstance(value, (int, float)) and pd.notna(value):
            return bool(value > 0), column
        text = f" {_safe_str(value).strip().lower()} "
        if any(keyword in text for keyword in POOL_KEYWORDS):
            return True, column

    for column in ("street", "property_url", "neighborhoods"):
        text = f" {_safe_str(row.get(column)).strip().lower()} "
        if any(keyword in text for keyword in POOL_KEYWORDS):
            return True, column
    return False, "none"


def _resolve_private_pool(row: pd.Series) -> tuple[bool, bool, str, float, str]:
    if "is_private_pool" in row.index and "is_private_pool_known" in row.index:
        is_private_pool = _safe_bool(row.get("is_private_pool"))
        is_private_pool_known = _safe_bool(row.get("is_private_pool_known"))
        source = "canonical"
    else:
        inferred_pool, source = _infer_pool(row)
        is_private_pool = inferred_pool
        is_private_pool_known = False

    if is_private_pool_known and is_private_pool:
        return True, True, source, 1.0, "high"
    if is_private_pool_known and not is_private_pool:
        return False, True, source, 0.0, "high"

    inferred_pool, inferred_source = _infer_pool(row)
    if inferred_pool:
        return False, False, f"{source}|{inferred_source}", 0.5, "medium"
    return False, False, f"{source}:unknown_private_pool", 0.0, "low"


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
    if assumptions["hard_gates"].get("require_str_supported_neighborhood", True):
        return under_cap
    return True


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
            return True, f"cap_data_unavailable:{cap_status}:fail_open"
        return False, f"cap_data_unavailable:{cap_status}:fail_closed"

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

    has_private_pool, is_private_pool_known, pool_source, pool_signal_score, pool_signal_conf = _resolve_private_pool(
        row
    )
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

    checks = {
        "quality": quality_pass if hard_gates.get("require_quality", True) else True,
        "str_support": str_support if hard_gates.get("require_str_supported_neighborhood", True) else True,
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
        "beds_baths": f"Beds/Baths meets {hard_gates['min_beds']}+/{hard_gates['min_full_baths']}+",
        "price_range": f"List price in range [{int(hard_gates['min_list_price'])}, {int(hard_gates['max_list_price'])}]",
        "location": "Preferred location match",
        "geo_cap_zip": "ZIP has neighborhood under STR cap",
    }
    fail_messages = {
        "quality": "Listing quality checks failed",
        "str_support": "Neighborhood is not STR-supported under current cap",
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

    if has_private_pool:
        reasons_pass.append("Private pool confirmed")
    elif is_private_pool_known:
        reasons_fail.append("Private pool not present")
    else:
        reasons_fail.append("Private pool unknown")

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
    # Backward-compatible; no longer a hard gate.
    output["eligible_pool"] = has_private_pool

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
    return output


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


def evaluate_str_fit(df: pd.DataFrame, assumptions: dict[str, Any]) -> pd.DataFrame:
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

    cap_eligible_zips, cap_status = _derive_cap_eligible_zip_codes(assumptions)
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

    scored_df = _load_coc_scores(scored_df, assumptions)
    scored_df = _apply_shortlist(scored_df, assumptions)

    sort_cols = ["is_shortlist_candidate", "str_fit_pass", "str_fit_score", "property_id"]
    ascending = [False, False, False, True]
    return scored_df.sort_values(by=sort_cols, ascending=ascending, kind="mergesort").reset_index(drop=True)


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
    print(
        f"Input rows: {len(df)}\n"
        f"For-sale evaluated rows: {len(scored_df)}\n"
        f"STR-fit pass rows (Stage 1): {fit_count}\n"
        f"Shortlist rows (Stage 2): {shortlist_count}\n"
        f"Output workbook: {Path(args.output).resolve()}"
    )


if __name__ == "__main__":
    main()

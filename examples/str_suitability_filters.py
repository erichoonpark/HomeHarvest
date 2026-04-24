from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_INPUT_PATH = Path("examples/zips/combined.xlsx")
DEFAULT_OUTPUT_PATH = Path("examples/zips/str_suitability_filter.xlsx")
DEFAULT_ASSUMPTIONS_PATH = Path("examples/data/str_suitability_filters.json")

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
        return json.load(f)


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


def _address_key(row: pd.Series) -> tuple[str, str, str, str]:
    return (
        _safe_str(row.get("street")).strip().lower(),
        _safe_str(row.get("city")).strip().lower(),
        _safe_str(row.get("state")).strip().lower(),
        _safe_str(row.get("zip_code")).strip(),
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


def _resolve_private_pool(row: pd.Series, assumptions: dict[str, Any]) -> tuple[bool, bool, str]:
    requirements = assumptions.get("requirements", {})
    exclude_unknown = bool(requirements.get("exclude_unknown_private_pool", True))

    if "is_private_pool" in row.index and "is_private_pool_known" in row.index:
        is_private_pool = _safe_bool(row.get("is_private_pool"))
        is_private_pool_known = _safe_bool(row.get("is_private_pool_known"))
        source = "canonical"
    else:
        has_pool, source = _infer_pool(row)
        is_private_pool = has_pool
        is_private_pool_known = False

    if exclude_unknown and not is_private_pool_known:
        return False, is_private_pool_known, f"{source}:unknown_private_pool"
    return bool(is_private_pool), bool(is_private_pool_known), source


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
    if assumptions["requirements"].get("require_str_supported_neighborhood", True):
        return under_cap
    return True


def _compute_location_fit(row: pd.Series, assumptions: dict[str, Any]) -> bool:
    location_cfg = assumptions.get("location", {})
    if not location_cfg.get("enabled", False):
        return True
    preferred = {str(city).strip().lower() for city in location_cfg.get("preferred_cities", [])}
    return _safe_str(row.get("city")).strip().lower() in preferred


def _score_row(
    row: pd.Series, assumptions: dict[str, Any], co_group_keys: set[tuple[Any, Any, Any, Any, Any, Any]]
) -> dict[str, Any]:
    thresholds = assumptions["thresholds"]
    weights = assumptions["scoring_weights"]

    quality_reason = _quality_fail_reason(row, co_group_keys)
    quality_pass = quality_reason == ""
    has_pool, is_private_pool_known, pool_source = _resolve_private_pool(row, assumptions)
    str_support = _compute_str_support(row, assumptions)
    location_fit = _compute_location_fit(row, assumptions)

    beds = pd.to_numeric(row.get("beds"), errors="coerce")
    baths = pd.to_numeric(row.get("full_baths"), errors="coerce")
    price = _safe_float(row.get("list_price"), 0.0)

    beds_baths_pass = (
        pd.notna(beds) and pd.notna(baths) and beds >= thresholds["min_beds"] and baths >= thresholds["min_full_baths"]
    )
    price_pass = thresholds["min_list_price"] <= price <= thresholds["max_list_price"]
    pool_pass = has_pool if assumptions["requirements"].get("require_pool", True) else True

    checks = {
        "quality": quality_pass,
        "str_support": str_support,
        "pool": pool_pass,
        "beds_baths": beds_baths_pass,
        "price_range": price_pass,
        "location": location_fit,
    }

    str_fit_pass = all(checks.values())
    str_fit_score = int(sum(weights.get(key, 0) for key, passed in checks.items() if passed))

    reasons_pass: list[str] = []
    reasons_fail: list[str] = []
    reason_map = {
        "quality": "Listing quality checks passed",
        "str_support": "STR-supported neighborhood",
        "pool": "Private pool requirement met",
        "beds_baths": f"Beds/Baths meets {thresholds['min_beds']}+/{thresholds['min_full_baths']}+",
        "price_range": f"List price in range [{thresholds['min_list_price']}, {thresholds['max_list_price']}]",
        "location": "Preferred location match",
    }
    for key, passed in checks.items():
        if passed:
            reasons_pass.append(reason_map[key])
        else:
            reasons_fail.append(reason_map[key])
    if not quality_pass and quality_reason:
        reasons_fail.append(quality_reason)

    output = row.to_dict()
    output["quality_pass"] = quality_pass
    output["quality_exclusion_reason"] = quality_reason if quality_reason else pd.NA
    output["eligible_str_supported"] = str_support
    output["has_pool_inferred"] = has_pool
    output["has_pool_source"] = pool_source
    output["is_private_pool"] = _safe_bool(row.get("is_private_pool")) if "is_private_pool" in row.index else has_pool
    output["is_private_pool_known"] = (
        _safe_bool(row.get("is_private_pool_known")) if "is_private_pool_known" in row.index else is_private_pool_known
    )
    output["eligible_pool"] = pool_pass
    output["eligible_beds_baths"] = beds_baths_pass
    output["eligible_price_range"] = price_pass
    output["eligible_location"] = location_fit
    output["str_fit_pass"] = str_fit_pass
    output["str_fit_score"] = str_fit_score
    output["str_fit_reasons_pass"] = "; ".join(reasons_pass)
    output["str_fit_reasons_fail"] = "; ".join(reasons_fail)
    return output


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

    co_group_keys = _co_ownership_group_keys(rows)
    scored_rows = [_score_row(row, assumptions, co_group_keys) for _, row in rows.iterrows()]
    scored_df = pd.DataFrame(scored_rows)
    if scored_df.empty:
        return scored_df
    return scored_df.sort_values(
        by=["str_fit_score", "property_id"], ascending=[False, True], kind="mergesort"
    ).reset_index(drop=True)


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
    print(
        f"Input rows: {len(df)}\n"
        f"For-sale evaluated rows: {len(scored_df)}\n"
        f"STR-fit pass rows: {fit_count}\n"
        f"Output workbook: {Path(args.output).resolve()}"
    )


if __name__ == "__main__":
    main()

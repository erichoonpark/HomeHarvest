from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_INPUT_PATH = Path("examples/zips/str_suitability_filter.xlsx")
DEFAULT_OUTPUT_PATH = Path("examples/zips/coc_scorecard.xlsx")
DEFAULT_ASSUMPTIONS_PATH = Path("examples/data/coc_assumptions.json")
MIN_VALID_HOME_PRICE = 100000
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


@dataclass(frozen=True)
class ScenarioAssumptions:
    adr: float
    occupancy_rate: float


@dataclass(frozen=True)
class FinancingAssumptions:
    down_payment_pct: float
    interest_rate_annual: float
    loan_term_years: int


@dataclass(frozen=True)
class CostModelAssumptions:
    closing_cost_pct: float
    furnishing_pct: float
    rehab_reserve_pct: float
    initial_reserve_pct: float
    management_fee_pct: float
    capex_pct: float
    maintenance_pct: float
    vacancy_buffer_pct: float
    turnover_buffer_pct: float
    insurance_rate_pct_annual: float
    property_tax_rate_pct_annual: float
    utilities_monthly: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate COC scorecard from STR suitability-filtered listings")
    parser.add_argument("--input", default=str(DEFAULT_INPUT_PATH), help="Input listings workbook path")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="Output scorecard workbook path")
    parser.add_argument("--top-n", type=int, default=25, help="Top N rows for scorecard ranking")
    parser.add_argument(
        "--assumptions",
        default=str(DEFAULT_ASSUMPTIONS_PATH),
        help="JSON assumptions path for financing, costs, and scenario presets",
    )
    parser.add_argument(
        "--run-all",
        action="store_true",
        help="Score all for-sale rows, ignoring str_fit_pass gate (audit mode).",
    )
    return parser.parse_args()


def load_assumptions(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        raw = json.load(f)

    return raw


def load_input_rows(path: str | Path) -> pd.DataFrame:
    workbook = Path(path)
    if not workbook.exists():
        raise FileNotFoundError(f"Input workbook not found: {workbook}")
    if workbook.suffix.lower() in {".xlsx", ".xls"}:
        excel = pd.ExcelFile(workbook)
        if "All_Listings" in excel.sheet_names:
            return pd.read_excel(workbook, sheet_name="All_Listings")
        if "All_Scored" in excel.sheet_names:
            return pd.read_excel(workbook, sheet_name="All_Scored")
    return pd.read_excel(workbook)


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "t"}:
        return True
    if text in {"0", "false", "no", "n", "f"}:
        return False
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return default


def _contains_excluded_address_keyword(street: Any) -> bool:
    value = f" {str(street or '').strip().lower()} "
    return any(keyword in value for keyword in ADDRESS_EXCLUDE_KEYWORDS)


def _address_key(row: pd.Series) -> tuple[str, str, str, str]:
    return (
        str(row.get("street", "")).strip().lower(),
        str(row.get("city", "")).strip().lower(),
        str(row.get("state", "")).strip().lower(),
        str(row.get("zip_code", "")).strip(),
    )


def _is_manually_excluded_row(row: pd.Series) -> bool:
    property_id = str(row.get("property_id", "") or "").strip()
    if property_id and property_id in MANUAL_EXCLUDED_PROPERTY_IDS:
        return True
    return _address_key(row) in MANUAL_EXCLUDED_ADDRESSES


def _contains_co_ownership_keyword(value: Any) -> bool:
    normalized = f" {str(value or '').strip().lower()} "
    return any(keyword in normalized for keyword in CO_OWNERSHIP_KEYWORDS)


def _has_unit_designator(street: Any) -> bool:
    normalized = str(street or "").strip().lower()
    return any(token in normalized for token in UNIT_ADDRESS_TOKENS)


def _looks_like_variant_share_listing(street: Any, property_url: Any) -> bool:
    street_text = str(street or "").strip().lower()
    url_text = str(property_url or "").strip().lower()
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
    street = row.get("street")
    property_url = row.get("property_url")
    return (
        _contains_co_ownership_keyword(street)
        or _contains_co_ownership_keyword(property_url)
        or _looks_like_variant_share_listing(street, property_url)
    )


def _co_ownership_group_keys(df: pd.DataFrame) -> set[tuple[Any, Any, Any, Any, Any, Any]]:
    required = {"street", "city", "zip_code", "beds", "full_baths", "sqft", "property_id"}
    if not required.issubset(df.columns):
        return set()
    if df.empty:
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


def _co_ownership_cluster_mask(df: pd.DataFrame, co_group_keys: set[tuple[Any, Any, Any, Any, Any, Any]]) -> pd.Series:
    key_cols = ["street", "city", "zip_code", "beds", "full_baths", "sqft"]
    if df.empty or not co_group_keys or any(col not in df.columns for col in key_cols):
        return pd.Series(False, index=df.index)
    keys = df[key_cols].apply(lambda row: tuple(row.values.tolist()), axis=1)
    return keys.isin(co_group_keys)


def _is_valid_home_row(row: pd.Series, min_price: int = MIN_VALID_HOME_PRICE) -> bool:
    price = _safe_float(row.get("list_price"), 0.0)
    beds = pd.to_numeric(row.get("beds"), errors="coerce")
    baths = pd.to_numeric(row.get("full_baths"), errors="coerce")
    sqft = pd.to_numeric(row.get("sqft"), errors="coerce")
    if price < float(min_price):
        return False
    if _is_manually_excluded_row(row):
        return False
    if _contains_excluded_address_keyword(row.get("street")):
        return False
    if _is_probable_co_ownership_row(row):
        return False
    if pd.isna(beds) and pd.isna(baths) and pd.isna(sqft):
        return False
    return True


def mortgage_payment(principal: float, annual_rate: float, term_years: int) -> float:
    if principal <= 0:
        return 0.0
    months = max(1, term_years * 12)
    monthly_rate = annual_rate / 12
    if monthly_rate == 0:
        return principal / months
    factor = (1 + monthly_rate) ** months
    return principal * (monthly_rate * factor) / (factor - 1)


def choose_scenario_tier(row: pd.Series, luxury_threshold: float) -> str:
    city = str(row.get("city", "")).strip().lower()
    price = _safe_float(row.get("list_price"), 0.0)
    if city == "palm springs":
        return "palm_springs_luxury" if price >= luxury_threshold else "palm_springs_normal"
    return "fallback"


def _scenario_for(row: pd.Series, scenario_name: str, assumptions: dict[str, Any]) -> ScenarioAssumptions:
    routing = assumptions["scenario_routing"]
    tiers = assumptions["scenario_presets"]
    tier_name = choose_scenario_tier(row, _safe_float(routing["luxury_price_threshold"], 2_000_000.0))
    tier_values = tiers[tier_name][scenario_name]
    return ScenarioAssumptions(
        adr=_safe_float(tier_values["adr"]), occupancy_rate=_safe_float(tier_values["occupancy_rate"])
    )


def _build_financing(assumptions: dict[str, Any]) -> FinancingAssumptions:
    data = assumptions["financing"]
    return FinancingAssumptions(
        down_payment_pct=_safe_float(data["down_payment_pct"]),
        interest_rate_annual=_safe_float(data["interest_rate_annual"]),
        loan_term_years=int(data["loan_term_years"]),
    )


def _build_cost_model(assumptions: dict[str, Any]) -> CostModelAssumptions:
    data = assumptions["cost_model"]
    return CostModelAssumptions(
        closing_cost_pct=_safe_float(data["closing_cost_pct"]),
        furnishing_pct=_safe_float(data["furnishing_pct"]),
        rehab_reserve_pct=_safe_float(data["rehab_reserve_pct"]),
        initial_reserve_pct=_safe_float(data["initial_reserve_pct"]),
        management_fee_pct=_safe_float(data["management_fee_pct"]),
        capex_pct=_safe_float(data["capex_pct"]),
        maintenance_pct=_safe_float(data["maintenance_pct"]),
        vacancy_buffer_pct=_safe_float(data["vacancy_buffer_pct"]),
        turnover_buffer_pct=_safe_float(data["turnover_buffer_pct"]),
        insurance_rate_pct_annual=_safe_float(data["insurance_rate_pct_annual"]),
        property_tax_rate_pct_annual=_safe_float(data["property_tax_rate_pct_annual"]),
        utilities_monthly=_safe_float(data["utilities_monthly"]),
    )


def _score_row(
    row: pd.Series,
    financing: FinancingAssumptions,
    cost_model: CostModelAssumptions,
    assumptions: dict[str, Any],
) -> dict[str, Any]:
    price = _safe_float(row.get("list_price"), 0.0)
    if price <= 0:
        return {}

    down_payment = price * financing.down_payment_pct
    loan_principal = price - down_payment
    monthly_debt_payment = mortgage_payment(loan_principal, financing.interest_rate_annual, financing.loan_term_years)

    closing_cost = price * cost_model.closing_cost_pct
    furnishing_cost = price * cost_model.furnishing_pct
    rehab_reserve = price * cost_model.rehab_reserve_pct
    initial_reserve = price * cost_model.initial_reserve_pct
    total_cash_cost_to_buy = down_payment + closing_cost + furnishing_cost + rehab_reserve + initial_reserve

    annual_fixed_ops = (
        price * cost_model.insurance_rate_pct_annual
        + price * cost_model.property_tax_rate_pct_annual
        + (cost_model.utilities_monthly * 12)
        + (_safe_float(row.get("hoa_fee"), 0.0) * 12)
    )

    base = {
        "property_id": row.get("property_id"),
        "property_url": row.get("property_url"),
        "status": row.get("status"),
        "street": row.get("street"),
        "city": row.get("city"),
        "state": row.get("state"),
        "zip_code": row.get("zip_code"),
        "neighborhoods": row.get("neighborhoods"),
        "beds": row.get("beds"),
        "full_baths": row.get("full_baths"),
        "sqft": row.get("sqft"),
        "list_price": price,
        "monthly_debt_payment": monthly_debt_payment,
        "annual_debt_service": monthly_debt_payment * 12,
        "down_payment": down_payment,
        "closing_cost": closing_cost,
        "furnishing_cost": furnishing_cost,
        "rehab_reserve": rehab_reserve,
        "initial_reserve": initial_reserve,
        "total_cash_cost_to_buy": total_cash_cost_to_buy,
        "annual_fixed_operating_costs": annual_fixed_ops,
        "scenario_tier": choose_scenario_tier(
            row, _safe_float(assumptions["scenario_routing"]["luxury_price_threshold"])
        ),
        "str_fit_pass": row.get("str_fit_pass"),
        "str_fit_score": row.get("str_fit_score"),
        "str_fit_reasons_pass": row.get("str_fit_reasons_pass"),
        "str_fit_reasons_fail": row.get("str_fit_reasons_fail"),
        "has_pool_inferred": row.get("has_pool_inferred"),
        "has_pool_source": row.get("has_pool_source"),
        "quality_pass": row.get("quality_pass"),
        "quality_exclusion_reason": row.get("quality_exclusion_reason"),
    }

    pct_ops = (
        cost_model.management_fee_pct
        + cost_model.capex_pct
        + cost_model.maintenance_pct
        + cost_model.vacancy_buffer_pct
        + cost_model.turnover_buffer_pct
    )

    for scenario_name in ("low", "med", "high"):
        scenario = _scenario_for(row, scenario_name, assumptions)
        monthly_revenue = scenario.adr * 30.0 * scenario.occupancy_rate
        annual_revenue = monthly_revenue * 12.0
        annual_variable_ops = annual_revenue * pct_ops
        annual_operating_total = annual_fixed_ops + annual_variable_ops
        annual_cash_flow = annual_revenue - annual_operating_total - (monthly_debt_payment * 12.0)
        coc = annual_cash_flow / total_cash_cost_to_buy if total_cash_cost_to_buy > 0 else 0.0

        base[f"adr_{scenario_name}"] = scenario.adr
        base[f"occupancy_{scenario_name}"] = scenario.occupancy_rate
        base[f"annual_revenue_{scenario_name}"] = annual_revenue
        base[f"annual_operating_cost_{scenario_name}"] = annual_operating_total
        base[f"annual_cash_flow_{scenario_name}"] = annual_cash_flow
        base[f"coc_{scenario_name}"] = coc

    return base


def score_properties(df: pd.DataFrame, assumptions: dict[str, Any], *, require_str_fit: bool = True) -> pd.DataFrame:
    financing = _build_financing(assumptions)
    cost_model = _build_cost_model(assumptions)

    eligible = df.copy()
    if "status" in eligible.columns:
        eligible = eligible[eligible["status"].astype(str).str.upper() == "FOR_SALE"]

    required = ["property_id", "list_price", "street", "city", "zip_code"]
    for col in required:
        if col not in eligible.columns:
            eligible[col] = pd.NA

    eligible = eligible[eligible["property_id"].notna() & eligible["list_price"].notna()].copy()
    if require_str_fit and "str_fit_pass" not in eligible.columns:
        raise ValueError("Missing required column 'str_fit_pass'. Run STR fit layer first or pass --run-all.")

    # Prefer latest snapshot per property_id when historical combined data contains duplicates.
    if "property_id" in eligible.columns:
        sort_cols = [c for c in ["batch_run_at", "list_date"] if c in eligible.columns]
        if sort_cols:
            eligible = eligible.sort_values(by=sort_cols, ascending=True, kind="mergesort")
        eligible = eligible.drop_duplicates(subset=["property_id"], keep="last").copy()

    scored_rows = [_score_row(row, financing, cost_model, assumptions) for _, row in eligible.iterrows()]
    scored_rows = [row for row in scored_rows if row]
    scored_df = pd.DataFrame(scored_rows)

    if scored_df.empty:
        return scored_df

    if "str_fit_pass" in scored_df.columns:
        scored_df["_rank_str_fit"] = scored_df["str_fit_pass"].map(lambda value: 1 if _safe_bool(value) else 0)
    else:
        scored_df["_rank_str_fit"] = 1
    scored_df = scored_df.sort_values(
        by=["_rank_str_fit", "coc_med", "property_id"],
        ascending=[False, False, True],
        kind="mergesort",
    )
    scored_df = scored_df.drop(columns=["_rank_str_fit"])
    return scored_df.reset_index(drop=True)


def assumptions_to_df(assumptions: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    financing = _build_financing(assumptions)
    for k, v in asdict(financing).items():
        rows.append({"section": "financing", "key": k, "value": v})

    costs = _build_cost_model(assumptions)
    for k, v in asdict(costs).items():
        rows.append({"section": "cost_model", "key": k, "value": v})

    rows.append(
        {
            "section": "scenario_routing",
            "key": "luxury_price_threshold",
            "value": _safe_float(assumptions["scenario_routing"]["luxury_price_threshold"]),
        }
    )

    for tier_name, tier_data in assumptions["scenario_presets"].items():
        for scenario_name, metrics in tier_data.items():
            rows.append({"section": f"{tier_name}.{scenario_name}", "key": "adr", "value": _safe_float(metrics["adr"])})
            rows.append(
                {
                    "section": f"{tier_name}.{scenario_name}",
                    "key": "occupancy_rate",
                    "value": _safe_float(metrics["occupancy_rate"]),
                }
            )

    return pd.DataFrame(rows)


def write_scorecard(scored_df: pd.DataFrame, assumptions: dict[str, Any], output_path: str | Path, top_n: int) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    if "str_fit_pass" in scored_df.columns:
        top_df = scored_df[scored_df["str_fit_pass"].map(_safe_bool)].head(top_n).copy()
    else:
        top_df = scored_df.head(top_n).copy()
    assumptions_df = assumptions_to_df(assumptions)

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        top_df.to_excel(writer, index=False, sheet_name="Top25_COC")
        assumptions_df.to_excel(writer, index=False, sheet_name="Assumptions")
        scored_df.to_excel(writer, index=False, sheet_name="All_Scored")


def main() -> None:
    args = parse_args()
    assumptions = load_assumptions(args.assumptions)

    df = load_input_rows(args.input)
    scored_df = score_properties(df, assumptions, require_str_fit=not args.run_all)
    write_scorecard(scored_df, assumptions, args.output, args.top_n)

    print(
        f"Input rows: {len(df)}\n"
        f"Eligible scored rows: {len(scored_df)}\n"
        f"Top-N requested: {args.top_n}\n"
        f"Output workbook: {Path(args.output).resolve()}"
    )


if __name__ == "__main__":
    main()

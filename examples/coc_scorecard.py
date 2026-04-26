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
    ("594 w stevens rd", "palm springs", "ca", "92262"),
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


@dataclass(frozen=True)
class AdrEngineAssumptions:
    base_adr_market: float
    pool_multiplier: float
    renovation_multiplier: float
    bedroom_multipliers: dict[str, float]
    luxury_uplift_pct: float


@dataclass(frozen=True)
class ContractPolicyAssumptions:
    annual_bookable_nights: float
    max_str_bookings_per_year: float
    avg_stay_nights_per_booking: float


@dataclass(frozen=True)
class MTRAssumptions:
    mtr_adr_multiplier: float
    mtr_occupancy: float


@dataclass(frozen=True)
class HELOCAssumptions:
    enabled: bool
    interest_only: bool
    rate_annual: float
    draw_strategy: str


@dataclass(frozen=True)
class TaxAssumptions:
    effective_combined_tax_rate: float
    analysis_year: int
    building_allocation_pct: float
    standard_recovery_years: float
    cost_seg_start_year: int
    cost_seg_bonus_pct: float


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

    return _normalize_assumptions(raw)


def _normalize_assumptions(raw: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(raw)
    normalized.setdefault("scenario_routing", {})
    normalized["scenario_routing"].setdefault("luxury_price_threshold", 2_000_000)

    normalized.setdefault("adr_engine", {})
    normalized["adr_engine"].setdefault("base_adr_market", 430)
    normalized["adr_engine"].setdefault("pool_multiplier", 1.12)
    normalized["adr_engine"].setdefault("renovation_multiplier", 1.08)
    normalized["adr_engine"].setdefault("bedroom_multipliers", {"1": 0.75, "2": 0.9, "3": 1.0, "4": 1.15, "5+": 1.3})
    normalized["adr_engine"].setdefault("luxury_uplift_pct", 0.35)

    normalized.setdefault("contract_policy", {})
    normalized["contract_policy"].setdefault("annual_bookable_nights", 365)
    normalized["contract_policy"].setdefault("max_str_bookings_per_year", 26)
    normalized["contract_policy"].setdefault("avg_stay_nights_per_booking", 4)

    normalized.setdefault("mtr", {})
    normalized["mtr"].setdefault("mtr_adr_multiplier", 0.55)
    normalized["mtr"].setdefault("mtr_occupancy", 0.72)

    normalized.setdefault("heloc", {})
    normalized["heloc"].setdefault("enabled", False)
    normalized["heloc"].setdefault("interest_only", True)
    normalized["heloc"].setdefault("rate_annual", 0.085)
    normalized["heloc"].setdefault("draw_strategy", "down_payment_only")

    normalized.setdefault("tax", {})
    normalized["tax"].setdefault("effective_combined_tax_rate", 0.37)
    normalized["tax"].setdefault("analysis_year", 1)
    normalized["tax"].setdefault("building_allocation_pct", 0.80)
    normalized["tax"].setdefault("standard_recovery_years", 27.5)
    normalized["tax"].setdefault("cost_seg_start_year", 2)
    normalized["tax"].setdefault("cost_seg_bonus_pct", 0.20)

    normalized.setdefault("ranking_metric", "coc_post_tax")
    return normalized


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


def _build_adr_engine(assumptions: dict[str, Any]) -> AdrEngineAssumptions:
    data = assumptions["adr_engine"]
    bedroom_multipliers = data.get("bedroom_multipliers", {})
    if not isinstance(bedroom_multipliers, dict):
        bedroom_multipliers = {}
    return AdrEngineAssumptions(
        base_adr_market=_safe_float(data["base_adr_market"]),
        pool_multiplier=_safe_float(data["pool_multiplier"], 1.0),
        renovation_multiplier=_safe_float(data["renovation_multiplier"], 1.0),
        bedroom_multipliers={str(k): _safe_float(v, 1.0) for k, v in bedroom_multipliers.items()},
        luxury_uplift_pct=_safe_float(data["luxury_uplift_pct"], 0.0),
    )


def _build_contract_policy(assumptions: dict[str, Any]) -> ContractPolicyAssumptions:
    data = assumptions["contract_policy"]
    return ContractPolicyAssumptions(
        annual_bookable_nights=_safe_float(data["annual_bookable_nights"], 365),
        max_str_bookings_per_year=_safe_float(data["max_str_bookings_per_year"], 26),
        avg_stay_nights_per_booking=_safe_float(data["avg_stay_nights_per_booking"], 4),
    )


def _build_mtr(assumptions: dict[str, Any]) -> MTRAssumptions:
    data = assumptions["mtr"]
    return MTRAssumptions(
        mtr_adr_multiplier=_safe_float(data["mtr_adr_multiplier"], 0.55),
        mtr_occupancy=_safe_float(data["mtr_occupancy"], 0.72),
    )


def _build_heloc(assumptions: dict[str, Any]) -> HELOCAssumptions:
    data = assumptions["heloc"]
    return HELOCAssumptions(
        enabled=_safe_bool(data.get("enabled")),
        interest_only=_safe_bool(data.get("interest_only"), True),
        rate_annual=_safe_float(data.get("rate_annual"), 0.085),
        draw_strategy=str(data.get("draw_strategy", "down_payment_only")),
    )


def _build_tax(assumptions: dict[str, Any]) -> TaxAssumptions:
    data = assumptions["tax"]
    return TaxAssumptions(
        effective_combined_tax_rate=_safe_float(data["effective_combined_tax_rate"], 0.37),
        analysis_year=int(_safe_float(data.get("analysis_year", 1), 1)),
        building_allocation_pct=_safe_float(data["building_allocation_pct"], 0.80),
        standard_recovery_years=_safe_float(data["standard_recovery_years"], 27.5),
        cost_seg_start_year=int(_safe_float(data["cost_seg_start_year"], 2)),
        cost_seg_bonus_pct=_safe_float(data["cost_seg_bonus_pct"], 0.20),
    )


def _bedroom_multiplier(beds: Any, multipliers: dict[str, float]) -> float:
    beds_value = int(_safe_float(beds, 0))
    if beds_value <= 0:
        return 1.0
    if beds_value >= 5:
        return _safe_float(multipliers.get("5+"), 1.0)
    return _safe_float(multipliers.get(str(beds_value)), 1.0)


def _is_renovated(row: pd.Series) -> bool:
    if "is_renovated" in row.index:
        return _safe_bool(row.get("is_renovated"))
    tags = " ".join(
        str(row.get(col, "") or "")
        for col in ("description", "remarks", "features", "amenities", "street", "property_url")
        if col in row.index
    ).lower()
    return any(token in tags for token in ("renovated", "remodeled", "updated", "fully redone", "modernized"))


def _primary_interest_year_one(loan_principal: float, annual_rate: float, term_years: int) -> float:
    if loan_principal <= 0:
        return 0.0
    months = max(1, term_years * 12)
    monthly_rate = annual_rate / 12
    payment = mortgage_payment(loan_principal, annual_rate, term_years)
    if monthly_rate <= 0:
        return min(loan_principal, payment * min(12, months))

    balance = loan_principal
    annual_interest = 0.0
    for _ in range(min(12, months)):
        interest = balance * monthly_rate
        principal = max(0.0, payment - interest)
        annual_interest += interest
        balance = max(0.0, balance - principal)
    return annual_interest


def _score_row(
    row: pd.Series,
    financing: FinancingAssumptions,
    cost_model: CostModelAssumptions,
    adr_engine: AdrEngineAssumptions,
    contract_policy: ContractPolicyAssumptions,
    mtr: MTRAssumptions,
    heloc: HELOCAssumptions,
    tax: TaxAssumptions,
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

    insurance_annual = price * cost_model.insurance_rate_pct_annual
    property_tax_annual = price * cost_model.property_tax_rate_pct_annual
    hoa_annual = _safe_float(row.get("hoa_fee"), 0.0) * 12
    annual_fixed_ops = insurance_annual + property_tax_annual + (cost_model.utilities_monthly * 12) + hoa_annual

    base = {
        "property_id": row.get("property_id"),
        "property_url": row.get("property_url"),
        "status": row.get("status"),
        "street": row.get("street"),
        "city": row.get("city"),
        "state": row.get("state"),
        "zip_code": row.get("zip_code"),
        "str_organized_neighborhood": row.get("str_organized_neighborhood") or row.get("neighborhoods"),
        "beds": row.get("beds"),
        "full_baths": row.get("full_baths"),
        "sqft": row.get("sqft"),
        "lot_sqft": row.get("lot_sqft"),
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
        "private_pool_verified": row.get("private_pool_verified"),
        "pool_enrichment_needed": row.get("pool_enrichment_needed"),
        "pool_enrichment_attempted": row.get("pool_enrichment_attempted"),
        "pool_enrichment_result": row.get("pool_enrichment_result"),
        "enrichment_attempted_at": row.get("enrichment_attempted_at"),
        "enrichment_source": row.get("enrichment_source"),
        "enrichment_round": row.get("enrichment_round"),
        "pool_signal_sources": row.get("pool_signal_sources"),
        "pool_evidence": row.get("pool_evidence"),
        "pool_confidence": row.get("pool_confidence"),
        "has_pool_inferred": row.get("has_pool_inferred"),
        "has_pool_source": row.get("has_pool_source"),
        "pool_signal_score": row.get("pool_signal_score"),
        "pool_signal_confidence": row.get("pool_signal_confidence"),
        "quality_pass": row.get("quality_pass"),
        "quality_exclusion_reason": row.get("quality_exclusion_reason"),
        "eligible_geo_cap_zip": row.get("eligible_geo_cap_zip"),
        "geo_cap_zip_reason": row.get("geo_cap_zip_reason"),
        "is_shortlist_candidate": row.get("is_shortlist_candidate"),
        "shortlist_rank": row.get("shortlist_rank"),
        "shortlist_reason": row.get("shortlist_reason"),
        "is_palm_springs_priority_candidate": row.get("is_palm_springs_priority_candidate"),
        "priority_score": row.get("priority_score"),
        "priority_rank": row.get("priority_rank"),
        "priority_reason_summary": row.get("priority_reason_summary"),
    }

    pct_ops = (
        cost_model.management_fee_pct
        + cost_model.capex_pct
        + cost_model.maintenance_pct
        + cost_model.vacancy_buffer_pct
        + cost_model.turnover_buffer_pct
    )

    scenario_tier = base["scenario_tier"]
    is_palm_springs = str(row.get("city", "")).strip().lower() == "palm springs"
    is_luxury = scenario_tier == "palm_springs_luxury"

    pool_present = _safe_bool(row.get("has_pool_inferred")) or _safe_bool(row.get("is_private_pool"))
    pool_mult = adr_engine.pool_multiplier if pool_present else 1.0
    renov_mult = adr_engine.renovation_multiplier if _is_renovated(row) else 1.0
    bed_mult = _bedroom_multiplier(row.get("beds"), adr_engine.bedroom_multipliers)
    luxury_mult = 1.0 + adr_engine.luxury_uplift_pct if is_luxury else 1.0
    adr_assumed = adr_engine.base_adr_market * pool_mult * renov_mult * bed_mult * luxury_mult

    max_str_nights = contract_policy.max_str_bookings_per_year * contract_policy.avg_stay_nights_per_booking
    if not is_palm_springs:
        max_str_nights = contract_policy.annual_bookable_nights

    for scenario_name in ("low", "med", "high"):
        scenario = _scenario_for(row, scenario_name, assumptions)
        demand_nights = contract_policy.annual_bookable_nights * scenario.occupancy_rate
        str_nights_capped = min(demand_nights, max_str_nights)
        remaining_nights = max(0.0, contract_policy.annual_bookable_nights - str_nights_capped)
        mtr_nights = remaining_nights * mtr.mtr_occupancy

        str_revenue = str_nights_capped * adr_assumed
        mtr_adr = adr_assumed * mtr.mtr_adr_multiplier
        mtr_revenue = mtr_nights * mtr_adr
        annual_revenue = str_revenue + mtr_revenue

        annual_variable_ops = annual_revenue * pct_ops
        annual_operating_total = annual_fixed_ops + annual_variable_ops
        primary_debt_service = monthly_debt_payment * 12.0

        if heloc.enabled:
            if heloc.draw_strategy == "down_payment_and_closing":
                heloc_draw = down_payment + closing_cost
            elif heloc.draw_strategy == "cash_in_components":
                heloc_draw = total_cash_cost_to_buy
            else:
                heloc_draw = down_payment
        else:
            heloc_draw = 0.0
        heloc_interest_annual = heloc_draw * heloc.rate_annual

        annual_cash_flow_pre_tax = (
            annual_revenue - annual_operating_total - primary_debt_service - heloc_interest_annual
        )

        mortgage_interest_annual = _primary_interest_year_one(
            loan_principal, financing.interest_rate_annual, financing.loan_term_years
        )
        building_basis = price * tax.building_allocation_pct
        depreciation_annual = building_basis / max(tax.standard_recovery_years, 1.0)
        depreciation_costseg_annual = (
            building_basis * tax.cost_seg_bonus_pct if tax.analysis_year >= tax.cost_seg_start_year else 0.0
        )
        deductible_expenses = (
            annual_operating_total
            + mortgage_interest_annual
            + heloc_interest_annual
            + property_tax_annual
            + depreciation_annual
            + depreciation_costseg_annual
        )
        taxable_income = annual_revenue - deductible_expenses
        tax_impact = taxable_income * tax.effective_combined_tax_rate
        annual_cash_flow_post_tax = annual_cash_flow_pre_tax - tax_impact

        annual_cash_flow = annual_cash_flow_pre_tax
        coc = annual_cash_flow / total_cash_cost_to_buy if total_cash_cost_to_buy > 0 else 0.0
        coc_post_tax = annual_cash_flow_post_tax / total_cash_cost_to_buy if total_cash_cost_to_buy > 0 else 0.0

        base["adr_assumed"] = adr_assumed
        base[f"adr_{scenario_name}"] = adr_assumed
        base[f"occupancy_{scenario_name}"] = scenario.occupancy_rate
        base[f"str_nights_capped_{scenario_name}"] = str_nights_capped
        base[f"mtr_nights_{scenario_name}"] = mtr_nights
        base[f"str_revenue_capped_{scenario_name}"] = str_revenue
        base[f"mtr_revenue_{scenario_name}"] = mtr_revenue
        base[f"annual_revenue_{scenario_name}"] = annual_revenue
        base[f"annual_operating_cost_{scenario_name}"] = annual_operating_total
        base[f"annual_cash_flow_{scenario_name}"] = annual_cash_flow_pre_tax
        base[f"coc_{scenario_name}"] = coc
        base[f"annual_cash_flow_pre_tax_{scenario_name}"] = annual_cash_flow_pre_tax
        base[f"annual_cash_flow_post_tax_{scenario_name}"] = annual_cash_flow_post_tax
        base[f"coc_post_tax_{scenario_name}"] = coc_post_tax
        base[f"taxable_income_{scenario_name}"] = taxable_income
        base[f"tax_impact_{scenario_name}"] = tax_impact

        if scenario_name == "med":
            base["str_nights_capped"] = str_nights_capped
            base["mtr_nights"] = mtr_nights
            base["str_revenue_capped"] = str_revenue
            base["mtr_revenue"] = mtr_revenue
            base["annual_revenue_total"] = annual_revenue
            base["annual_cash_flow_pre_tax"] = annual_cash_flow_pre_tax
            base["coc_pre_tax"] = coc
            base["taxable_income"] = taxable_income
            base["tax_impact"] = tax_impact
            base["annual_cash_flow_post_tax"] = annual_cash_flow_post_tax
            base["coc_post_tax"] = coc_post_tax
            base["heloc_interest_annual"] = heloc_interest_annual
            base["mortgage_interest_annual"] = mortgage_interest_annual
            base["depreciation_annual"] = depreciation_annual
            base["depreciation_costseg_annual"] = depreciation_costseg_annual

    return base


def score_properties(df: pd.DataFrame, assumptions: dict[str, Any], *, require_str_fit: bool = True) -> pd.DataFrame:
    assumptions = _normalize_assumptions(assumptions)
    financing = _build_financing(assumptions)
    cost_model = _build_cost_model(assumptions)
    adr_engine = _build_adr_engine(assumptions)
    contract_policy = _build_contract_policy(assumptions)
    mtr = _build_mtr(assumptions)
    heloc = _build_heloc(assumptions)
    tax = _build_tax(assumptions)

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
    if not eligible.empty:
        eligible = eligible[~eligible.apply(_is_manually_excluded_row, axis=1)].copy()

    # Prefer latest snapshot per property_id when historical combined data contains duplicates.
    if "property_id" in eligible.columns:
        sort_cols = [c for c in ["batch_run_at", "list_date"] if c in eligible.columns]
        if sort_cols:
            eligible = eligible.sort_values(by=sort_cols, ascending=True, kind="mergesort")
        eligible = eligible.drop_duplicates(subset=["property_id"], keep="last").copy()

    scored_rows = [
        _score_row(row, financing, cost_model, adr_engine, contract_policy, mtr, heloc, tax, assumptions)
        for _, row in eligible.iterrows()
    ]
    scored_rows = [row for row in scored_rows if row]
    scored_df = pd.DataFrame(scored_rows)

    if scored_df.empty:
        return scored_df

    if "str_fit_pass" in scored_df.columns:
        scored_df["_rank_str_fit"] = scored_df["str_fit_pass"].map(lambda value: 1 if _safe_bool(value) else 0)
    else:
        scored_df["_rank_str_fit"] = 1
    ranking_metric = str(assumptions.get("ranking_metric", "coc_post_tax"))
    if ranking_metric not in scored_df.columns:
        ranking_metric = "coc_med"
    scored_df = scored_df.sort_values(
        by=["_rank_str_fit", ranking_metric, "property_id"],
        ascending=[False, False, True],
        kind="mergesort",
    )
    scored_df = scored_df.drop(columns=["_rank_str_fit"])
    return scored_df.reset_index(drop=True)


def assumptions_to_df(assumptions: dict[str, Any]) -> pd.DataFrame:
    assumptions = _normalize_assumptions(assumptions)
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

    adr_engine = _build_adr_engine(assumptions)
    rows.append({"section": "adr_engine", "key": "base_adr_market", "value": adr_engine.base_adr_market})
    rows.append({"section": "adr_engine", "key": "pool_multiplier", "value": adr_engine.pool_multiplier})
    rows.append({"section": "adr_engine", "key": "renovation_multiplier", "value": adr_engine.renovation_multiplier})
    rows.append({"section": "adr_engine", "key": "luxury_uplift_pct", "value": adr_engine.luxury_uplift_pct})
    rows.append(
        {
            "section": "adr_engine",
            "key": "bedroom_multipliers",
            "value": json.dumps(adr_engine.bedroom_multipliers),
        }
    )

    contract_policy = _build_contract_policy(assumptions)
    for k, v in asdict(contract_policy).items():
        rows.append({"section": "contract_policy", "key": k, "value": v})

    mtr = _build_mtr(assumptions)
    for k, v in asdict(mtr).items():
        rows.append({"section": "mtr", "key": k, "value": v})

    heloc = _build_heloc(assumptions)
    for k, v in asdict(heloc).items():
        rows.append({"section": "heloc", "key": k, "value": v})

    tax = _build_tax(assumptions)
    for k, v in asdict(tax).items():
        rows.append({"section": "tax", "key": k, "value": v})

    rows.append(
        {"section": "ranking", "key": "ranking_metric", "value": assumptions.get("ranking_metric", "coc_post_tax")}
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

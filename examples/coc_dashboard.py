from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_INPUT_PATH = Path("examples/zips/coc_scorecard.xlsx")
DEFAULT_OUTPUT_PATH = Path("examples/zips/coc_dashboard.html")
DEFAULT_HEALTH_REPORT_PATH = Path("examples/zips/incremental_health_report.json")
DEFAULT_COC_ASSUMPTIONS_PATH = Path("examples/data/coc_assumptions.json")
BUDGET_LUXURY_MAX_PRICE = 1_500_000.0
BUDGET_LUXURY_TOP_N = 30
DASHBOARD_MAX_LIST_PRICE = 1_500_000.0
EXCLUDED_PROPERTY_IDS = {"2310318356"}
EXCLUDED_PROPERTY_SIGNATURES = {("1961 s palm canyon dr", "palm springs", "ca", "92264")}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build static COC dashboard HTML from scorecard workbook")
    parser.add_argument("--input", default=str(DEFAULT_INPUT_PATH), help="Input COC scorecard workbook path")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="Output dashboard HTML path")
    parser.add_argument("--top-n", type=int, default=10, help="Top N rows to display in COC table")
    parser.add_argument("--homes-limit", type=int, default=100, help="Max homes loaded in interactive breakdown")
    parser.add_argument(
        "--health-report-input",
        default=str(DEFAULT_HEALTH_REPORT_PATH),
        help="Optional incremental health report JSON used for KPI metadata.",
    )
    return parser.parse_args()


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_optional_float(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_str(value: Any, default: str = "") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    return str(value)


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = _safe_str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "t"}:
        return True
    if text in {"0", "false", "no", "n", "f"}:
        return False
    return default


def _normalize_text(value: Any) -> str:
    return " ".join(_safe_str(value).lower().replace(",", " ").split())


def _normalize_zip(value: Any) -> str:
    text = _safe_str(value).strip()
    if not text:
        return ""
    if text.endswith(".0"):
        text = text[:-2]
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 5:
        return digits[:5]
    return _normalize_text(text)


def _is_excluded_listing(row: pd.Series) -> bool:
    property_id = _safe_str(row.get("property_id")).strip()
    if property_id and property_id in EXCLUDED_PROPERTY_IDS:
        return True

    signature = (
        _normalize_text(row.get("street")),
        _normalize_text(row.get("city")),
        _normalize_text(row.get("state")),
        _normalize_zip(row.get("zip_code")),
    )
    if signature in EXCLUDED_PROPERTY_SIGNATURES:
        return True

    full_address = _normalize_text(row.get("address"))
    return full_address == "1961 s palm canyon dr palm springs ca 92264"


def _ai_insights(row: pd.Series) -> dict[str, str]:
    coc_med = _safe_float(row.get("coc_post_tax"), _safe_float(row.get("coc_med")))
    coc_low = _safe_float(row.get("coc_low"))
    coc_high = _safe_float(row.get("coc_high"))
    annual_cash_flow_med = _safe_float(row.get("annual_cash_flow_med"))
    annual_cash_flow_low = _safe_float(row.get("annual_cash_flow_low"))
    list_price = _safe_float(row.get("list_price"))
    sqft = _safe_float(row.get("sqft"))
    beds = _safe_float(row.get("beds"))
    full_baths = _safe_float(row.get("full_baths"))
    total_cash_cost_to_buy = _safe_float(row.get("total_cash_cost_to_buy"))
    str_fit_score = _safe_float(row.get("str_fit_score"))
    occ_low = _safe_float(row.get("occupancy_low"))
    occ_high = _safe_float(row.get("occupancy_high"))
    adr_med = _safe_float(row.get("adr_med"))
    fail_reasons_raw = _safe_str(row.get("str_fit_reasons_fail"))
    fail_reasons = fail_reasons_raw.lower()

    def _fmt_currency(value: float) -> str:
        return f"${value:,.0f}"

    def _fmt_pct(value: float) -> str:
        return f"{value * 100:.1f}%"

    price_per_sqft = (list_price / sqft) if sqft > 0 else 0.0
    layout = ""
    if beds > 0 and full_baths > 0:
        layout = f" Layout: {beds:.0f} bed / {full_baths:.1f} bath."

    potential = (
        f"Potential: Priced at {_fmt_currency(list_price)}"
        f"{f' ({_fmt_currency(price_per_sqft)}/sq ft)' if price_per_sqft > 0 else ''}, "
        f"this home underwrites to post-tax COC {_fmt_pct(coc_med)}"
        f" and median annual cash flow {_fmt_currency(annual_cash_flow_med)}.{layout}"
    )
    if occ_low > 0 and occ_high > 0:
        potential = f"{potential} Occupancy band {_fmt_pct(occ_low)}-{_fmt_pct(occ_high)} supports demand depth."
    if adr_med > 0:
        potential = f"{potential} ADR midpoint is {_fmt_currency(adr_med)}."
    if str_fit_score > 0:
        potential = f"{potential} STR-fit score: {str_fit_score:.0f}/100."

    risk = "Risk: "
    risk_parts: list[str] = []
    if coc_low < 0:
        risk_parts.append(f"downside COC reaches {_fmt_pct(coc_low)}")
    if annual_cash_flow_low < 0:
        risk_parts.append(f"downside annual cash flow is {_fmt_currency(annual_cash_flow_low)}")
    elif annual_cash_flow_med <= 0:
        risk_parts.append("base-case annual cash flow is non-positive")
    elif annual_cash_flow_med < 6000:
        risk_parts.append(f"base-case cash flow is thin at {_fmt_currency(annual_cash_flow_med)}")
    if total_cash_cost_to_buy >= 250000:
        risk_parts.append(f"high upfront capital at {_fmt_currency(total_cash_cost_to_buy)}")
    if list_price >= 1200000:
        risk_parts.append("premium pricing increases acquisition basis risk")
    if "private pool unknown" in fail_reasons:
        risk_parts.append("pool data is incomplete and may affect STR appeal")
    if adr_med > 0 and occ_low < 0.45:
        risk_parts.append("lower occupancy downside could pressure ADR assumptions")
    if coc_high - coc_low > 0.12:
        risk_parts.append("wide return spread suggests higher forecast volatility")
    if fail_reasons_raw:
        fail_summary = fail_reasons_raw.split(";")[0].strip()
        if fail_summary:
            risk_parts.append(f"filter flag: {fail_summary.lower()}")

    if not risk_parts:
        risk += "No major red flags in current underwriting inputs."
    else:
        risk += "; ".join(risk_parts[:2]).capitalize() + "."

    return {"potential": potential, "risk": risk}


def load_scored_data(path: str | Path) -> pd.DataFrame:
    workbook = Path(path)
    if not workbook.exists():
        raise FileNotFoundError(f"Scorecard workbook not found: {workbook}")

    excel = pd.ExcelFile(workbook)
    if "All_Scored" in excel.sheet_names:
        df = pd.read_excel(workbook, sheet_name="All_Scored")
    else:
        df = pd.read_excel(workbook)

    ranking_col = "coc_post_tax" if "coc_post_tax" in df.columns else "coc_med"
    if ranking_col in df.columns:
        df = df.sort_values(by=[ranking_col, "property_id"], ascending=[False, True], kind="mergesort")

    return df.reset_index(drop=True)


def _row_to_home_payload(row: pd.Series) -> dict[str, Any]:
    annual_revenue_med = _safe_float(row.get("annual_revenue_med"), 0.0)
    annual_operating_med = _safe_float(row.get("annual_operating_cost_med"), 0.0)
    annual_fixed = _safe_float(row.get("annual_fixed_operating_costs"), 0.0)

    variable_ratio = 0.0
    if annual_revenue_med > 0:
        variable_ratio = max(0.0, (annual_operating_med - annual_fixed) / annual_revenue_med)

    street = _safe_str(row.get("street"))
    city = _safe_str(row.get("city"))
    state = _safe_str(row.get("state"))
    zip_code = _safe_str(row.get("zip_code"))
    address = ", ".join([p for p in [street, city, state, zip_code] if p])

    insights = _ai_insights(row)

    return {
        "property_id": _safe_str(row.get("property_id")),
        "address": address,
        "city": city,
        "zip_code": zip_code,
        "property_url": _safe_str(row.get("property_url")),
        "list_price": _safe_float(row.get("list_price")),
        "scenario_tier": _safe_str(row.get("scenario_tier")),
        "monthly_debt_payment": _safe_float(row.get("monthly_debt_payment")),
        "annual_debt_service": _safe_float(row.get("annual_debt_service")),
        "total_cash_cost_to_buy": _safe_float(row.get("total_cash_cost_to_buy")),
        "annual_fixed_operating_costs": annual_fixed,
        "operating_variable_ratio": variable_ratio,
        "adr_low": _safe_float(row.get("adr_low")),
        "adr_med": _safe_float(row.get("adr_med")),
        "adr_high": _safe_float(row.get("adr_high")),
        "occ_low": _safe_float(row.get("occupancy_low")),
        "occ_med": _safe_float(row.get("occupancy_med")),
        "occ_high": _safe_float(row.get("occupancy_high")),
        "coc_low": _safe_float(row.get("coc_low")),
        "coc_med": _safe_float(row.get("coc_med")),
        "coc_high": _safe_float(row.get("coc_high")),
        "coc_pre_tax": _safe_float(row.get("coc_pre_tax"), _safe_float(row.get("coc_med"))),
        "coc_post_tax": _safe_float(row.get("coc_post_tax"), _safe_float(row.get("coc_med"))),
        "annual_cash_flow_low": _safe_float(row.get("annual_cash_flow_low")),
        "annual_cash_flow_med": _safe_float(row.get("annual_cash_flow_med")),
        "annual_cash_flow_high": _safe_float(row.get("annual_cash_flow_high")),
        "str_fit_pass": _safe_bool(row.get("str_fit_pass")),
        "str_fit_score": _safe_float(row.get("str_fit_score")),
        "str_fit_reasons_pass": _safe_str(row.get("str_fit_reasons_pass")),
        "str_fit_reasons_fail": _safe_str(row.get("str_fit_reasons_fail")),
        "ai_insight_potential": insights["potential"],
        "ai_insight_risk": insights["risk"],
    }


def _top_rows(df: pd.DataFrame, top_n: int) -> list[dict[str, Any]]:
    top_rows: list[dict[str, Any]] = []
    for _, row in df.head(top_n).iterrows():
        insights = _ai_insights(row)
        list_price = _safe_float(row.get("list_price"))
        sqft = _safe_float(row.get("sqft"))
        price_per_sqft = (list_price / sqft) if sqft > 0 else 0.0
        top_rows.append(
            {
                "property_id": _safe_str(row.get("property_id")),
                "address": ", ".join(
                    [
                        p
                        for p in [
                            _safe_str(row.get("street")),
                            _safe_str(row.get("city")),
                            _safe_str(row.get("state")),
                            _safe_str(row.get("zip_code")),
                        ]
                        if p
                    ]
                ),
                "list_price": list_price,
                "sqft": sqft,
                "lot_sqft": _safe_float(row.get("lot_sqft")),
                "price_per_sqft": price_per_sqft,
                "beds": _safe_float(row.get("beds")),
                "full_baths": _safe_float(row.get("full_baths")),
                "adr_med": _safe_float(row.get("adr_med")),
                "coc_med": _safe_float(row.get("coc_med")),
                "coc_pre_tax": _safe_float(row.get("coc_pre_tax"), _safe_float(row.get("coc_med"))),
                "coc_post_tax": _safe_float(row.get("coc_post_tax"), _safe_float(row.get("coc_med"))),
                "annual_cash_flow_med": _safe_float(row.get("annual_cash_flow_med")),
                "monthly_debt_payment": _safe_float(row.get("monthly_debt_payment")),
                "total_cash_cost_to_buy": _safe_float(row.get("total_cash_cost_to_buy")),
                "dscr": _safe_optional_float(row.get("dscr")),
                "str_fit_score": _safe_float(row.get("str_fit_score")),
                "str_fit_pass": _safe_bool(row.get("str_fit_pass")),
                "property_url": _safe_str(row.get("property_url")),
                "ai_insight_potential": insights["potential"],
                "ai_insight_risk": insights["risk"],
            }
        )
    return top_rows


def _table_rows(df: pd.DataFrame, max_rows: int = 500) -> list[dict[str, Any]]:
    if df.empty:
        return []
    rows: list[dict[str, Any]] = []
    for _, row in df.head(max_rows).iterrows():
        rows.append(
            {
                "property_id": _safe_str(row.get("property_id")),
                "address": ", ".join(
                    [
                        p
                        for p in [
                            _safe_str(row.get("street")),
                            _safe_str(row.get("city")),
                            _safe_str(row.get("state")),
                            _safe_str(row.get("zip_code")),
                        ]
                        if p
                    ]
                ),
                "city": _safe_str(row.get("city")),
                "neighborhood": _safe_str(
                    row.get("neighborhood")
                    or row.get("str_organized_neighborhood")
                    or row.get("str_neighborhood")
                    or row.get("neighborhoods")
                ),
                "list_price": _safe_float(row.get("list_price")),
                "beds": _safe_float(row.get("beds")),
                "full_baths": _safe_float(row.get("full_baths")),
                "sqft": _safe_float(row.get("sqft")),
                "lot_sqft": _safe_float(row.get("lot_sqft")),
                "price_per_sqft": (
                    _safe_float(row.get("list_price")) / _safe_float(row.get("sqft"))
                    if _safe_float(row.get("sqft")) > 0
                    else 0.0
                ),
                "coc_pre_tax": _safe_float(row.get("coc_pre_tax"), _safe_float(row.get("coc_med"))),
                "coc_post_tax": _safe_float(row.get("coc_post_tax"), _safe_float(row.get("coc_med"))),
                "annual_cash_flow_med": _safe_float(row.get("annual_cash_flow_med")),
                "str_fit_score": _safe_float(row.get("str_fit_score")),
                "property_url": _safe_str(row.get("property_url")),
            }
        )
    return rows


def _load_coc_assumptions_summary(path: str | Path = DEFAULT_COC_ASSUMPTIONS_PATH) -> dict[str, Any]:
    assumptions_path = Path(path)
    if not assumptions_path.exists():
        return {}
    try:
        payload = json.loads(assumptions_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}

    financing = payload.get("financing", {}) if isinstance(payload.get("financing"), dict) else {}
    cost_model = payload.get("cost_model", {}) if isinstance(payload.get("cost_model"), dict) else {}
    tax = payload.get("tax", {}) if isinstance(payload.get("tax"), dict) else {}
    return {
        "pre_tax_formula": "Pre-tax COC = annual_cash_flow_pre_tax / total_cash_cost_to_buy",
        "post_tax_formula": "Post-tax COC = annual_cash_flow_post_tax / total_cash_cost_to_buy",
        "note": (
            "Post-tax cash flow adjusts pre-tax cash flow by tax impact, which is derived from taxable income "
            "after deductible expenses (including interest and depreciation)."
        ),
        "caveat": "Underwriting estimate only. Not tax, legal, or investment advice.",
        "tax": {
            "effective_combined_tax_rate": _safe_float(tax.get("effective_combined_tax_rate"), 0.37),
            "analysis_year": int(_safe_float(tax.get("analysis_year"), 1)),
            "building_allocation_pct": _safe_float(tax.get("building_allocation_pct"), 0.80),
            "standard_recovery_years": _safe_float(tax.get("standard_recovery_years"), 27.5),
            "cost_seg_start_year": int(_safe_float(tax.get("cost_seg_start_year"), 2)),
            "cost_seg_bonus_pct": _safe_float(tax.get("cost_seg_bonus_pct"), 0.20),
        },
        "financing": {
            "down_payment_pct": _safe_float(financing.get("down_payment_pct"), 0.10),
            "interest_rate_annual": _safe_float(financing.get("interest_rate_annual"), 0.0575),
            "loan_term_years": int(_safe_float(financing.get("loan_term_years"), 30)),
        },
        "cost_model": {
            "management_fee_pct": _safe_float(cost_model.get("management_fee_pct"), 0.18),
            "capex_pct": _safe_float(cost_model.get("capex_pct"), 0.05),
            "maintenance_pct": _safe_float(cost_model.get("maintenance_pct"), 0.06),
            "vacancy_buffer_pct": _safe_float(cost_model.get("vacancy_buffer_pct"), 0.04),
            "turnover_buffer_pct": _safe_float(cost_model.get("turnover_buffer_pct"), 0.03),
        },
    }


def _normalized_map(series: pd.Series, *, inverse: bool = False) -> dict[int, float]:
    values = pd.to_numeric(series, errors="coerce")
    min_val = values.min(skipna=True)
    max_val = values.max(skipna=True)
    if pd.isna(min_val) or pd.isna(max_val):
        return {idx: 0.5 for idx in series.index}
    if max_val == min_val:
        return {idx: 0.5 for idx in series.index}

    normalized: dict[int, float] = {}
    denom = max_val - min_val
    for idx, raw in values.items():
        if pd.isna(raw):
            base = 0.5
        else:
            base = (float(raw) - float(min_val)) / float(denom)
        normalized[idx] = 1.0 - base if inverse else base
    return normalized


def _budget_luxury_value_rows(
    df: pd.DataFrame,
    *,
    top_n: int,
    max_price: float,
    coc_weight: float,
    ppsf_weight: float,
) -> tuple[list[dict[str, Any]], int]:
    if df.empty:
        return [], 0

    list_price_num = pd.to_numeric(df.get("list_price"), errors="coerce").fillna(0.0)
    budget = df[list_price_num <= max_price].copy()
    if budget.empty:
        return [], 0

    budget["price_per_sqft"] = budget.apply(
        lambda r: (
            (_safe_float(r.get("list_price")) / _safe_float(r.get("sqft"))) if _safe_float(r.get("sqft")) > 0 else 0.0
        ),
        axis=1,
    )

    if "coc_post_tax" in budget.columns:
        ranking_col = "coc_post_tax"
    elif "coc_pre_tax" in budget.columns:
        ranking_col = "coc_pre_tax"
    else:
        ranking_col = "coc_med"

    fallback_series = budget.get("coc_pre_tax")
    if fallback_series is None:
        fallback_series = budget.get("coc_med")
    if fallback_series is None:
        fallback_series = pd.Series(0.0, index=budget.index)
    budget["_coc_rank"] = budget[ranking_col].fillna(fallback_series)

    coc_norm = _normalized_map(budget["_coc_rank"])
    ppsf_norm = _normalized_map(budget["price_per_sqft"], inverse=True)

    budget["value_score"] = [(coc_weight * coc_norm[idx]) + (ppsf_weight * ppsf_norm[idx]) for idx in budget.index]
    budget = budget.sort_values(
        by=["value_score", "_coc_rank", "price_per_sqft", "property_id"],
        ascending=[False, False, True, True],
        kind="mergesort",
    )

    rows = _top_rows(budget, top_n)
    for i, row_idx in enumerate(budget.head(top_n).index):
        rows[i]["value_score"] = _safe_float(budget.loc[row_idx, "value_score"])
        rows[i]["ranking_metric_used"] = ranking_col
    return rows, int(len(budget))


def _pool_watchlist_rows(df: pd.DataFrame, top_n: int = 30) -> list[dict[str, Any]]:
    if df.empty:
        return []
    watch = df.copy()
    watch["pool_enrichment_needed"] = watch.get("pool_enrichment_needed", False)
    watch["private_pool_verified"] = watch.get("private_pool_verified", False)
    watch = watch[
        watch["pool_enrichment_needed"].fillna(False).astype(bool)
        & ~watch["private_pool_verified"].fillna(False).astype(bool)
    ].copy()
    if watch.empty:
        return []
    watch = watch.sort_values(by=["str_fit_score", "property_id"], ascending=[False, True], kind="mergesort")
    rows: list[dict[str, Any]] = []
    for _, row in watch.head(top_n).iterrows():
        list_price = _safe_float(row.get("list_price"))
        sqft = _safe_float(row.get("sqft"))
        rows.append(
            {
                "property_id": _safe_str(row.get("property_id")),
                "address": ", ".join(
                    [
                        p
                        for p in [
                            _safe_str(row.get("street")),
                            _safe_str(row.get("city")),
                            _safe_str(row.get("state")),
                            _safe_str(row.get("zip_code")),
                        ]
                        if p
                    ]
                ),
                "property_url": _safe_str(row.get("property_url")),
                "list_price": list_price,
                "sqft": sqft,
                "lot_sqft": _safe_float(row.get("lot_sqft")),
                "price_per_sqft": (list_price / sqft) if sqft > 0 else 0.0,
                "pool_signal_confidence": _safe_str(
                    row.get("pool_signal_confidence"), _safe_str(row.get("pool_confidence"), "unknown")
                ),
                "pool_signal_sources": _safe_str(row.get("pool_signal_sources"), "none"),
                "pool_evidence": _safe_str(row.get("pool_evidence"), "n/a"),
                "pool_enrichment_result": _safe_str(row.get("pool_enrichment_result"), "queued"),
            }
        )
    return rows


def _palm_springs_priority_rows(df: pd.DataFrame, top_n: int) -> list[dict[str, Any]]:
    if df.empty:
        return []
    candidates = df[
        df.get("is_palm_springs_priority_candidate", pd.Series(False, index=df.index)).fillna(False).astype(bool)
    ].copy()
    if candidates.empty:
        return []

    coc_post = (
        pd.to_numeric(candidates["coc_post_tax"], errors="coerce")
        if "coc_post_tax" in candidates.columns
        else pd.Series(0.0, index=candidates.index)
    )
    coc_pre = (
        pd.to_numeric(candidates["coc_pre_tax"], errors="coerce")
        if "coc_pre_tax" in candidates.columns
        else pd.Series(float("nan"), index=candidates.index)
    )
    coc_base = (
        pd.to_numeric(candidates["coc_med"], errors="coerce")
        if "coc_med" in candidates.columns
        else pd.Series(float("nan"), index=candidates.index)
    )
    candidates["_priority_score_num"] = pd.to_numeric(candidates.get("priority_score"), errors="coerce").fillna(0.0)
    candidates["_priority_coc_pre"] = coc_pre.fillna(coc_post).fillna(coc_base).fillna(0.0)
    candidates["_priority_coc_post"] = coc_post.fillna(coc_base).fillna(coc_pre).fillna(0.0)
    candidates = candidates.sort_values(
        by=["_priority_coc_pre", "_priority_coc_post", "_priority_score_num", "property_id"],
        ascending=[False, False, False, True],
        kind="mergesort",
    )

    rows = _top_rows(candidates, top_n)
    for i, row_idx in enumerate(candidates.head(top_n).index):
        rows[i]["priority_score"] = _safe_float(candidates.loc[row_idx, "_priority_score_num"])
        rows[i]["priority_rank"] = i + 1
        rows[i]["priority_reason_summary"] = _safe_str(
            candidates.loc[row_idx, "priority_reason_summary"], "Balanced STR value profile."
        )
    return rows


def _load_incremental_health_report(path: str | Path) -> dict[str, Any]:
    report_path = Path(path)
    if not report_path.exists():
        return {}
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def build_dashboard_payload(
    scored_df: pd.DataFrame,
    *,
    top_n: int = 10,
    homes_limit: int = 100,
    health_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scored = scored_df.copy()
    if not scored.empty:
        scored = scored.loc[~scored.apply(_is_excluded_listing, axis=1)].copy()

    if "status" in scored.columns:
        scored = scored[scored["status"].astype(str).str.upper() == "FOR_SALE"].copy()

    if "list_price" in scored.columns:
        list_price_num = pd.to_numeric(scored.get("list_price"), errors="coerce").fillna(0.0)
        scored = scored[list_price_num <= DASHBOARD_MAX_LIST_PRICE].copy()

    if "str_fit_pass" not in scored.columns:
        scored["str_fit_pass"] = True

    if "str_fit_score" not in scored.columns:
        scored["str_fit_score"] = 0.0

    fit = scored[scored["str_fit_pass"].fillna(False).astype(bool)].copy()
    ranking_col = "coc_post_tax" if "coc_post_tax" in fit.columns else "coc_med"
    fit = fit.sort_values(
        by=[ranking_col, "str_fit_score", "property_id"], ascending=[False, False, True], kind="mergesort"
    )
    if "scenario_tier" in fit.columns:
        luxury = fit[fit["scenario_tier"].astype(str) == "palm_springs_luxury"].copy()
    else:
        luxury = fit.iloc[0:0].copy()
    luxury = luxury.sort_values(
        by=[ranking_col, "str_fit_score", "property_id"], ascending=[False, False, True], kind="mergesort"
    )
    budget_value_rows, total_budget_value_candidates = _budget_luxury_value_rows(
        fit,
        top_n=BUDGET_LUXURY_TOP_N,
        max_price=BUDGET_LUXURY_MAX_PRICE,
        coc_weight=0.70,
        ppsf_weight=0.30,
    )

    top_fit = _top_rows(fit, top_n)
    top_luxury = _top_rows(luxury, top_n)
    table_rows = _table_rows(fit, max_rows=500)
    priority_rows = _palm_springs_priority_rows(scored, top_n)
    watchlist_rows = _pool_watchlist_rows(scored, top_n=30)
    coc_assumptions_summary = _load_coc_assumptions_summary()
    total_pool_unknown_candidates = int(
        (
            scored.get("pool_enrichment_needed", pd.Series(False, index=scored.index)).fillna(False).astype(bool)
            & ~scored.get("private_pool_verified", pd.Series(False, index=scored.index)).fillna(False).astype(bool)
        ).sum()
    )
    total_pool_verified_after_enrichment = int(
        scored.get("pool_enrichment_result", pd.Series("", index=scored.index))
        .astype(str)
        .eq("verified_after_enrichment")
        .sum()
    )
    homes_fit = [_row_to_home_payload(row) for _, row in fit.head(homes_limit).iterrows()]
    palm_springs_mask = (
        scored.get("city", pd.Series("", index=scored.index)).astype(str).str.strip().str.lower().eq("palm springs")
    )
    total_palm_springs_strict_pass = int(
        (
            palm_springs_mask
            & scored.get("str_fit_pass", pd.Series(False, index=scored.index)).fillna(False).astype(bool)
        ).sum()
    )
    total_palm_springs_priority_candidates = int(
        scored.get("is_palm_springs_priority_candidate", pd.Series(False, index=scored.index))
        .fillna(False)
        .astype(bool)
        .sum()
    )
    top_priority_score = _safe_float(priority_rows[0].get("priority_score")) if priority_rows else 0.0

    if health_report is None:
        health_report = {}
    summary = health_report.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    new_listings_today = int(_safe_float(summary.get("new_rows"), 0.0))
    fetched_rows_today = int(_safe_float(summary.get("fetched_rows"), 0.0))
    listings_pulled_at = _safe_str(health_report.get("batch_run_at")).strip() or None

    return {
        "total_ingested": int(len(scored)),
        "total_str_fit_passed": int(len(fit)),
        "new_listings_today": new_listings_today,
        "fetched_rows_today": fetched_rows_today,
        "listings_pulled_at": listings_pulled_at,
        "top_properties": top_fit,
        "top_properties_luxury": top_luxury,
        "table_rows": table_rows,
        "top_properties_palm_springs_priority": priority_rows,
        "top_properties_luxury_value_budget": budget_value_rows,
        "pool_verification_watchlist": watchlist_rows,
        "total_pool_unknown_candidates": total_pool_unknown_candidates,
        "total_pool_verified_after_enrichment": total_pool_verified_after_enrichment,
        "total_luxury_value_budget_candidates": total_budget_value_candidates,
        "total_palm_springs_priority_candidates": total_palm_springs_priority_candidates,
        "total_palm_springs_strict_pass": total_palm_springs_strict_pass,
        "top_priority_score": top_priority_score,
        "luxury_value_budget_cap": BUDGET_LUXURY_MAX_PRICE,
        "luxury_value_note": (
            "Ranked for value using post-tax COC (fallback: pre-tax COC) and lower price per sqft "
            "for STR-fit for-sale properties under the budget cap."
        ),
        "total_luxury_candidates": int(len(luxury)),
        "luxury_widget_note": (
            "Luxury = scenario_tier = palm_springs_luxury from COC routing assumptions. "
            "Ranked by post-tax COC (fallback: base COC) among luxury-tier STR-fit listings."
        ),
        "pool_watchlist_note": "Not STR-pass yet; awaiting private-pool verification.",
        "priority_ranking_note": (
            "Coachella Valley STR-pass listings sorted by pre-tax COC "
            "(tie-break: post-tax COC, then priority score). "
            "Dashboard view is capped at $1,500,000 list price."
        ),
        "coc_assumptions_summary": coc_assumptions_summary,
        "homes": homes_fit,
        "total_houses_on_sale": int(len(scored)),
        "str_filter_snapshot": [
            "STR-supported neighborhood required",
            "Private pool required (verified/inferred high-confidence)",
            "Beds/Baths minimum: 2+/2+",
            "STR hard-gate list price range: $150,000 to $1,500,000",
            "Dashboard review queue cap: <= $1,500,000 list price",
            "Preferred cities: Palm Springs, North Palm Springs, Cathedral City, Thousand Palms, Indio, Bermuda Dunes, Coachella, La Quinta, Palm Desert, Rancho Mirage, Desert Hot Springs, Indian Wells",
            "ZIP must be in under-cap STR geography",
        ],
    }


def render_dashboard_html(payload: dict[str, Any]) -> str:
    data_json = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>COC Dashboard</title>
  <style>
    :root {
      --bg: #f7f8fa;
      --card: #ffffff;
      --ink: #111827;
      --muted: #6b7280;
      --line: #dbe3ee;
      --accent: #14532d;
      --accent-soft: #dcfce7;
      --score: #0f766e;
      --label: #334155;
      --chip-bg: #e2e8f0;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", Arial, sans-serif;
      background: radial-gradient(circle at top right, #e0ecff 0%, #f7f8fa 38%);
      color: var(--ink);
    }
    .wrap { max-width: 1220px; margin: 24px auto 36px; padding: 0 18px; }
    .headcard {
      background: linear-gradient(120deg, #0f172a 0%, #1f2937 46%, #111827 100%);
      color: #eef2ff;
      border-radius: 16px;
      padding: 22px;
      border: 1px solid #1e293b;
      margin-bottom: 16px;
    }
    .eyebrow {
      margin: 0 0 6px;
      text-transform: uppercase;
      letter-spacing: .08em;
      font-weight: 700;
      color: #93c5fd;
      font-size: 12px;
    }
    .headline { margin: 0; font-size: 28px; font-weight: 800; }
    .subline { margin: 8px 0 0; color: #cbd5e1; font-size: 14px; }
    .kpis {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 14px;
    }
    .kpi {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
    }
    .kpi .k { margin: 0; font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; font-weight: 700; }
    .kpi .v { margin: 6px 0 0; font-size: 32px; font-weight: 800; color: var(--accent); line-height: 1; }
    .kpi .s { margin: 8px 0 0; font-size: 12px; color: var(--muted); }
    .module {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 18px;
      margin-bottom: 14px;
    }
    .module h2 {
      margin: 0 0 8px;
      font-size: 22px;
      line-height: 1.2;
    }
    .module-note {
      margin: 0;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.5;
    }
    .snapshot {
      margin-top: 12px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }
    .snapshot ul {
      margin: 6px 0 0;
      padding-left: 18px;
    }
    .rank-list {
      display: grid;
      gap: 10px;
      margin-top: 14px;
    }
    .rank-row {
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px;
      background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
      display: grid;
      gap: 12px;
    }
    .rank-head {
      display: grid;
      grid-template-columns: 120px 170px minmax(0, 1fr);
      gap: 12px;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--line);
    }
    .rank-body {
      display: grid;
      grid-template-columns: 1.2fr 1fr 1.2fr;
      gap: 12px;
    }
    .group {
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px;
      background: #ffffff;
    }
    .group-title {
      margin: 0 0 8px;
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: .05em;
      color: #0f172a;
    }
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px 10px;
    }
    .reason-group .label {
      margin-top: 10px;
    }
    .reason-summary {
      margin: 4px 0 0;
      color: #334155;
      font-size: 13px;
      line-height: 1.4;
      font-weight: 600;
    }
    .ai-line {
      margin: 4px 0 0;
      color: #334155;
      font-size: 12px;
      line-height: 1.4;
      font-weight: 500;
    }
    .field {
      min-width: 0;
    }
    .label {
      margin: 0;
      color: var(--label);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .05em;
      font-weight: 700;
    }
    .value {
      margin: 4px 0 0;
      color: #0b1220;
      font-size: 14px;
      font-weight: 650;
      line-height: 1.35;
      word-break: break-word;
    }
    .value.rank {
      color: var(--score);
      font-size: 18px;
      font-weight: 800;
    }
    .value.reason {
      font-size: 12px;
      color: #334155;
      font-weight: 500;
    }
    a.link {
      color: #1d4ed8;
      text-decoration: none;
      font-weight: 700;
    }
    a.link:hover { text-decoration: underline; }
    .empty {
      margin-top: 12px;
      color: var(--muted);
      font-size: 14px;
      display: none;
      border: 1px dashed var(--line);
      border-radius: 10px;
      padding: 10px;
      background: #fafcff;
    }
    .controls {
      margin-top: 14px;
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 8px;
    }
    .controls input, .controls select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px 10px;
      font-size: 13px;
      background: #fff;
      color: #0f172a;
    }
    .table-wrap {
      margin-top: 12px;
      border: 1px solid var(--line);
      border-radius: 12px;
      overflow: auto;
      background: #fff;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 1050px;
    }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 10px;
      text-align: left;
      font-size: 13px;
      vertical-align: top;
      white-space: nowrap;
    }
    th {
      background: #f8fafc;
      color: #0f172a;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .04em;
    }
    th[data-sort] {
      cursor: pointer;
    }
    .pager {
      margin-top: 10px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      font-size: 12px;
      color: var(--muted);
    }
    .pager button {
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 8px;
      padding: 6px 10px;
      cursor: pointer;
      color: #0f172a;
      font-size: 12px;
    }
    .assumptions {
      margin-top: 14px;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px;
      background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
    }
    .assumptions p {
      margin: 6px 0;
      font-size: 13px;
      color: #334155;
    }
    .assumptions .formula {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      color: #0f172a;
      font-size: 12px;
    }
    .chip {
      display: inline-block;
      margin-left: 6px;
      padding: 2px 8px;
      font-size: 11px;
      font-weight: 700;
      border-radius: 999px;
      background: var(--chip-bg);
      color: #0f172a;
      vertical-align: middle;
    }
    @media (max-width: 1100px) {
      .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .rank-head { grid-template-columns: 110px 1fr; }
      .rank-head .field:last-child { grid-column: span 2; }
      .rank-body { grid-template-columns: 1fr; }
    }
    @media (max-width: 700px) {
      .kpis { grid-template-columns: 1fr; }
      .rank-head { grid-template-columns: 1fr; }
      .rank-head .field:last-child { grid-column: auto; }
      .metric-grid { grid-template-columns: 1fr; }
      .headline { font-size: 22px; }
      .controls { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="headcard">
      <p class="eyebrow">STR Investor Dashboard</p>
      <h1 class="headline">Coachella Valley STR Review Queue</h1>
      <p class="subline">High-level shortlist for which property to underwrite next.</p>
    </section>
    <section class="kpis">
      <article class="kpi">
        <p class="k">Total Listings</p>
        <p id="total-ingested" class="v">0</p>
        <p class="s">For-sale records scored</p>
      </article>
      <article class="kpi">
        <p class="k">STR Fit Passed</p>
        <p id="total-fit" class="v">0</p>
        <p class="s">Passed suitability filters</p>
      </article>
      <article class="kpi">
        <p class="k">Today's Listing Update</p>
        <p id="new-listings-today" class="v">0</p>
        <p id="listing-update-detail" class="s">Fetched 0 listings, 0 were new.</p>
        <p id="listings-pulled-at" class="s">Last run date: unavailable</p>
      </article>
    </section>
    <section class="module">
      <h2>Best Property Ranking for STR Review</h2>
      <p id="priority-note" class="module-note"></p>
      <div class="snapshot">
        <strong>STR Filter Snapshot</strong><span class="chip">Coachella Valley</span>
        <ul id="filter-snapshot"></ul>
      </div>
      <div id="ranking-list" class="rank-list"></div>
      <div id="priority-empty" class="empty"></div>
    </section>
    <section class="module">
      <h2>STR-Pass Listings Table View</h2>
      <p class="module-note">Sortable and filterable view for multi-listing comparison.</p>
      <div id="table-controls" class="controls">
        <input id="filter-city" type="text" placeholder="Filter city" />
        <input id="filter-min-price" type="number" placeholder="Min price" />
        <input id="filter-max-price" type="number" placeholder="Max price" />
        <input id="filter-min-post-tax-coc" type="number" step="0.01" placeholder="Min post-tax COC (decimal)" />
        <select id="sort-field">
          <option value="coc_post_tax">Sort: Post-Tax COC</option>
          <option value="coc_pre_tax">Sort: Pre-Tax COC</option>
          <option value="annual_cash_flow_med">Sort: Cash Flow (Med)</option>
          <option value="price_per_sqft">Sort: Price / SqFt</option>
          <option value="list_price">Sort: List Price</option>
          <option value="beds">Sort: Beds</option>
          <option value="full_baths">Sort: Baths</option>
          <option value="str_fit_score">Sort: STR Fit Score</option>
        </select>
        <select id="rows-per-page">
          <option value="10">10 rows</option>
          <option value="25" selected>25 rows</option>
          <option value="50">50 rows</option>
        </select>
      </div>
      <div class="table-wrap">
        <table id="listings-table">
          <thead>
            <tr>
              <th data-sort="address">Address</th>
              <th data-sort="city">City</th>
              <th data-sort="neighborhood">Neighborhood</th>
              <th data-sort="list_price">List Price</th>
              <th data-sort="price_per_sqft">Price / SqFt</th>
              <th data-sort="beds">Beds</th>
              <th data-sort="full_baths">Baths</th>
              <th data-sort="sqft">SqFt</th>
              <th data-sort="lot_sqft">Lot SqFt</th>
              <th data-sort="coc_pre_tax">Pre-Tax COC</th>
              <th data-sort="coc_post_tax">Post-Tax COC</th>
              <th data-sort="annual_cash_flow_med">Annual Cash Flow (Med)</th>
              <th data-sort="str_fit_score">STR Fit Score</th>
              <th>Link</th>
            </tr>
          </thead>
          <tbody id="table-body"></tbody>
        </table>
      </div>
      <div class="pager">
        <button id="prev-page" type="button">Previous</button>
        <span id="table-page-status">Page 1 of 1</span>
        <button id="next-page" type="button">Next</button>
      </div>
      <div id="table-empty" class="empty"></div>
    </section>
    <section class="module">
      <h2>COC Assumptions and Formula Summary</h2>
      <div id="assumptions-panel" class="assumptions"></div>
    </section>
  </div>
<script>
const payload = __PAYLOAD_JSON__;
const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
const pct = (v) => `${(Number(v || 0) * 100).toFixed(2)}%`;
const score100 = (v) => (Number(v || 0) * 100).toFixed(1);
let tableState = { page: 1, pageSize: 25, sortField: 'coc_post_tax', sortDir: 'desc' };
const pullTimestampFormatter = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/Los_Angeles',
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  second: '2-digit',
  timeZoneName: 'short',
});

function formatPullTimestamp(rawValue) {
  if (!rawValue) return 'Last run date: unavailable';
  const parsed = new Date(rawValue);
  if (Number.isNaN(parsed.getTime())) return 'Last run date: unavailable';
  return `Last run date: ${pullTimestampFormatter.format(parsed)}`;
}

function formatListingUpdateDetail(fetchedRows, newRows) {
  const fetched = Number(fetchedRows || 0);
  const netNew = Number(newRows || 0);
  return `Fetched ${fetched.toLocaleString()} listings, ${netNew.toLocaleString()} were new.`;
}

function renderPriorityRanking() {
  const container = document.getElementById('ranking-list');
  const empty = document.getElementById('priority-empty');
  container.innerHTML = '';

  const rows = payload.top_properties_palm_springs_priority || [];
  if (!rows.length) {
    empty.style.display = 'block';
    empty.textContent = 'No Coachella Valley priority candidates in the current dataset.';
    return;
  }

  empty.style.display = 'none';
  rows.forEach((p, idx) => {
    const rank = String(idx + 1);
    const listing = p.property_url
      ? `<a class="link" href="${p.property_url}">View Listing</a>`
      : '<span style="color:#94a3b8">No link</span>';
    const reasonSummary = p.priority_reason_summary || 'Balanced STR value profile.';
    const aiPotential = p.ai_insight_potential || 'Potential: no specific upside note available.';
    const aiRisk = p.ai_insight_risk || 'Risk: no major risk note available.';

    const row = document.createElement('article');
    row.className = 'rank-row';
    row.innerHTML = `
      <div class="rank-head">
        <div class="field"><p class="label">Rank</p><p class="value rank">${rank}</p></div>
        <div class="field"><p class="label">Property ID</p><p class="value">${p.property_id || 'n/a'}</p></div>
        <div class="field"><p class="label">Address</p><p class="value">${p.address || 'n/a'}<br>${listing}</p></div>
      </div>
      <div class="rank-body">
        <section class="group">
          <h3 class="group-title">What You Pay</h3>
          <div class="metric-grid">
            <div class="field"><p class="label">List Price</p><p class="value">${currency.format(Number(p.list_price || 0))}</p></div>
            <div class="field"><p class="label">Price / Sq Ft</p><p class="value">${currency.format(Number(p.price_per_sqft || 0))}</p></div>
            <div class="field"><p class="label">Lot Size</p><p class="value">${Number(p.lot_sqft || 0).toLocaleString()}</p></div>
            <div class="field"><p class="label">Bedrooms</p><p class="value">${Number(p.beds || 0).toFixed(0)}</p></div>
            <div class="field"><p class="label">Bathrooms</p><p class="value">${Number(p.full_baths || 0).toFixed(1)}</p></div>
          </div>
        </section>
        <section class="group">
          <h3 class="group-title">Expected Return</h3>
          <div class="metric-grid">
            <div class="field"><p class="label">Priority Score</p><p class="value">${score100(p.priority_score)}</p></div>
            <div class="field"><p class="label">Pre-Tax COC</p><p class="value">${pct(p.coc_pre_tax)}</p></div>
            <div class="field"><p class="label">Post-Tax COC</p><p class="value">${pct(p.coc_post_tax)}</p></div>
            <div class="field"><p class="label">Annual Cash Flow (Med)</p><p class="value">${currency.format(Number(p.annual_cash_flow_med || 0))}</p></div>
          </div>
        </section>
        <section class="group reason-group">
          <h3 class="group-title">Reason</h3>
          <p class="label">Ranking Driver</p>
          <p class="reason-summary">${reasonSummary}</p>
          <p class="label">AI Property Insight</p>
          <p class="ai-line">${aiPotential}</p>
          <p class="ai-line">${aiRisk}</p>
        </section>
      </div>
    `;
    container.appendChild(row);
  });
}

function _toNum(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function getFilteredTableRows() {
  const rows = payload.table_rows || [];
  const cityNeedle = (document.getElementById('filter-city').value || '').trim().toLowerCase();
  const minPrice = document.getElementById('filter-min-price').value;
  const maxPrice = document.getElementById('filter-max-price').value;
  const minPostTaxCoc = document.getElementById('filter-min-post-tax-coc').value;
  const minPriceNum = minPrice === '' ? null : Number(minPrice);
  const maxPriceNum = maxPrice === '' ? null : Number(maxPrice);
  const minCocNum = minPostTaxCoc === '' ? null : Number(minPostTaxCoc);

  return rows.filter((r) => {
    if (cityNeedle && !(String(r.city || '').toLowerCase().includes(cityNeedle))) return false;
    if (minPriceNum !== null && _toNum(r.list_price) < minPriceNum) return false;
    if (maxPriceNum !== null && _toNum(r.list_price) > maxPriceNum) return false;
    if (minCocNum !== null && _toNum(r.coc_post_tax) < minCocNum) return false;
    return true;
  });
}

function sortRows(rows) {
  const field = tableState.sortField;
  const dir = tableState.sortDir === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    const av = a[field];
    const bv = b[field];
    if (typeof av === 'string' || typeof bv === 'string') {
      return dir * String(av || '').localeCompare(String(bv || ''));
    }
    const delta = _toNum(av) - _toNum(bv);
    if (delta !== 0) return dir * delta;
    return String(a.property_id || '').localeCompare(String(b.property_id || ''));
  });
}

function renderTable() {
  const body = document.getElementById('table-body');
  const empty = document.getElementById('table-empty');
  const status = document.getElementById('table-page-status');
  body.innerHTML = '';

  const filtered = sortRows(getFilteredTableRows());
  const total = filtered.length;
  const pages = Math.max(1, Math.ceil(total / tableState.pageSize));
  tableState.page = Math.max(1, Math.min(tableState.page, pages));
  const start = (tableState.page - 1) * tableState.pageSize;
  const pageRows = filtered.slice(start, start + tableState.pageSize);

  if (!pageRows.length) {
    empty.style.display = 'block';
    empty.textContent = 'No listings match the current filters.';
  } else {
    empty.style.display = 'none';
  }

  pageRows.forEach((r) => {
    const tr = document.createElement('tr');
    const link = r.property_url ? `<a class="link" href="${r.property_url}">Open</a>` : '<span style="color:#94a3b8">n/a</span>';
    tr.innerHTML = `
      <td>${r.address || 'n/a'}</td>
      <td>${r.city || 'n/a'}</td>
      <td>${r.neighborhood || 'n/a'}</td>
      <td>${currency.format(_toNum(r.list_price))}</td>
      <td>${currency.format(_toNum(r.price_per_sqft))}</td>
      <td>${_toNum(r.beds).toFixed(0)}</td>
      <td>${_toNum(r.full_baths).toFixed(1)}</td>
      <td>${_toNum(r.sqft).toLocaleString()}</td>
      <td>${_toNum(r.lot_sqft).toLocaleString()}</td>
      <td>${pct(_toNum(r.coc_pre_tax))}</td>
      <td>${pct(_toNum(r.coc_post_tax))}</td>
      <td>${currency.format(_toNum(r.annual_cash_flow_med))}</td>
      <td>${_toNum(r.str_fit_score).toFixed(0)}</td>
      <td>${link}</td>
    `;
    body.appendChild(tr);
  });

  status.textContent = `Page ${tableState.page} of ${pages} (${total.toLocaleString()} rows)`;
  document.getElementById('prev-page').disabled = tableState.page <= 1;
  document.getElementById('next-page').disabled = tableState.page >= pages;
}

function renderAssumptionsPanel() {
  const panel = document.getElementById('assumptions-panel');
  const data = payload.coc_assumptions_summary || {};
  if (!Object.keys(data).length) {
    panel.innerHTML = '<p>Assumptions summary unavailable.</p>';
    return;
  }

  const tax = data.tax || {};
  const financing = data.financing || {};
  const cost = data.cost_model || {};

  panel.innerHTML = `
    <p class="formula">${data.pre_tax_formula || ''}</p>
    <p class="formula">${data.post_tax_formula || ''}</p>
    <p>${data.note || ''}</p>
    <p><strong>Tax Inputs:</strong> Effective tax ${(100 * _toNum(tax.effective_combined_tax_rate)).toFixed(1)}%, analysis year ${_toNum(tax.analysis_year).toFixed(0)}, building allocation ${(100 * _toNum(tax.building_allocation_pct)).toFixed(1)}%, recovery ${_toNum(tax.standard_recovery_years).toFixed(1)} years, cost-seg start year ${_toNum(tax.cost_seg_start_year).toFixed(0)}, cost-seg bonus ${(100 * _toNum(tax.cost_seg_bonus_pct)).toFixed(1)}%.</p>
    <p><strong>Financing Inputs:</strong> Down payment ${(100 * _toNum(financing.down_payment_pct)).toFixed(1)}%, interest ${(100 * _toNum(financing.interest_rate_annual)).toFixed(2)}%, loan term ${_toNum(financing.loan_term_years).toFixed(0)} years.</p>
    <p><strong>Core Opex Ratios:</strong> Management ${(100 * _toNum(cost.management_fee_pct)).toFixed(1)}%, capex ${(100 * _toNum(cost.capex_pct)).toFixed(1)}%, maintenance ${(100 * _toNum(cost.maintenance_pct)).toFixed(1)}%, vacancy buffer ${(100 * _toNum(cost.vacancy_buffer_pct)).toFixed(1)}%, turnover buffer ${(100 * _toNum(cost.turnover_buffer_pct)).toFixed(1)}%.</p>
    <p>${data.caveat || ''}</p>
  `;
}

function bindTableControls() {
  ['filter-city', 'filter-min-price', 'filter-max-price', 'filter-min-post-tax-coc'].forEach((id) => {
    document.getElementById(id).addEventListener('input', () => {
      tableState.page = 1;
      renderTable();
    });
  });
  document.getElementById('rows-per-page').addEventListener('change', (e) => {
    tableState.pageSize = Number(e.target.value || 25);
    tableState.page = 1;
    renderTable();
  });
  document.getElementById('sort-field').addEventListener('change', (e) => {
    tableState.sortField = e.target.value || 'coc_post_tax';
    tableState.page = 1;
    renderTable();
  });
  document.querySelectorAll('th[data-sort]').forEach((th) => {
    th.addEventListener('click', () => {
      const field = th.getAttribute('data-sort');
      if (!field) return;
      if (tableState.sortField === field) {
        tableState.sortDir = tableState.sortDir === 'asc' ? 'desc' : 'asc';
      } else {
        tableState.sortField = field;
        tableState.sortDir = 'desc';
      }
      tableState.page = 1;
      renderTable();
    });
  });
  document.getElementById('prev-page').addEventListener('click', () => {
    tableState.page = Math.max(1, tableState.page - 1);
    renderTable();
  });
  document.getElementById('next-page').addEventListener('click', () => {
    tableState.page += 1;
    renderTable();
  });
}

function init() {
  document.getElementById('total-ingested').textContent = String(payload.total_ingested || 0);
  document.getElementById('total-fit').textContent = String(payload.total_str_fit_passed || 0);
  document.getElementById('new-listings-today').textContent = String(payload.new_listings_today || 0);
  document.getElementById('listing-update-detail').textContent = formatListingUpdateDetail(
    payload.fetched_rows_today,
    payload.new_listings_today,
  );
  document.getElementById('listings-pulled-at').textContent = formatPullTimestamp(payload.listings_pulled_at);
  document.getElementById('priority-note').textContent = payload.priority_ranking_note || '';

  const snapshot = document.getElementById('filter-snapshot');
  snapshot.innerHTML = '';
  (payload.str_filter_snapshot || []).forEach((line) => {
    const item = document.createElement('li');
    item.textContent = line;
    snapshot.appendChild(item);
  });

  renderPriorityRanking();
  bindTableControls();
  renderTable();
  renderAssumptionsPanel();
}

init();
</script>
</body>
</html>
""".replace(
        "__PAYLOAD_JSON__", data_json
    )


def write_dashboard_html(payload: dict[str, Any], output_path: str | Path) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_dashboard_html(payload), encoding="utf-8")


def main() -> None:
    args = parse_args()
    scored_df = load_scored_data(args.input)
    health_report = _load_incremental_health_report(args.health_report_input)
    payload = build_dashboard_payload(
        scored_df,
        top_n=args.top_n,
        homes_limit=args.homes_limit,
        health_report=health_report,
    )
    write_dashboard_html(payload, args.output)
    print(
        f"Input scored rows: {len(scored_df)}\n"
        f"Total ingested: {payload['total_ingested']}\n"
        f"STR fit passed: {payload['total_str_fit_passed']}\n"
        f"Top rows displayed: {len(payload['top_properties'])}\n"
        f"Interactive homes loaded (STR fit): {len(payload['homes'])}\n"
        f"Dashboard HTML: {Path(args.output).resolve()}"
    )


if __name__ == "__main__":
    main()

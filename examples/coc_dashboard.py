from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_INPUT_PATH = Path("examples/zips/coc_scorecard.xlsx")
DEFAULT_OUTPUT_PATH = Path("examples/zips/coc_dashboard.html")
DEFAULT_HEALTH_REPORT_PATH = Path("examples/zips/incremental_health_report.json")
DEFAULT_ASSUMPTIONS_PATH = Path("examples/data/coc_assumptions.json")
BUDGET_LUXURY_MAX_PRICE = 1_500_000.0
BUDGET_LUXURY_TOP_N = 30
DASHBOARD_MAX_LIST_PRICE = 1_500_000.0
EXCLUDED_PROPERTY_IDS = {"2310318356", "2002934800"}
EXCLUDED_PROPERTY_SIGNATURES = {
    ("1961 s palm canyon dr", "palm springs", "ca", "92264"),
    ("3467 savanna way", "palm springs", "ca", "92262"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build static COC dashboard HTML from scorecard workbook")
    parser.add_argument("--input", default=str(DEFAULT_INPUT_PATH), help="Input COC scorecard workbook path")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="Output dashboard HTML path")
    parser.add_argument("--top-n", type=int, default=10, help="Top N rows to display in COC table")
    parser.add_argument(
        "--homes-limit",
        type=int,
        default=0,
        help="Max homes loaded in interactive breakdown (0 loads all STR-fit passed listings)",
    )
    parser.add_argument(
        "--health-report-input",
        default=str(DEFAULT_HEALTH_REPORT_PATH),
        help="Optional incremental health report JSON used for KPI metadata.",
    )
    parser.add_argument(
        "--assumptions-input",
        default=str(DEFAULT_ASSUMPTIONS_PATH),
        help="COC assumptions JSON used for Palm Springs constraint and tier benchmark metadata.",
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
    return full_address in {
        "1961 s palm canyon dr palm springs ca 92264",
        "3467 savanna way palm springs ca 92262",
    }


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
    sqft = _safe_float(row.get("sqft"))
    list_price = _safe_float(row.get("list_price"))
    price_per_sqft = (list_price / sqft) if sqft > 0 else 0.0

    insights = _ai_insights(row)

    return {
        "property_id": _safe_str(row.get("property_id")),
        "address": address,
        "city": city,
        "zip_code": zip_code,
        "property_url": _safe_str(row.get("property_url")),
        "list_price": list_price,
        "sqft": sqft,
        "price_per_sqft": price_per_sqft,
        "beds": _safe_float(row.get("beds")),
        "full_baths": _safe_float(row.get("full_baths")),
        "scenario_tier": _safe_str(row.get("scenario_tier")),
        "tier_auto": _safe_str(row.get("tier_auto")),
        "tier_final": _safe_str(row.get("tier_final")),
        "tier_source": _safe_str(row.get("tier_source"), "auto"),
        "monthly_debt_payment": _safe_float(row.get("monthly_debt_payment")),
        "annual_debt_service": _safe_float(row.get("annual_debt_service")),
        "total_cash_cost_to_buy": _safe_float(row.get("total_cash_cost_to_buy")),
        "annual_fixed_operating_costs": annual_fixed,
        "operating_variable_ratio": variable_ratio,
        "adr_low": _safe_float(row.get("adr_low")),
        "adr_med": _safe_float(row.get("adr_med")),
        "adr_high": _safe_float(row.get("adr_high")),
        "adr_auto": _safe_float(row.get("adr_auto")),
        "adr_final": _safe_float(row.get("adr_final"), _safe_float(row.get("adr_med"))),
        "adr_source": _safe_str(row.get("adr_source"), "auto"),
        "occ_low": _safe_float(row.get("occupancy_low")),
        "occ_med": _safe_float(row.get("occupancy_med")),
        "occ_high": _safe_float(row.get("occupancy_high")),
        "occupancy_auto": _safe_float(row.get("occupancy_auto")),
        "occupancy_final": _safe_float(row.get("occupancy_final"), _safe_float(row.get("occupancy_med"))),
        "occupancy_source": _safe_str(row.get("occupancy_source"), "auto"),
        "override_last_updated_at": _safe_str(row.get("override_last_updated_at")),
        "override_note": _safe_str(row.get("override_note")),
        "coc_low": _safe_float(row.get("coc_low")),
        "coc_med": _safe_float(row.get("coc_med")),
        "coc_high": _safe_float(row.get("coc_high")),
        "coc_pre_tax": _safe_float(row.get("coc_pre_tax"), _safe_float(row.get("coc_med"))),
        "coc_post_tax": _safe_float(row.get("coc_post_tax"), _safe_float(row.get("coc_med"))),
        "annual_cash_flow_low": _safe_float(row.get("annual_cash_flow_low")),
        "annual_cash_flow_med": _safe_float(row.get("annual_cash_flow_med")),
        "annual_cash_flow_high": _safe_float(row.get("annual_cash_flow_high")),
        "annual_revenue_med": annual_revenue_med,
        "annual_operating_cost_med": annual_operating_med,
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
                "adr_auto": _safe_float(row.get("adr_auto")),
                "adr_final": _safe_float(row.get("adr_final"), _safe_float(row.get("adr_med"))),
                "adr_source": _safe_str(row.get("adr_source"), "auto"),
                "occupancy_auto": _safe_float(row.get("occupancy_auto")),
                "occupancy_final": _safe_float(row.get("occupancy_final"), _safe_float(row.get("occupancy_med"))),
                "occupancy_source": _safe_str(row.get("occupancy_source"), "auto"),
                "tier_auto": _safe_str(row.get("tier_auto")),
                "tier_final": _safe_str(row.get("tier_final"), _safe_str(row.get("scenario_tier"))),
                "tier_source": _safe_str(row.get("tier_source"), "auto"),
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


def _load_coc_assumptions(path: str | Path) -> dict[str, Any]:
    assumptions_path = Path(path)
    if not assumptions_path.exists():
        return {}
    try:
        payload = json.loads(assumptions_path.read_text(encoding="utf-8"))
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
    full_scrape_completed_at: str | None = None,
    coc_assumptions: dict[str, Any] | None = None,
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
    priority_rows = _palm_springs_priority_rows(scored, top_n)
    watchlist_rows = _pool_watchlist_rows(scored, top_n=30)
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
    effective_homes_limit = int(homes_limit) if int(homes_limit) > 0 else int(len(fit))
    homes_fit = [_row_to_home_payload(row) for _, row in fit.head(effective_homes_limit).iterrows()]
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
    if coc_assumptions is None:
        coc_assumptions = {}
    summary = health_report.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    new_listings_today = int(_safe_float(summary.get("new_rows"), 0.0))
    fetched_rows_today = int(_safe_float(summary.get("fetched_rows"), 0.0))
    listings_pulled_at = _safe_str(health_report.get("batch_run_at")).strip() or None
    contract_policy = coc_assumptions.get("contract_policy", {}) if isinstance(coc_assumptions, dict) else {}
    mtr = coc_assumptions.get("mtr", {}) if isinstance(coc_assumptions, dict) else {}
    scenario_presets = coc_assumptions.get("scenario_presets", {}) if isinstance(coc_assumptions, dict) else {}
    tier_benchmarks = {
        "average": scenario_presets.get("palm_springs_normal", {}),
        "luxury": scenario_presets.get("palm_springs_luxury", {}),
    }

    return {
        "total_ingested": int(len(scored)),
        "total_str_fit_passed": int(len(fit)),
        "new_listings_today": new_listings_today,
        "fetched_rows_today": fetched_rows_today,
        "listings_pulled_at": listings_pulled_at,
        "full_scrape_completed_at": full_scrape_completed_at,
        "top_properties": top_fit,
        "top_properties_luxury": top_luxury,
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
            "Palm Springs/Bermuda Dunes/Indio STR-pass listings sorted by pre-tax COC "
            "(tie-break: post-tax COC, then priority score). "
            "Dashboard view is capped at $1,500,000 list price."
        ),
        "homes": homes_fit,
        "total_houses_on_sale": int(len(scored)),
        "str_filter_snapshot": [
            "STR-allowed neighborhoods",
            "Beds/Baths minimum: 2+/2+",
            "Private pool required (verified/inferred high-confidence)",
            "Under $1.5M list price",
            "Preferred cities: Palm Springs, Bermuda Dunes, Indio",
            "ZIP must be in approved under-cap STR neighborhood set",
        ],
        "contract_policy": {
            "annual_bookable_nights": _safe_float(contract_policy.get("annual_bookable_nights"), 365.0),
            "max_str_bookings_per_year": _safe_float(contract_policy.get("max_str_bookings_per_year"), 26.0),
            "avg_stay_nights_per_booking": _safe_float(contract_policy.get("avg_stay_nights_per_booking"), 4.0),
        },
        "mtr": {
            "mtr_adr_multiplier": _safe_float(mtr.get("mtr_adr_multiplier"), 0.55),
            "mtr_occupancy": _safe_float(mtr.get("mtr_occupancy"), 0.72),
        },
        "tier_benchmarks": tier_benchmarks,
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
    .wrap { width: 100%; margin: 24px 0 36px; padding: 0 18px; }
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
    .kpi details {
      margin-top: 8px;
      border-top: 1px solid #e5eaf2;
      padding-top: 8px;
    }
    .kpi summary {
      cursor: pointer;
      font-size: 12px;
      font-weight: 700;
      color: #334155;
      user-select: none;
    }
    .kpi details ul {
      margin: 6px 0 0;
      padding-left: 16px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
    }
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
    .overview-header-row {
      margin-top: 10px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) 420px;
      gap: 14px;
      align-items: start;
    }
    .overview-summary {
      min-width: 0;
    }
    .finance-toolbar {
      display: flex;
      justify-content: flex-end;
      margin-top: -3px;
    }
    .finance-widget {
      border: 1px solid var(--line);
      border-radius: 12px;
      background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
      padding: 12px;
      width: min(420px, 100%);
    }
    .finance-widget h3 {
      margin: 0 0 6px;
      font-size: 16px;
    }
    .finance-sub {
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.4;
    }
    .finance-group {
      border-top: 1px solid #e2e8f0;
      padding-top: 10px;
      margin-top: 10px;
    }
    .finance-group:first-of-type {
      border-top: none;
      padding-top: 0;
      margin-top: 0;
    }
    .finance-label {
      margin: 0 0 6px;
      color: #334155;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .05em;
      font-weight: 700;
    }
    .finance-option {
      display: flex;
      align-items: flex-start;
      gap: 8px;
      margin: 0 0 6px;
      font-size: 12px;
      color: #0f172a;
    }
    .finance-option strong {
      display: block;
      font-size: 12px;
    }
    .finance-hint {
      margin: 0;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.35;
    }
    .finance-metrics {
      margin: 8px 0 0;
      display: grid;
      gap: 6px;
    }
    .finance-metrics p {
      margin: 0;
      font-size: 12px;
      color: #0f172a;
      display: flex;
      justify-content: space-between;
      gap: 8px;
    }
    .constraint-panel {
      border: 1px solid #c7d2fe;
      border-radius: 10px;
      background: linear-gradient(180deg, #ffffff 0%, #f5f9ff 100%);
      padding: 10px;
      margin: 4px 0;
    }
    .constraint-grid {
      display: grid;
      grid-template-columns: 1.3fr 1fr;
      gap: 12px;
      align-items: start;
    }
    .constraint-group {
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 10px;
      background: #fff;
    }
    .constraint-group h4 {
      margin: 0 0 8px;
      font-size: 13px;
    }
    .constraint-field { margin: 0 0 8px; }
    .constraint-field label {
      display: block;
      margin-bottom: 4px;
      font-size: 11px;
      color: #334155;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .04em;
    }
    .constraint-field input, .constraint-field select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 6px 8px;
      font-size: 12px;
      background: #fff;
    }
    .constraint-tier-toggle {
      display: inline-flex;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    .constraint-tier-toggle button {
      border: none;
      background: #fff;
      padding: 6px 10px;
      font-size: 12px;
      cursor: pointer;
      font-weight: 700;
      color: #334155;
    }
    .constraint-tier-toggle button.active {
      background: #bfdbfe;
      color: #1e3a8a;
    }
    .constraint-formula {
      margin: 0 0 6px;
      font-size: 12px;
      color: #0f172a;
      display: flex;
      justify-content: space-between;
      gap: 8px;
    }
    .constraint-badge {
      display: inline-block;
      border: 1px solid #cbd5e1;
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 11px;
      font-weight: 700;
      color: #334155;
      background: #f8fafc;
      margin-right: 5px;
    }
    .constraint-delta-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }
    .constraint-delta {
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      padding: 8px;
      background: #fff;
    }
    .constraint-delta p { margin: 0; }
    .constraint-delta .k { font-size: 11px; color: #64748b; }
    .constraint-delta .v { margin-top: 4px; font-size: 14px; font-weight: 800; color: #14532d; }
    .constraint-delta .d { margin-top: 2px; font-size: 11px; color: #0f766e; font-weight: 700; }
    .constraint-toggle-btn {
      border: 1px solid #bfdbfe;
      background: #dbeafe;
      color: #1e3a8a;
      font-size: 11px;
      font-weight: 700;
      border-radius: 8px;
      padding: 5px 8px;
      cursor: pointer;
      white-space: nowrap;
    }
    .constraint-note {
      font-size: 11px;
      color: #64748b;
    }
    .table-controls {
      margin-top: 14px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
    }
    .table-controls .left,
    .table-controls .right {
      display: flex;
      align-items: center;
      gap: 10px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
    }
    .table-controls .left .filter-label {
      margin-left: 8px;
    }
    .table-controls select,
    .table-controls button {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      color: #0f172a;
      font-size: 12px;
      padding: 6px 8px;
    }
    .table-controls button {
      font-weight: 700;
      cursor: pointer;
    }
    .table-controls button:disabled {
      cursor: not-allowed;
      opacity: 0.45;
    }
    .table-wrap {
      margin-top: 10px;
      border: 1px solid var(--line);
      border-radius: 12px;
      overflow: auto;
      background: #fff;
      max-height: 70vh;
    }
    table.listings-table {
      width: 100%;
      min-width: 1700px;
      border-collapse: separate;
      border-spacing: 0;
      font-size: 12px;
      line-height: 1.2;
    }
    .listings-table thead th {
      position: sticky;
      top: 0;
      z-index: 2;
      background: #eef2ff;
      color: #1e293b;
      text-transform: uppercase;
      letter-spacing: .04em;
      font-size: 10px;
      padding: 8px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      white-space: nowrap;
    }
    .listings-table tbody td {
      padding: 7px 10px;
      border-bottom: 1px solid #eef2f7;
      color: #0f172a;
      white-space: nowrap;
      vertical-align: middle;
    }
    .listings-table tbody tr:nth-child(even) td {
      background: #f8fafc;
    }
    .listings-table tbody tr:hover td {
      background: #eff6ff;
    }
    .col-address {
      min-width: 300px;
      white-space: normal !important;
    }
    .num {
      text-align: right;
      font-variant-numeric: tabular-nums;
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
      .overview-header-row { grid-template-columns: 1fr; }
      .finance-toolbar { justify-content: stretch; }
      .finance-widget { width: 100%; }
      .constraint-grid { grid-template-columns: 1fr; }
    }
    @media (max-width: 700px) {
      .kpis { grid-template-columns: 1fr; }
      .headline { font-size: 22px; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="headcard">
      <p class="eyebrow">STR Investor Dashboard</p>
      <h1 class="headline">Palm Springs / Bermuda Dunes / Indio STR Review Queue</h1>
      <p class="subline">High-level shortlist for which property to underwrite next.</p>
    </section>
    <section class="kpis">
      <article class="kpi">
        <p class="k">Total Listings</p>
        <p id="total-ingested" class="v">0</p>
        <p class="s">For-sale records scored</p>
        <p id="full-scrape-at" class="s">Full scrape: unavailable</p>
      </article>
      <article class="kpi">
        <p class="k">STR Fit Passed</p>
        <p id="total-fit" class="v">0</p>
        <p class="s">Passed suitability filters</p>
        <details>
          <summary>STR Filters Applied</summary>
          <ul id="str-filter-kpi-list"></ul>
        </details>
      </article>
      <article class="kpi">
        <p class="k">Today's Listing Update</p>
        <p id="new-listings-today" class="v">0</p>
        <p id="listing-update-detail" class="s">Fetched 0 listings, 0 were new.</p>
        <p id="listings-pulled-at" class="s">Last run date: unavailable</p>
      </article>
    </section>
    <section class="module">
      <div class="overview-header-row">
        <div class="overview-summary">
          <h2>Listings Overview</h2>
          <p id="priority-note" class="module-note"></p>
          <div class="snapshot">
            <strong>STR Filter Snapshot</strong><span class="chip">Palm Springs • Bermuda Dunes • Indio</span>
            <ul id="filter-snapshot"></ul>
          </div>
        </div>
        <div class="finance-toolbar">
          <aside class="finance-widget">
            <h3>Financing Options</h3>
            <p class="finance-sub">Global scenario applied to all listings in this table.</p>
            <div class="finance-group">
              <p class="finance-label">Mortgage Mode</p>
              <label class="finance-option">
                <input id="mortgage-second-home" type="radio" name="mortgage-mode" value="second_home" checked />
                <span><strong>Second Home</strong>5.75% rate, 10% down</span>
              </label>
              <label class="finance-option">
                <input id="mortgage-investment" type="radio" name="mortgage-mode" value="investment_home" />
                <span><strong>Investment Home</strong>6.25% rate, 25% down</span>
              </label>
            </div>
            <div class="finance-group">
              <p class="finance-label">Down Payment Source</p>
              <label class="finance-option">
                <input id="heloc-enabled" type="checkbox" checked />
                <span><strong>HELOC enabled</strong>Use SF condo HELOC for down payment (interest-only).</span>
              </label>
              <p class="finance-hint">HELOC draw strategy: down payment only. HELOC APR: 8.50%.</p>
            </div>
            <div class="finance-group">
              <p class="finance-label">Active Assumptions</p>
              <div class="finance-metrics">
                <p><span>Mortgage Rate</span><strong id="active-rate">5.75%</strong></p>
                <p><span>Down Payment</span><strong id="active-down">10%</strong></p>
                <p><span>HELOC</span><strong id="active-heloc">On</strong></p>
              </div>
            </div>
          </aside>
        </div>
      </div>
      <div class="table-controls">
        <div class="left">
          <span id="table-count"></span>
          <label class="filter-label" for="city-filter">City</label>
          <select id="city-filter">
            <option value="all" selected>All</option>
          </select>
          <label for="rows-per-page">Rows/page</label>
          <select id="rows-per-page">
            <option value="25">25</option>
            <option value="50" selected>50</option>
            <option value="100">100</option>
          </select>
        </div>
        <div class="right">
          <button id="page-prev" type="button">Prev</button>
          <span id="page-indicator"></span>
          <button id="page-next" type="button">Next</button>
        </div>
      </div>
      <div class="table-wrap">
        <table class="listings-table">
          <thead>
            <tr>
              <th data-sort-key="rank" data-sort-type="number">Rank</th>
              <th data-sort-key="property_id" data-sort-type="string">Property ID</th>
              <th data-sort-key="address" data-sort-type="string">Address</th>
              <th data-sort-key="city" data-sort-type="string">City</th>
              <th data-sort-key="zip_code" data-sort-type="string">ZIP</th>
              <th data-sort-key="list_price" data-sort-type="number">List Price</th>
              <th data-sort-key="sqft" data-sort-type="number">Sq Ft</th>
              <th data-sort-key="price_per_sqft" data-sort-type="number">Price / Sq Ft</th>
              <th data-sort-key="beds" data-sort-type="number">Beds</th>
              <th data-sort-key="full_baths" data-sort-type="number">Baths</th>
              <th data-sort-key="coc_pre_tax" data-sort-type="number">Pre-Tax COC</th>
              <th data-sort-key="coc_post_tax" data-sort-type="number">Post-Tax COC</th>
              <th data-sort-key="annual_cash_flow_med" data-sort-type="number">Annual Cash Flow (Med)</th>
              <th data-sort-key="adr_med" data-sort-type="number">ADR (Med)</th>
              <th data-sort-key="occ_med" data-sort-type="number">Occ (Med)</th>
              <th data-sort-key="total_cash_cost_to_buy" data-sort-type="number">Total Cash To Buy</th>
              <th data-sort-key="monthly_debt_payment" data-sort-type="number">Monthly Debt</th>
              <th data-sort-key="str_fit_score" data-sort-type="number">STR Fit Score</th>
              <th>Palm Springs Constraints</th>
            </tr>
          </thead>
          <tbody id="ranking-list"></tbody>
        </table>
      </div>
      <div id="priority-empty" class="empty"></div>
    </section>
  </div>
<script>
const payload = __PAYLOAD_JSON__;
const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
const pct = (v) => `${(Number(v || 0) * 100).toFixed(2)}%`;
const sourceBadge = (source) => {
  const isManual = String(source || '').toLowerCase() === 'manual';
  return `<span class="constraint-badge">${isManual ? 'MANUAL' : 'AUTO'}</span>`;
};
let currentPage = 1;
let rowsPerPage = 50;
let sortedRows = [];
let filteredRows = [];
let activeSortKey = 'coc_post_tax';
let activeSortDirection = 'desc';
let activeCityFilter = 'all';
const financingConfig = {
  second_home: { rateAnnual: 0.0575, downPct: 0.10, labelRate: '5.75%', labelDown: '10%' },
  investment_home: { rateAnnual: 0.0625, downPct: 0.25, labelRate: '6.25%', labelDown: '25%' },
  helocRateAnnual: 0.085,
  loanTermYears: 30,
  baselineDownPct: 0.10,
};
let activeMortgageMode = 'second_home';
let helocEnabled = true;
let scenarioRows = [];
const rowConstraintState = {};
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

function formatFullScrapeTimestamp(rawValue) {
  if (!rawValue) return 'Full scrape: unavailable';
  const parsed = new Date(rawValue);
  if (Number.isNaN(parsed.getTime())) return 'Full scrape: unavailable';
  return `Full scrape: ${pullTimestampFormatter.format(parsed)}`;
}

function formatListingUpdateDetail(fetchedRows, newRows) {
  const fetched = Number(fetchedRows || 0);
  const netNew = Number(newRows || 0);
  return `Fetched ${fetched.toLocaleString()} listings, ${netNew.toLocaleString()} were new.`;
}

function formatInt(value) {
  return Number(value || 0).toLocaleString();
}

function asPct(value) {
  return `${(Number(value || 0) * 100).toFixed(2)}%`;
}

function toTierView(scenarioTier) {
  return String(scenarioTier || '').toLowerCase() === 'palm_springs_luxury' ? 'luxury' : 'average';
}

function isPalmSpringsRow(row) {
  return String(row?.city || '').trim().toLowerCase() === 'palm springs';
}

function mortgagePayment(principal, annualRate, years) {
  if (principal <= 0) return 0;
  const monthlyRate = annualRate / 12;
  const months = years * 12;
  if (monthlyRate <= 0 || months <= 0) return principal / Math.max(1, months);
  const factor = Math.pow(1 + monthlyRate, months);
  return principal * ((monthlyRate * factor) / (factor - 1));
}

function scenarioForRow(row) {
  const loan = financingConfig[activeMortgageMode] || financingConfig.second_home;
  const listPrice = Number(row.list_price || 0);
  const downPayment = listPrice * loan.downPct;
  const primaryLoan = Math.max(0, listPrice - downPayment);
  const monthlyMortgage = mortgagePayment(primaryLoan, loan.rateAnnual, financingConfig.loanTermYears);
  const helocDraw = helocEnabled ? downPayment : 0;
  const monthlyHeloc = helocEnabled ? (helocDraw * financingConfig.helocRateAnnual) / 12 : 0;
  const monthlyDebtPayment = monthlyMortgage + monthlyHeloc;

  const baselineCashToBuy = Number(row.total_cash_cost_to_buy || 0);
  const baselineDownPayment = listPrice * financingConfig.baselineDownPct;
  const baselineOtherCash = Math.max(0, baselineCashToBuy - baselineDownPayment);
  const totalCashToBuy = baselineOtherCash + downPayment - helocDraw;

  const baselineAnnualCashFlow = Number(row.annual_cash_flow_med || 0);
  const baselineAnnualDebt = Number(row.monthly_debt_payment || 0) * 12;
  const annualCashBeforeDebt = baselineAnnualCashFlow + baselineAnnualDebt;
  const annualCashFlowMed = annualCashBeforeDebt - (monthlyDebtPayment * 12);

  const baselineCocPost = Number(row.coc_post_tax || 0);
  const baselineAnnualPostTax = baselineCocPost * baselineCashToBuy;
  const postTaxDelta = baselineAnnualPostTax - baselineAnnualCashFlow;
  const annualCashFlowPostTax = annualCashFlowMed + postTaxDelta;

  const cocPreTax = totalCashToBuy > 0 ? (annualCashFlowMed / totalCashToBuy) : 0;
  const cocPostTax = totalCashToBuy > 0 ? (annualCashFlowPostTax / totalCashToBuy) : 0;

  return {
    ...row,
    monthly_debt_payment: monthlyDebtPayment,
    total_cash_cost_to_buy: totalCashToBuy,
    annual_cash_flow_med: annualCashFlowMed,
    coc_pre_tax: cocPreTax,
    coc_post_tax: cocPostTax,
  };
}

function constraintScenarioForRow(row, state) {
  if (!row) return null;
  const contractPolicy = payload.contract_policy || {};
  const mtrPolicy = payload.mtr || {};
  const annualNights = Number(contractPolicy.annual_bookable_nights || 365);
  const maxBookings = Number(contractPolicy.max_str_bookings_per_year || 26);
  const avgStay = Math.max(1, Number(state.avgStay || 0));
  const strNights = Math.min(annualNights, maxBookings * avgStay);
  const mtrNights = Math.max(0, annualNights - strNights);

  const strOcc = Number(row.occupancy_final || row.occ_med || 0);
  const adr = Math.max(0, Number(state.adr || 0));
  const mtrAdrMultiplier = Number(mtrPolicy.mtr_adr_multiplier || 0.55);
  const mtrOcc = Number(mtrPolicy.mtr_occupancy || 0.72);
  const mtrAdr = adr * mtrAdrMultiplier;

  const strRevenue = strNights * adr * strOcc;
  const mtrRevenue = mtrNights * mtrAdr * mtrOcc;
  const blendedRevenue = strRevenue + mtrRevenue;

  const baselineRevenue = Number(row.annual_revenue_med || 0);
  const revenueDelta = blendedRevenue - baselineRevenue;
  const variableRatio = Number(row.operating_variable_ratio || 0);
  const operatingDelta = revenueDelta * variableRatio;

  const baselineAnnualCashFlow = Number(row.annual_cash_flow_med || 0);
  const adjustedAnnualCashFlow = baselineAnnualCashFlow + revenueDelta - operatingDelta;

  const baselineCocPost = Number(row.coc_post_tax || 0);
  const baselineCashToBuy = Number(row.total_cash_cost_to_buy || 0);
  const baselineAnnualPostTax = baselineCocPost * baselineCashToBuy;
  const postTaxDelta = baselineAnnualPostTax - baselineAnnualCashFlow;
  const adjustedAnnualPostTax = adjustedAnnualCashFlow + postTaxDelta;

  const cocPreTax = baselineCashToBuy > 0 ? adjustedAnnualCashFlow / baselineCashToBuy : 0;
  const cocPostTax = baselineCashToBuy > 0 ? adjustedAnnualPostTax / baselineCashToBuy : 0;

  return {
    strNights,
    mtrNights,
    strShare: annualNights > 0 ? strNights / annualNights : 0,
    mtrShare: annualNights > 0 ? mtrNights / annualNights : 0,
    blendedRevenue,
    annualCashFlow: adjustedAnnualCashFlow,
    preTaxCoc: cocPreTax,
    postTaxCoc: cocPostTax,
    baselineAnnualCashFlow,
    baselinePreTaxCoc: Number(row.coc_pre_tax || 0),
    baselinePostTaxCoc: baselineCocPost,
  };
}

function computeScenarioRows() {
  scenarioRows = (payload.homes || []).map((row) => scenarioForRow(row));
}

function getSortValue(row, key, type, rankIndex) {
  if (key === 'rank') return rankIndex;
  const raw = row?.[key];
  if (type === 'number') return Number(raw || 0);
  return String(raw || '').toLowerCase();
}

function sortRows(rows) {
  const typeMap = {
    rank: 'number',
    property_id: 'string',
    address: 'string',
    city: 'string',
    zip_code: 'string',
    list_price: 'number',
    sqft: 'number',
    price_per_sqft: 'number',
    beds: 'number',
    full_baths: 'number',
    coc_pre_tax: 'number',
    coc_post_tax: 'number',
    annual_cash_flow_med: 'number',
    adr_med: 'number',
    occ_med: 'number',
    total_cash_cost_to_buy: 'number',
    monthly_debt_payment: 'number',
    str_fit_score: 'number',
    property_url: 'string',
  };
  const sortType = typeMap[activeSortKey] || 'string';
  return [...rows].sort((a, b) => {
    const aValue = getSortValue(a, activeSortKey, sortType, 0);
    const bValue = getSortValue(b, activeSortKey, sortType, 0);
    if (aValue < bValue) return activeSortDirection === 'asc' ? -1 : 1;
    if (aValue > bValue) return activeSortDirection === 'asc' ? 1 : -1;
    const cocDelta = Number(b.coc_post_tax || 0) - Number(a.coc_post_tax || 0);
    if (cocDelta !== 0) return cocDelta;
    const scoreDelta = Number(b.str_fit_score || 0) - Number(a.str_fit_score || 0);
    if (scoreDelta !== 0) return scoreDelta;
    return String(a.property_id || '').localeCompare(String(b.property_id || ''));
  });
}

function applyCityFilter(rows) {
  const normalizedFilter = String(activeCityFilter || 'all').trim().toLowerCase();
  if (normalizedFilter === 'all') return rows;
  return rows.filter((row) => String(row?.city || '').trim().toLowerCase() === normalizedFilter);
}

function updateFinancingSummary() {
  const loan = financingConfig[activeMortgageMode] || financingConfig.second_home;
  document.getElementById('active-rate').textContent = loan.labelRate;
  document.getElementById('active-down').textContent = loan.labelDown;
  document.getElementById('active-heloc').textContent = helocEnabled ? 'On' : 'Off';
}

function renderSortIndicators() {
  document.querySelectorAll('.listings-table thead th[data-sort-key]').forEach((th) => {
    const key = th.getAttribute('data-sort-key');
    const baseLabel = th.textContent.replace(/\\s+[↑↓]$/, '');
    th.textContent = baseLabel;
    if (key === activeSortKey) {
      th.textContent = `${baseLabel} ${activeSortDirection === 'asc' ? '↑' : '↓'}`;
    }
  });
}

function renderPriorityRanking() {
  const container = document.getElementById('ranking-list');
  const empty = document.getElementById('priority-empty');
  const count = document.getElementById('table-count');
  const indicator = document.getElementById('page-indicator');
  const prev = document.getElementById('page-prev');
  const next = document.getElementById('page-next');
  container.innerHTML = '';

  filteredRows = applyCityFilter(scenarioRows);
  sortedRows = sortRows(filteredRows);

  if (!sortedRows.length) {
    empty.style.display = 'block';
    empty.textContent = 'No STR-fit listings in the current dataset.';
    count.textContent = '0 listings';
    indicator.textContent = 'Page 0 / 0';
    prev.disabled = true;
    next.disabled = true;
    return;
  }

  empty.style.display = 'none';
  const totalPages = Math.max(1, Math.ceil(sortedRows.length / rowsPerPage));
  if (currentPage > totalPages) currentPage = totalPages;
  const start = (currentPage - 1) * rowsPerPage;
  const pageRows = sortedRows.slice(start, start + rowsPerPage);

  pageRows.forEach((p, idx) => {
    const state = getConstraintState(p);
    const isPs = isPalmSpringsRow(p);
    const tr = document.createElement('tr');
    const rank = start + idx + 1;
    const addressCell = p.property_url
      ? `<a class="link" href="${p.property_url}">${p.address || 'n/a'}</a>`
      : (p.address || 'n/a');
    const constraintCell = isPs
      ? `<button type="button" class="constraint-toggle-btn" data-property-id="${p.property_id}" data-action="toggle">${state.open ? 'Hide Constraints' : 'Show Constraints'}</button>`
      : '<span class="constraint-note"></span>';
    tr.innerHTML = `
      <td class="num">${rank}</td>
      <td>${p.property_id || 'n/a'}</td>
      <td class="col-address">${addressCell}</td>
      <td>${p.city || 'n/a'}</td>
      <td>${p.zip_code || 'n/a'}</td>
      <td class="num">${currency.format(Number(p.list_price || 0))}</td>
      <td class="num">${formatInt(p.sqft)}</td>
      <td class="num">${currency.format(Number(p.price_per_sqft || 0))}</td>
      <td class="num">${Number(p.beds || 0).toFixed(0)}</td>
      <td class="num">${Number(p.full_baths || 0).toFixed(1)}</td>
      <td class="num">${pct(p.coc_pre_tax)}</td>
      <td class="num">${pct(p.coc_post_tax)}</td>
      <td class="num">${currency.format(Number(p.annual_cash_flow_med || 0))}</td>
      <td class="num">${currency.format(Number(p.adr_final || p.adr_med || 0))} ${sourceBadge(p.adr_source)}</td>
      <td class="num">${pct(p.occupancy_final || p.occ_med)} ${sourceBadge(p.occupancy_source)}</td>
      <td class="num">${currency.format(Number(p.total_cash_cost_to_buy || 0))}</td>
      <td class="num">${currency.format(Number(p.monthly_debt_payment || 0))}</td>
      <td class="num">${Number(p.str_fit_score || 0).toFixed(0)}</td>
      <td>${constraintCell}</td>
    `;
    container.appendChild(tr);

    if (isPs && state.open) {
      const detailTr = document.createElement('tr');
      detailTr.innerHTML = `<td colspan="19">${renderConstraintDetail(p, state)}</td>`;
      container.appendChild(detailTr);
    }
  });

  count.textContent = `${sortedRows.length.toLocaleString()} listings`;
  indicator.textContent = `Page ${currentPage} / ${totalPages}`;
  prev.disabled = currentPage <= 1;
  next.disabled = currentPage >= totalPages;
}

function getConstraintState(row) {
  const propertyId = String(row.property_id || '');
  if (!rowConstraintState[propertyId]) {
    const contractPolicy = payload.contract_policy || {};
    rowConstraintState[propertyId] = {
      open: false,
      tier: toTierView(row.scenario_tier),
      adr: Number(row.adr_med || 0),
      avgStay: Number(contractPolicy.avg_stay_nights_per_booking || 4),
    };
  }
  return rowConstraintState[propertyId];
}

function renderConstraintDetail(row, state) {
  const scenario = constraintScenarioForRow(row, state);
  if (!scenario) return '';
  const contractPolicy = payload.contract_policy || {};
  const mtrPolicy = payload.mtr || {};
  const preDelta = scenario.preTaxCoc - scenario.baselinePreTaxCoc;
  const postDelta = scenario.postTaxCoc - scenario.baselinePostTaxCoc;
  const cashDelta = scenario.annualCashFlow - scenario.baselineAnnualCashFlow;
  const propertyId = String(row.property_id || '');
  return `
    <div class="constraint-panel">
      <div class="constraint-grid">
        <div class="constraint-group">
          <h4>Palm Springs Constraint Inputs (Listing-Level)</h4>
          <div class="constraint-field">
            <label>Tier</label>
            <div class="constraint-tier-toggle">
              <button type="button" class="constraint-tier-btn ${state.tier === 'average' ? 'active' : ''}" data-property-id="${propertyId}" data-tier="average">Average</button>
              <button type="button" class="constraint-tier-btn ${state.tier === 'luxury' ? 'active' : ''}" data-property-id="${propertyId}" data-tier="luxury">Luxury</button>
            </div>
          </div>
          <div class="constraint-field">
            <label for="constraint-adr-${propertyId}">ADR ($)</label>
            <input id="constraint-adr-${propertyId}" type="number" min="0" step="5" value="${Math.round(state.adr)}" data-property-id="${propertyId}" data-field="adr" />
          </div>
          <div class="constraint-field">
            <label for="constraint-stay-${propertyId}">Avg Stay (nights)</label>
            <input id="constraint-stay-${propertyId}" type="number" min="1" max="30" step="0.5" value="${Number(state.avgStay).toFixed(1)}" data-property-id="${propertyId}" data-field="avg_stay" />
          </div>
          <p class="finance-hint">Max STR contracts/year: <strong>${Number(contractPolicy.max_str_bookings_per_year || 26)}</strong></p>
          <p class="finance-hint">MTR ADR multiplier: <strong>${Number(mtrPolicy.mtr_adr_multiplier || 0.55).toFixed(2)}x</strong></p>
          <p class="finance-hint">MTR occupancy: <strong>${asPct(Number(mtrPolicy.mtr_occupancy || 0.72))}</strong></p>
        </div>
        <div class="constraint-group">
          <h4>Constraint Math</h4>
          <p class="constraint-formula"><span>Tier</span><strong>${String(row.tier_final || row.scenario_tier || 'n/a')} (${String(row.tier_source || 'auto').toUpperCase()})</strong></p>
          <p class="constraint-formula"><span>ADR / OCC Baseline</span><strong>${currency.format(Number(row.adr_final || row.adr_med || 0))} / ${asPct(Number(row.occupancy_final || row.occ_med || 0))}</strong></p>
          <p class="constraint-formula"><span>Override Note</span><strong>${String(row.override_note || '').trim() || 'n/a'}</strong></p>
          <p class="constraint-formula"><span>STR nights = min(365, 26 × avg_stay)</span><strong>${Math.round(scenario.strNights)} nights</strong></p>
          <p class="constraint-formula"><span>MTR nights = 365 - STR nights</span><strong>${Math.round(scenario.mtrNights)} nights</strong></p>
          <p class="constraint-formula"><span>STR/MTR split</span><strong>${asPct(scenario.strShare)} / ${asPct(scenario.mtrShare)}</strong></p>
          <p class="constraint-formula"><span>Blended revenue</span><strong>${currency.format(scenario.blendedRevenue)}</strong></p>
          <p>
            <span class="constraint-badge">26-cap</span>
            <span class="constraint-badge">STR ${Math.round(scenario.strNights)}n</span>
            <span class="constraint-badge">MTR ${Math.round(scenario.mtrNights)}n</span>
            <span class="constraint-badge">${(scenario.strShare * 100).toFixed(0)}/${(scenario.mtrShare * 100).toFixed(0)} split</span>
          </p>
        </div>
      </div>
      <div class="constraint-group" style="margin-top: 12px;">
        <h4>Impact vs Baseline</h4>
        <div class="constraint-delta-grid">
          <article class="constraint-delta">
            <p class="k">Pre-Tax CoC</p>
            <p class="v">${pct(scenario.preTaxCoc)}</p>
            <p class="d">${preDelta >= 0 ? '+' : ''}${(preDelta * 100).toFixed(2)} pts</p>
          </article>
          <article class="constraint-delta">
            <p class="k">Post-Tax CoC</p>
            <p class="v">${pct(scenario.postTaxCoc)}</p>
            <p class="d">${postDelta >= 0 ? '+' : ''}${(postDelta * 100).toFixed(2)} pts</p>
          </article>
          <article class="constraint-delta">
            <p class="k">Annual Cash Flow</p>
            <p class="v">${currency.format(scenario.annualCashFlow)}</p>
            <p class="d">${cashDelta >= 0 ? '+' : '-'}${currency.format(Math.abs(cashDelta))}</p>
          </article>
        </div>
      </div>
    </div>
  `;
}

function init() {
  document.getElementById('total-ingested').textContent = String(payload.total_ingested || 0);
  document.getElementById('full-scrape-at').textContent = formatFullScrapeTimestamp(payload.full_scrape_completed_at);
  document.getElementById('total-fit').textContent = String(payload.total_str_fit_passed || 0);
  document.getElementById('new-listings-today').textContent = String(payload.new_listings_today || 0);
  document.getElementById('listing-update-detail').textContent = formatListingUpdateDetail(
    payload.fetched_rows_today,
    payload.new_listings_today,
  );
  document.getElementById('listings-pulled-at').textContent = formatPullTimestamp(payload.listings_pulled_at);
  document.getElementById('priority-note').textContent = 'STR-fit listings sorted by post-tax COC (desc), then STR fit score.';

  document.getElementById('mortgage-second-home').addEventListener('change', () => {
    activeMortgageMode = 'second_home';
    currentPage = 1;
    computeScenarioRows();
    updateFinancingSummary();
    renderPriorityRanking();
  });
  document.getElementById('mortgage-investment').addEventListener('change', () => {
    activeMortgageMode = 'investment_home';
    currentPage = 1;
    computeScenarioRows();
    updateFinancingSummary();
    renderPriorityRanking();
  });
  document.getElementById('heloc-enabled').addEventListener('change', (event) => {
    helocEnabled = Boolean(event.target.checked);
    currentPage = 1;
    computeScenarioRows();
    updateFinancingSummary();
    renderPriorityRanking();
  });

  document.getElementById('rows-per-page').addEventListener('change', (event) => {
    rowsPerPage = Number(event.target.value || 50);
    currentPage = 1;
    renderPriorityRanking();
  });
  document.getElementById('city-filter').addEventListener('change', (event) => {
    activeCityFilter = String(event.target.value || 'all').trim().toLowerCase();
    currentPage = 1;
    renderPriorityRanking();
  });
  document.getElementById('page-prev').addEventListener('click', () => {
    if (currentPage > 1) {
      currentPage -= 1;
      renderPriorityRanking();
    }
  });
  document.getElementById('page-next').addEventListener('click', () => {
    currentPage += 1;
    renderPriorityRanking();
  });
  document.querySelectorAll('.listings-table thead th[data-sort-key]').forEach((th) => {
    th.style.cursor = 'pointer';
    th.addEventListener('click', () => {
      const clickedKey = th.getAttribute('data-sort-key') || '';
      if (!clickedKey) return;
      if (activeSortKey === clickedKey) {
        activeSortDirection = activeSortDirection === 'asc' ? 'desc' : 'asc';
      } else {
        activeSortKey = clickedKey;
        activeSortDirection = 'asc';
      }
      currentPage = 1;
      renderSortIndicators();
      renderPriorityRanking();
    });
  });
  document.getElementById('ranking-list').addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const propertyId = String(target.dataset.propertyId || '');
    if (!propertyId) return;
    if (target.dataset.action === 'toggle') {
      const row = scenarioRows.find((item) => String(item.property_id || '') === propertyId);
      if (!row || !isPalmSpringsRow(row)) return;
      const state = getConstraintState(row);
      state.open = !state.open;
      renderPriorityRanking();
      return;
    }
    if (target.classList.contains('constraint-tier-btn')) {
      const row = scenarioRows.find((item) => String(item.property_id || '') === propertyId);
      if (!row) return;
      const state = getConstraintState(row);
      const tier = String(target.dataset.tier || 'average');
      state.tier = tier === 'luxury' ? 'luxury' : 'average';
      renderPriorityRanking();
    }
  });
  document.getElementById('ranking-list').addEventListener('input', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    if (!(target instanceof HTMLInputElement)) return;
    const propertyId = String(target.dataset.propertyId || '');
    if (!propertyId) return;
    const row = scenarioRows.find((item) => String(item.property_id || '') === propertyId);
    if (!row) return;
    const state = getConstraintState(row);
    if (target.dataset.field === 'adr') {
      state.adr = Math.max(0, Number(target.value || 0));
      renderPriorityRanking();
      return;
    }
    if (target.dataset.field === 'avg_stay') {
      state.avgStay = Math.max(1, Number(target.value || 1));
      renderPriorityRanking();
    }
  });
  renderSortIndicators();
  computeScenarioRows();
  const cityFilter = document.getElementById('city-filter');
  const uniqueCities = Array.from(
    new Set(
      scenarioRows
        .map((row) => String(row.city || '').trim())
        .filter((city) => city.length > 0)
    )
  ).sort((a, b) => a.localeCompare(b));
  uniqueCities.forEach((city) => {
    const option = document.createElement('option');
    option.value = city.toLowerCase();
    option.textContent = city;
    cityFilter.appendChild(option);
  });
  activeCityFilter = String(cityFilter.value || 'all').trim().toLowerCase();

  updateFinancingSummary();

  const snapshot = document.getElementById('filter-snapshot');
  const kpiFilterList = document.getElementById('str-filter-kpi-list');
  snapshot.innerHTML = '';
  kpiFilterList.innerHTML = '';
  (payload.str_filter_snapshot || []).forEach((line) => {
    const item = document.createElement('li');
    item.textContent = line;
    snapshot.appendChild(item);
    const kpiItem = document.createElement('li');
    kpiItem.textContent = line;
    kpiFilterList.appendChild(kpiItem);
  });

  renderPriorityRanking();
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
    coc_assumptions = _load_coc_assumptions(args.assumptions_input)
    full_scrape_completed_at: str | None = None
    input_path = Path(args.input)
    if input_path.exists():
        full_scrape_completed_at = datetime.fromtimestamp(input_path.stat().st_mtime).astimezone().isoformat()
    payload = build_dashboard_payload(
        scored_df,
        top_n=args.top_n,
        homes_limit=args.homes_limit,
        health_report=health_report,
        full_scrape_completed_at=full_scrape_completed_at,
        coc_assumptions=coc_assumptions,
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

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_INPUT_PATH = Path("examples/zips/coc_scorecard.xlsx")
DEFAULT_OUTPUT_PATH = Path("examples/zips/coc_dashboard.html")
BUDGET_LUXURY_MAX_PRICE = 1_500_000.0
BUDGET_LUXURY_TOP_N = 30


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build static COC dashboard HTML from scorecard workbook")
    parser.add_argument("--input", default=str(DEFAULT_INPUT_PATH), help="Input COC scorecard workbook path")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="Output dashboard HTML path")
    parser.add_argument("--top-n", type=int, default=10, help="Top N rows to display in COC table")
    parser.add_argument("--homes-limit", type=int, default=100, help="Max homes loaded in interactive breakdown")
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


def _ai_insights(row: pd.Series) -> dict[str, str]:
    coc_med = _safe_float(row.get("coc_post_tax"), _safe_float(row.get("coc_med")))
    coc_low = _safe_float(row.get("coc_low"))
    annual_cash_flow_med = _safe_float(row.get("annual_cash_flow_med"))
    list_price = _safe_float(row.get("list_price"))
    total_cash_cost_to_buy = _safe_float(row.get("total_cash_cost_to_buy"))
    str_fit_score = _safe_float(row.get("str_fit_score"))
    occ_low = _safe_float(row.get("occupancy_low"))
    occ_high = _safe_float(row.get("occupancy_high"))
    adr_med = _safe_float(row.get("adr_med"))
    fail_reasons = _safe_str(row.get("str_fit_reasons_fail")).lower()

    if coc_med >= 0.12:
        potential = "Potential: Strong projected COC return with attractive STR upside."
    elif coc_med >= 0.06:
        potential = "Potential: Solid projected COC return with healthy yield profile."
    elif coc_med > 0:
        potential = "Potential: Positive projected COC return with moderate upside."
    else:
        potential = "Potential: Limited return profile; upside depends on operational improvements."

    if annual_cash_flow_med > 15000:
        potential = f"{potential[:-1]} Cash flow outlook is robust."
    elif annual_cash_flow_med > 0:
        potential = f"{potential[:-1]} Cash flow outlook is positive."

    if occ_low >= 0.5 and occ_high >= 0.65:
        potential = f"{potential[:-1]} Occupancy range suggests resilient demand."

    if str_fit_score >= 85:
        potential = f"{potential[:-1]} STR-fit score supports investment confidence."

    risk = "Risk: "
    risk_parts: list[str] = []
    if coc_low < 0:
        risk_parts.append("downside scenario can turn cash flow negative")
    if annual_cash_flow_med <= 0:
        risk_parts.append("base-case annual cash flow is negative")
    elif annual_cash_flow_med < 6000:
        risk_parts.append("base-case cash flow is thin")
    if total_cash_cost_to_buy >= 250000:
        risk_parts.append("high upfront capital requirement")
    if list_price >= 1200000:
        risk_parts.append("premium pricing increases acquisition risk")
    if "private pool unknown" in fail_reasons:
        risk_parts.append("pool data is incomplete and may affect STR appeal")
    if adr_med > 0 and occ_low < 0.45:
        risk_parts.append("lower occupancy downside could pressure ADR assumptions")

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

    coc_post = pd.to_numeric(candidates.get("coc_post_tax"), errors="coerce")
    coc_pre = pd.to_numeric(candidates.get("coc_pre_tax"), errors="coerce")
    candidates["_priority_score_num"] = pd.to_numeric(candidates.get("priority_score"), errors="coerce").fillna(0.0)
    candidates["_priority_coc_tie"] = coc_post.fillna(coc_pre).fillna(0.0)
    candidates["_priority_rank_num"] = pd.to_numeric(candidates.get("priority_rank"), errors="coerce")
    candidates = candidates.sort_values(
        by=["_priority_rank_num", "_priority_score_num", "_priority_coc_tie", "property_id"],
        ascending=[True, False, False, True],
        kind="mergesort",
    )

    rows = _top_rows(candidates, top_n)
    for i, row_idx in enumerate(candidates.head(top_n).index):
        rows[i]["priority_score"] = _safe_float(candidates.loc[row_idx, "_priority_score_num"])
        rows[i]["priority_rank"] = int(_safe_float(candidates.loc[row_idx, "_priority_rank_num"], float(i + 1)))
        rows[i]["priority_reason_summary"] = _safe_str(
            candidates.loc[row_idx, "priority_reason_summary"], "Balanced STR value profile."
        )
    return rows


def build_dashboard_payload(scored_df: pd.DataFrame, *, top_n: int = 10, homes_limit: int = 100) -> dict[str, Any]:
    scored = scored_df.copy()
    if "status" in scored.columns:
        scored = scored[scored["status"].astype(str).str.upper() == "FOR_SALE"].copy()

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

    return {
        "total_ingested": int(len(scored)),
        "total_str_fit_passed": int(len(fit)),
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
            "Palm Springs for-sale STR-pass listings ranked by hybrid value score: lower price/sqft, "
            "larger lot utility, and stronger under-cap neighborhood support; tie-break by post-tax COC."
        ),
        "homes": homes_fit,
        "total_houses_on_sale": int(len(scored)),
        "str_filter_snapshot": [
            "Quality checks required",
            "STR-supported neighborhood required",
            "Beds/Baths minimum: 2+/2+",
            "List price range: $100,000 to $3,000,000",
            "Preferred cities: Palm Springs, Indio, Bermuda Dunes",
            "ZIP must be in under-cap STR geography",
        ],
    }


def render_dashboard_html(payload: dict[str, Any]) -> str:
    data_json = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>COC Dashboard</title>
  <style>
    :root {{
      --bg: #f5f7fb;
      --card: #ffffff;
      --ink: #0f172a;
      --muted: #64748b;
      --line: #e2e8f0;
      --accent: #14532d;
      --accent2: #1d4ed8;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: "Avenir Next", "Segoe UI", Arial, sans-serif; background: var(--bg); color: var(--ink); }}
    .wrap {{ max-width: 1200px; margin: 32px auto; padding: 0 20px; }}
    .grid {{ display: grid; grid-template-columns: repeat(12, 1fr); gap: 16px; }}
    .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 18px; }}
    .hero {{ grid-column: span 4; }}
    .hero h2 {{ margin: 0 0 8px; font-size: 14px; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: .06em; }}
    .hero .big {{ font-size: 42px; font-weight: 800; color: var(--accent); line-height: 1; }}
    .assumptions-card {{ grid-column: span 12; }}
    .tablecard-main {{ grid-column: span 12; }}
    .tablecard-lux {{ grid-column: span 12; }}
    .title {{ margin: 0 0 14px; font-size: 20px; font-weight: 700; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 10px 8px; text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-weight: 700; }}
    a.link {{ color: #1d4ed8; text-decoration: none; font-weight: 600; }}
    a.link:hover {{ text-decoration: underline; }}
    .snapshot {{ color: var(--muted); font-size: 13px; line-height: 1.5; }}
    .snapshot ul {{ margin: 8px 0 0; padding-left: 18px; }}
    .insight {{ font-size: 12px; color: #334155; line-height: 1.4; }}
    .breakdown {{ grid-column: span 12; }}
    .controls {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    label {{ display: block; font-size: 13px; color: var(--muted); margin-bottom: 6px; }}
    select, input[type=range] {{ width: 100%; }}
    .marks {{ display: flex; justify-content: space-between; color: var(--muted); font-size: 12px; margin-top: 4px; }}
    .metrics {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 16px; }}
    .metric {{ border: 1px solid var(--line); border-radius: 10px; padding: 12px; background: #fafcff; }}
    .metric .k {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }}
    .metric .v {{ font-size: 22px; font-weight: 700; margin-top: 4px; }}
    .sub {{ margin-top: 10px; color: var(--muted); font-size: 13px; }}
    .tag {{ display: inline-block; padding: 2px 8px; border-radius: 999px; background: #eef2ff; color: var(--accent2); font-size: 12px; font-weight: 600; }}
    .reasonbox {{ border: 1px solid var(--line); border-radius: 10px; padding: 10px; margin-top: 10px; font-size: 12px; color: var(--muted); background: #fcfdff; }}
    @media (max-width: 900px) {{
      .hero {{ grid-column: span 6; }}
      .tablecard-main, .tablecard-lux, .breakdown {{ grid-column: span 12; }}
      .metrics {{ grid-template-columns: repeat(2, 1fr); }}
      .controls {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"grid\">
      <div class=\"card hero\">
        <h2>Total Ingested</h2>
        <div id=\"total-ingested\" class=\"big\">0</div>
        <div class=\"sub\">All scored for-sale rows.</div>
      </div>
      <div class=\"card hero\">
        <h2>STR Fit Passed</h2>
        <div id=\"total-fit\" class=\"big\">0</div>
        <div class=\"sub\">Rows meeting STR suitability rules.</div>
      </div>
      <div class=\"card assumptions-card\">
        <div class=\"snapshot\">
          <strong>STR Filter Snapshot</strong>
          <ul id=\"filter-snapshot\"></ul>
        </div>
      </div>
      <div class=\"card tablecard-main\">
        <h3 class=\"title\">Palm Springs Priority List</h3>
        <div class=\"sub\" id=\"priority-note\"></div>
        <div class=\"sub\">Candidates: <strong id=\"priority-candidates\"></strong> | Palm Springs STR-Pass: <strong id=\"priority-strict-pass\"></strong> | Top Score: <strong id=\"priority-top-score\"></strong></div>
        <table>
          <thead>
            <tr><th>Rank</th><th>Property ID</th><th>Address</th><th>Priority Score</th><th>List Price</th><th>Price / Sq Ft</th><th>Lot Size</th><th>Post-Tax COC</th><th>Reason</th></tr>
          </thead>
          <tbody id=\"priority-body\"></tbody>
        </table>
        <div id=\"priority-empty\" class=\"sub\" style=\"display:none;\"></div>
      </div>
      <div class=\"card tablecard-lux\">
        <h3 class=\"title\">Pool Verification Watchlist</h3>
        <div class=\"sub\" id=\"pool-watchlist-note\"></div>
        <table>
          <thead>
            <tr><th>Property ID</th><th>Address</th><th>List Price</th><th>Sq Ft</th><th>Lot Size</th><th>Price / Sq Ft</th><th>Confidence</th><th>Signal Sources</th><th>Enrichment Result</th><th>Evidence</th></tr>
          </thead>
          <tbody id=\"pool-watchlist-body\"></tbody>
        </table>
        <div id=\"pool-watchlist-empty\" class=\"sub\" style=\"display:none;\"></div>
      </div>
      <div class=\"card tablecard-lux\">
        <h3 class=\"title\">Luxury STR Value Under $1.5M</h3>
        <div class=\"sub\" id=\"luxury-value-note\"></div>
        <h4 class=\"sub\">STR Potential</h4>
        <table>
          <thead>
            <tr><th>Property ID</th><th>Address</th><th>List Price</th><th>Sq Ft</th><th>Price / Sq Ft</th><th>Lot Size</th><th>Bedrooms</th><th>Bathrooms</th><th>Assumed ADR Rate</th><th>AI Insights</th></tr>
          </thead>
          <tbody id=\"luxury-value-potential-body\"></tbody>
        </table>
        <h4 class=\"sub\">Investment Metrics</h4>
        <table>
          <thead>
            <tr><th>Pre-Tax COC</th><th>Post-Tax COC</th><th>Monthly Payment</th><th>Cash Needed</th><th>Annual Cash Flow (Med)</th><th>DSCR</th></tr>
          </thead>
          <tbody id=\"luxury-value-investment-body\"></tbody>
        </table>
        <div id=\"luxury-value-empty\" class=\"sub\" style=\"display:none;\"></div>
      </div>
      <div class=\"card tablecard-lux\">
        <h3 class=\"title\">Luxury STR Opportunities</h3>
        <div class=\"sub\" id=\"luxury-note\"></div>
        <h4 class=\"sub\">STR Potential</h4>
        <table>
          <thead>
            <tr><th>Property ID</th><th>Address</th><th>List Price</th><th>Sq Ft</th><th>Price / Sq Ft</th><th>Lot Size</th><th>Bedrooms</th><th>Bathrooms</th><th>Assumed ADR Rate</th><th>AI Insights</th></tr>
          </thead>
          <tbody id=\"luxury5-potential-body\"></tbody>
        </table>
        <h4 class=\"sub\">Investment Metrics</h4>
        <table>
          <thead>
            <tr><th>Pre-Tax COC</th><th>Post-Tax COC</th><th>Monthly Payment</th><th>Cash Needed</th><th>Annual Cash Flow (Med)</th><th>DSCR</th></tr>
          </thead>
          <tbody id=\"luxury5-investment-body\"></tbody>
        </table>
        <div id=\"luxury-empty\" class=\"sub\" style=\"display:none;\"></div>
      </div>
      <div class=\"card tablecard-main\">
        <h3 class=\"title\">Top STR-Passing Properties by COC Return</h3>
        <h4 class=\"sub\">STR Potential</h4>
        <table>
          <thead>
            <tr><th>Property ID</th><th>Address</th><th>List Price</th><th>Sq Ft</th><th>Price / Sq Ft</th><th>Lot Size</th><th>Bedrooms</th><th>Bathrooms</th><th>Assumed ADR Rate</th><th>AI Insights</th></tr>
          </thead>
          <tbody id=\"top5-potential-body\"></tbody>
        </table>
        <h4 class=\"sub\">Investment Metrics</h4>
        <table>
          <thead>
            <tr><th>Pre-Tax COC</th><th>Post-Tax COC</th><th>Monthly Payment</th><th>Cash Needed</th><th>Annual Cash Flow (Med)</th><th>DSCR</th></tr>
          </thead>
          <tbody id=\"top5-investment-body\"></tbody>
        </table>
      </div>
      <div class=\"card breakdown\">
        <h3 class=\"title\">Home Breakdown with ADR + Occupancy Sliders (Low / Base / High)</h3>
        <div class=\"controls\">
          <div>
            <label for=\"home-select\">Property</label>
            <select id=\"home-select\"></select>
          </div>
          <div>
            <label>Scenario Tier</label>
            <div id=\"tier-badge\" class=\"tag\"></div>
          </div>
          <div>
            <label for=\"adr-slider\">ADR: <span id=\"adr-val\"></span></label>
            <input id=\"adr-slider\" type=\"range\" min=\"0\" max=\"1\" step=\"1\" />
            <div class=\"marks\"><span id=\"adr-low\"></span><span id=\"adr-med\"></span><span id=\"adr-high\"></span></div>
          </div>
          <div>
            <label for=\"occ-slider\">Occupancy: <span id=\"occ-val\"></span></label>
            <input id=\"occ-slider\" type=\"range\" min=\"0\" max=\"1\" step=\"0.01\" />
            <div class=\"marks\"><span id=\"occ-low\"></span><span id=\"occ-med\"></span><span id=\"occ-high\"></span></div>
          </div>
        </div>
        <div class=\"metrics\">
          <div class=\"metric\"><div class=\"k\">Monthly Payment</div><div id=\"m-monthly\" class=\"v\"></div></div>
          <div class=\"metric\"><div class=\"k\">Total Cash Cost</div><div id=\"m-cash\" class=\"v\"></div></div>
          <div class=\"metric\"><div class=\"k\">Annual Cash Flow</div><div id=\"m-cashflow\" class=\"v\"></div></div>
          <div class=\"metric\"><div class=\"k\">COC Return</div><div id=\"m-coc\" class=\"v\"></div></div>
        </div>
        <div class=\"reasonbox\">
          <div><strong>STR Fit:</strong> <span id=\"fit-status\"></span> | Score: <span id=\"fit-score\"></span></div>
          <div><strong>Pass Reasons:</strong> <span id=\"fit-pass\"></span></div>
          <div><strong>Fail Reasons:</strong> <span id=\"fit-fail\"></span></div>
        </div>
      </div>
    </div>
  </div>
<script>
const payload = {data_json};
const currency = new Intl.NumberFormat('en-US', {{ style: 'currency', currency: 'USD', maximumFractionDigits: 0 }});
const pct = (v) => `${{(v*100).toFixed(2)}}%`;

function renderTopFive() {{
  const potentialBody = document.getElementById('top5-potential-body');
  const investmentBody = document.getElementById('top5-investment-body');
  potentialBody.innerHTML = '';
  investmentBody.innerHTML = '';
  (payload.top_properties || []).forEach((p) => {{
    const listing = p.property_url
      ? `<a class="link" href="${{p.property_url}}" target="_blank" rel="noopener noreferrer">View Listing</a>`
      : `<span style="color:#94a3b8">No link</span>`;
    const potentialRow = document.createElement('tr');
    potentialRow.innerHTML = `<td><strong>${{p.property_id}}</strong></td>
      <td><span style="color:#334155">${{p.address}}</span><br>${{listing}}</td>
      <td>${{currency.format(p.list_price)}}</td>
      <td>${{Number(p.sqft || 0).toLocaleString()}}</td>
      <td>${{currency.format(p.price_per_sqft || 0)}}</td>
      <td>${{Number(p.lot_sqft || 0).toLocaleString()}}</td>
      <td>${{Number(p.beds || 0).toFixed(0)}}</td>
      <td>${{Number(p.full_baths || 0).toFixed(1)}}</td>
      <td>${{currency.format(p.adr_med || 0)}}</td>
      <td class="insight"><div>${{p.ai_insight_potential || 'Potential: n/a'}}</div><div>${{p.ai_insight_risk || 'Risk: n/a'}}</div></td>`;
    potentialBody.appendChild(potentialRow);

    const investmentRow = document.createElement('tr');
    const dscr = p.dscr == null ? 'N/A' : Number(p.dscr).toFixed(2);
    investmentRow.innerHTML = `<td>${{pct(p.coc_pre_tax)}}</td>
      <td>${{pct(p.coc_post_tax)}}</td>
      <td>${{currency.format(p.monthly_debt_payment || 0)}}</td>
      <td>${{currency.format(p.total_cash_cost_to_buy || 0)}}</td>
      <td>${{currency.format(p.annual_cash_flow_med)}}</td>
      <td>${{dscr}}</td>`;
    investmentBody.appendChild(investmentRow);
  }});
}}

function renderPalmSpringsPriority() {{
  const body = document.getElementById('priority-body');
  const empty = document.getElementById('priority-empty');
  body.innerHTML = '';
  const rows = payload.top_properties_palm_springs_priority || [];
  if (!rows.length) {{
    empty.style.display = 'block';
    empty.textContent = 'No Palm Springs priority candidates in current dataset.';
    return;
  }}
  empty.style.display = 'none';
  rows.forEach((p) => {{
    const listing = p.property_url
      ? `<a class="link" href="${{p.property_url}}" target="_blank" rel="noopener noreferrer">View Listing</a>`
      : `<span style="color:#94a3b8">No link</span>`;
    const row = document.createElement('tr');
    row.innerHTML = `<td>${{Number(p.priority_rank || 0).toFixed(0)}}</td>
      <td><strong>${{p.property_id}}</strong></td>
      <td><span style="color:#334155">${{p.address}}</span><br>${{listing}}</td>
      <td>${{(Number(p.priority_score || 0) * 100).toFixed(1)}}</td>
      <td>${{currency.format(p.list_price)}}</td>
      <td>${{currency.format(p.price_per_sqft || 0)}}</td>
      <td>${{Number(p.lot_sqft || 0).toLocaleString()}}</td>
      <td>${{pct(p.coc_post_tax)}}</td>
      <td class="insight">${{p.priority_reason_summary || 'Balanced STR value profile.'}}</td>`;
    body.appendChild(row);
  }});
}}

function renderPoolWatchlist() {{
  const body = document.getElementById('pool-watchlist-body');
  const empty = document.getElementById('pool-watchlist-empty');
  body.innerHTML = '';
  const rows = payload.pool_verification_watchlist || [];
  if (!rows.length) {{
    empty.style.display = 'block';
    empty.textContent = 'No unresolved pool-verification candidates in current dataset.';
    return;
  }}
  empty.style.display = 'none';
  rows.forEach((p) => {{
    const listing = p.property_url
      ? `<a class="link" href="${{p.property_url}}" target="_blank" rel="noopener noreferrer">View Listing</a>`
      : `<span style="color:#94a3b8">No link</span>`;
    const row = document.createElement('tr');
    row.innerHTML = `<td><strong>${{p.property_id}}</strong></td>
      <td><span style="color:#334155">${{p.address}}</span><br>${{listing}}</td>
      <td>${{currency.format(p.list_price)}}</td>
      <td>${{Number(p.sqft || 0).toLocaleString()}}</td>
      <td>${{Number(p.lot_sqft || 0).toLocaleString()}}</td>
      <td>${{currency.format(p.price_per_sqft || 0)}}</td>
      <td>${{p.pool_signal_confidence || 'unknown'}}</td>
      <td>${{p.pool_signal_sources || 'none'}}</td>
      <td>${{p.pool_enrichment_result || 'queued'}}</td>
      <td class="insight">${{p.pool_evidence || 'n/a'}}</td>`;
    body.appendChild(row);
  }});
}}

function renderLuxuryValueBudget() {{
  const potentialBody = document.getElementById('luxury-value-potential-body');
  const investmentBody = document.getElementById('luxury-value-investment-body');
  const empty = document.getElementById('luxury-value-empty');
  potentialBody.innerHTML = '';
  investmentBody.innerHTML = '';

  const rows = payload.top_properties_luxury_value_budget || [];
  if (!rows.length) {{
    empty.style.display = 'block';
    empty.textContent = 'No STR-fit luxury-value properties under $1.5M in current dataset.';
    return;
  }}

  empty.style.display = 'none';
  rows.forEach((p) => {{
    const listing = p.property_url
      ? `<a class="link" href="${{p.property_url}}" target="_blank" rel="noopener noreferrer">View Listing</a>`
      : `<span style="color:#94a3b8">No link</span>`;
    const potentialRow = document.createElement('tr');
    potentialRow.innerHTML = `<td><strong>${{p.property_id}}</strong></td>
      <td><span style="color:#334155">${{p.address}}</span><br>${{listing}}</td>
      <td>${{currency.format(p.list_price)}}</td>
      <td>${{Number(p.sqft || 0).toLocaleString()}}</td>
      <td>${{currency.format(p.price_per_sqft || 0)}}</td>
      <td>${{Number(p.lot_sqft || 0).toLocaleString()}}</td>
      <td>${{Number(p.beds || 0).toFixed(0)}}</td>
      <td>${{Number(p.full_baths || 0).toFixed(1)}}</td>
      <td>${{currency.format(p.adr_med || 0)}}</td>
      <td class="insight"><div>${{p.ai_insight_potential || 'Potential: n/a'}}</div><div>${{p.ai_insight_risk || 'Risk: n/a'}}</div></td>`;
    potentialBody.appendChild(potentialRow);

    const investmentRow = document.createElement('tr');
    const dscr = p.dscr == null ? 'N/A' : Number(p.dscr).toFixed(2);
    investmentRow.innerHTML = `<td>${{pct(p.coc_pre_tax)}}</td>
      <td>${{pct(p.coc_post_tax)}}</td>
      <td>${{currency.format(p.monthly_debt_payment || 0)}}</td>
      <td>${{currency.format(p.total_cash_cost_to_buy || 0)}}</td>
      <td>${{currency.format(p.annual_cash_flow_med)}}</td>
      <td>${{dscr}}</td>`;
    investmentBody.appendChild(investmentRow);
  }});
}}

function renderLuxuryFive() {{
  const potentialBody = document.getElementById('luxury5-potential-body');
  const investmentBody = document.getElementById('luxury5-investment-body');
  const empty = document.getElementById('luxury-empty');
  potentialBody.innerHTML = '';
  investmentBody.innerHTML = '';

  const rows = payload.top_properties_luxury || [];
  if (!rows.length) {{
    empty.style.display = 'block';
    empty.textContent = 'No luxury STR-fit properties available in current dataset.';
    return;
  }}

  empty.style.display = 'none';
  rows.forEach((p) => {{
    const listing = p.property_url
      ? `<a class="link" href="${{p.property_url}}" target="_blank" rel="noopener noreferrer">View Listing</a>`
      : `<span style="color:#94a3b8">No link</span>`;
    const potentialRow = document.createElement('tr');
    potentialRow.innerHTML = `<td><strong>${{p.property_id}}</strong></td>
      <td><span style="color:#334155">${{p.address}}</span><br>${{listing}}</td>
      <td>${{currency.format(p.list_price)}}</td>
      <td>${{Number(p.sqft || 0).toLocaleString()}}</td>
      <td>${{currency.format(p.price_per_sqft || 0)}}</td>
      <td>${{Number(p.lot_sqft || 0).toLocaleString()}}</td>
      <td>${{Number(p.beds || 0).toFixed(0)}}</td>
      <td>${{Number(p.full_baths || 0).toFixed(1)}}</td>
      <td>${{currency.format(p.adr_med || 0)}}</td>
      <td class="insight"><div>${{p.ai_insight_potential || 'Potential: n/a'}}</div><div>${{p.ai_insight_risk || 'Risk: n/a'}}</div></td>`;
    potentialBody.appendChild(potentialRow);

    const investmentRow = document.createElement('tr');
    const dscr = p.dscr == null ? 'N/A' : Number(p.dscr).toFixed(2);
    investmentRow.innerHTML = `<td>${{pct(p.coc_pre_tax)}}</td>
      <td>${{pct(p.coc_post_tax)}}</td>
      <td>${{currency.format(p.monthly_debt_payment || 0)}}</td>
      <td>${{currency.format(p.total_cash_cost_to_buy || 0)}}</td>
      <td>${{currency.format(p.annual_cash_flow_med)}}</td>
      <td>${{dscr}}</td>`;
    investmentBody.appendChild(investmentRow);
  }});
}}

function populateHomes() {{
  const select = document.getElementById('home-select');
  select.innerHTML = '';
  (payload.homes || []).forEach((h, idx) => {{
    const opt = document.createElement('option');
    opt.value = String(idx);
    opt.textContent = `${{h.property_id}} - ${{currency.format(h.list_price)}} - ${{h.address}}`;
    select.appendChild(opt);
  }});
}}

function updateForHome(idx) {{
  const rows = payload.homes || [];
  const home = rows[idx] || rows[0];
  if (!home) return;

  document.getElementById('tier-badge').textContent = home.scenario_tier;
  document.getElementById('fit-status').textContent = home.str_fit_pass ? 'Pass' : 'Fail';
  document.getElementById('fit-score').textContent = String(home.str_fit_score || 0);
  document.getElementById('fit-pass').textContent = home.str_fit_reasons_pass || 'n/a';
  document.getElementById('fit-fail').textContent = home.str_fit_reasons_fail || 'n/a';

  const adrSlider = document.getElementById('adr-slider');
  const occSlider = document.getElementById('occ-slider');

  adrSlider.min = String(home.adr_low);
  adrSlider.max = String(home.adr_high);
  adrSlider.step = '1';
  adrSlider.value = String(home.adr_med);

  occSlider.min = String(home.occ_low);
  occSlider.max = String(home.occ_high);
  occSlider.step = '0.01';
  occSlider.value = String(home.occ_med);

  document.getElementById('adr-low').textContent = `Low $${{home.adr_low.toFixed(0)}}`;
  document.getElementById('adr-med').textContent = `Base $${{home.adr_med.toFixed(0)}}`;
  document.getElementById('adr-high').textContent = `High $${{home.adr_high.toFixed(0)}}`;

  document.getElementById('occ-low').textContent = `Low ${{(home.occ_low*100).toFixed(0)}}%`;
  document.getElementById('occ-med').textContent = `Base ${{(home.occ_med*100).toFixed(0)}}%`;
  document.getElementById('occ-high').textContent = `High ${{(home.occ_high*100).toFixed(0)}}%`;

  const recompute = () => {{
    const adr = Number(adrSlider.value);
    const occ = Number(occSlider.value);
    const adrRange = Math.max(1, home.adr_high - home.adr_low);
    const occRange = Math.max(0.0001, home.occ_high - home.occ_low);
    const adrWeight = Math.min(1, Math.max(0, (adr - home.adr_low) / adrRange));
    const occWeight = Math.min(1, Math.max(0, (occ - home.occ_low) / occRange));
    const scenarioMix = (adrWeight + occWeight) / 2;

    const annualCashFlowLow = Number(home.annual_cash_flow_low || 0);
    const annualCashFlowHigh = Number(home.annual_cash_flow_high || home.annual_cash_flow_med || 0);
    const annualCashFlow = annualCashFlowLow + ((annualCashFlowHigh - annualCashFlowLow) * scenarioMix);
    const coc = home.total_cash_cost_to_buy > 0 ? (annualCashFlow / home.total_cash_cost_to_buy) : 0;

    document.getElementById('adr-val').textContent = currency.format(adr);
    document.getElementById('occ-val').textContent = `${{(occ*100).toFixed(1)}}%`;
    document.getElementById('m-monthly').textContent = currency.format(home.monthly_debt_payment);
    document.getElementById('m-cash').textContent = currency.format(home.total_cash_cost_to_buy);
    document.getElementById('m-cashflow').textContent = currency.format(annualCashFlow);
    document.getElementById('m-coc').textContent = pct(coc);
  }};

  adrSlider.oninput = recompute;
  occSlider.oninput = recompute;
  recompute();
}}

function init() {{
  document.getElementById('total-ingested').textContent = String(payload.total_ingested || 0);
  document.getElementById('total-fit').textContent = String(payload.total_str_fit_passed || 0);
  const snapshot = document.getElementById('filter-snapshot');
  (payload.str_filter_snapshot || []).forEach((line) => {{
    const item = document.createElement('li');
    item.textContent = line;
    snapshot.appendChild(item);
  }});

  const select = document.getElementById('home-select');
  select.addEventListener('change', (e) => updateForHome(Number(e.target.value)));

  document.getElementById('luxury-value-note').textContent = payload.luxury_value_note || '';
  document.getElementById('luxury-note').textContent = payload.luxury_widget_note || '';
  document.getElementById('pool-watchlist-note').textContent = payload.pool_watchlist_note || '';
  document.getElementById('priority-note').textContent = payload.priority_ranking_note || '';
  document.getElementById('priority-candidates').textContent = String(payload.total_palm_springs_priority_candidates || 0);
  document.getElementById('priority-strict-pass').textContent = String(payload.total_palm_springs_strict_pass || 0);
  document.getElementById('priority-top-score').textContent = (Number(payload.top_priority_score || 0) * 100).toFixed(1);
  renderPalmSpringsPriority();
  renderPoolWatchlist();
  renderLuxuryValueBudget();
  renderTopFive();
  renderLuxuryFive();
  populateHomes();
  updateForHome(0);
}}

init();
</script>
</body>
</html>
"""


def write_dashboard_html(payload: dict[str, Any], output_path: str | Path) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_dashboard_html(payload), encoding="utf-8")


def main() -> None:
    args = parse_args()
    scored_df = load_scored_data(args.input)
    payload = build_dashboard_payload(scored_df, top_n=args.top_n, homes_limit=args.homes_limit)
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

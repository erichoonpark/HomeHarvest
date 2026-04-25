from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_INPUT_PATH = Path("examples/zips/coc_scorecard.xlsx")
DEFAULT_OUTPUT_PATH = Path("examples/zips/coc_dashboard.html")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build static COC dashboard HTML from scorecard workbook")
    parser.add_argument("--input", default=str(DEFAULT_INPUT_PATH), help="Input COC scorecard workbook path")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="Output dashboard HTML path")
    parser.add_argument("--top-n", type=int, default=5, help="Top N rows to display in COC table")
    parser.add_argument("--homes-limit", type=int, default=100, help="Max homes loaded in interactive breakdown")
    return parser.parse_args()


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
    coc_med = _safe_float(row.get("coc_med"))
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

    if "coc_med" in df.columns:
        df = df.sort_values(by=["coc_med", "property_id"], ascending=[False, True], kind="mergesort")

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
                "list_price": _safe_float(row.get("list_price")),
                "city": _safe_str(row.get("city")),
                "zip_code": _safe_str(row.get("zip_code")),
                "scenario_tier": _safe_str(row.get("scenario_tier")),
                "coc_low": _safe_float(row.get("coc_low")),
                "coc_med": _safe_float(row.get("coc_med")),
                "coc_high": _safe_float(row.get("coc_high")),
                "annual_cash_flow_med": _safe_float(row.get("annual_cash_flow_med")),
                "annual_debt_service": _safe_float(row.get("annual_debt_service")),
                "total_cash_cost_to_buy": _safe_float(row.get("total_cash_cost_to_buy")),
                "str_fit_score": _safe_float(row.get("str_fit_score")),
                "str_fit_pass": _safe_bool(row.get("str_fit_pass")),
                "property_url": _safe_str(row.get("property_url")),
                "ai_insight_potential": insights["potential"],
                "ai_insight_risk": insights["risk"],
            }
        )
    return top_rows


def build_dashboard_payload(scored_df: pd.DataFrame, *, top_n: int = 5, homes_limit: int = 100) -> dict[str, Any]:
    scored = scored_df.copy()
    if "status" in scored.columns:
        scored = scored[scored["status"].astype(str).str.upper() == "FOR_SALE"].copy()

    if "str_fit_pass" not in scored.columns:
        scored["str_fit_pass"] = True

    if "str_fit_score" not in scored.columns:
        scored["str_fit_score"] = 0.0

    fit = scored[scored["str_fit_pass"].fillna(False).astype(bool)].copy()
    fit = fit.sort_values(
        by=["coc_med", "str_fit_score", "property_id"], ascending=[False, False, True], kind="mergesort"
    )
    if "scenario_tier" in fit.columns:
        luxury = fit[fit["scenario_tier"].astype(str) == "palm_springs_luxury"].copy()
    else:
        luxury = fit.iloc[0:0].copy()
    luxury = luxury.sort_values(
        by=["coc_med", "str_fit_score", "property_id"], ascending=[False, False, True], kind="mergesort"
    )

    top_fit = _top_rows(fit, top_n)
    top_luxury = _top_rows(luxury, top_n)
    homes_fit = [_row_to_home_payload(row) for _, row in fit.head(homes_limit).iterrows()]

    return {
        "total_ingested": int(len(scored)),
        "total_str_fit_passed": int(len(fit)),
        "top_properties": top_fit,
        "top_properties_luxury": top_luxury,
        "total_luxury_candidates": int(len(luxury)),
        "luxury_widget_note": (
            "Luxury = scenario_tier = palm_springs_luxury from COC routing assumptions. "
            "Ranked by base COC among luxury-tier STR-fit listings."
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
      <div class=\"card tablecard-lux\">
        <h3 class=\"title\">Luxury STR Opportunities</h3>
        <div class=\"sub\" id=\"luxury-note\"></div>
        <table>
          <thead>
            <tr><th>Property</th><th>City/ZIP</th><th>Scenario Tier</th><th>List Price</th><th>COC (Low/Med/High)</th><th>Annual Cash Flow (Med)</th><th>Annual Debt Service</th><th>Total Cash Cost</th><th>STR Fit Score</th><th>AI Insights</th></tr>
          </thead>
          <tbody id=\"luxury5-body\"></tbody>
        </table>
        <div id=\"luxury-empty\" class=\"sub\" style=\"display:none;\"></div>
      </div>
      <div class=\"card tablecard-main\">
        <h3 class=\"title\">Top 5 STR-Passing Properties by COC Return</h3>
        <table>
          <thead>
            <tr><th>Property</th><th>City/ZIP</th><th>Scenario Tier</th><th>List Price</th><th>COC (Low/Med/High)</th><th>Annual Cash Flow (Med)</th><th>Annual Debt Service</th><th>Total Cash Cost</th><th>STR Fit Score</th><th>AI Insights</th></tr>
          </thead>
          <tbody id=\"top5-body\"></tbody>
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
  const body = document.getElementById('top5-body');
  body.innerHTML = '';
  (payload.top_properties || []).forEach((p) => {{
    const listing = p.property_url
      ? `<a class="link" href="${{p.property_url}}" target="_blank" rel="noopener noreferrer">View Listing</a>`
      : `<span style="color:#94a3b8">No link</span>`;
    const row = document.createElement('tr');
    row.innerHTML = `<td><strong>${{p.property_id}}</strong><br><span style="color:#64748b">${{p.address}}</span><br>${{listing}}</td>
      <td>${{p.city || ''}}${{p.city && p.zip_code ? ', ' : ''}}${{p.zip_code || ''}}</td>
      <td>${{p.scenario_tier || 'n/a'}}</td>
      <td>${{currency.format(p.list_price)}}</td>
      <td>${{pct(p.coc_low || 0)}} / ${{pct(p.coc_med)}} / ${{pct(p.coc_high || 0)}}</td>
      <td>${{currency.format(p.annual_cash_flow_med)}}</td>
      <td>${{currency.format(p.annual_debt_service || 0)}}</td>
      <td>${{currency.format(p.total_cash_cost_to_buy || 0)}}</td>
      <td>${{(p.str_fit_score || 0).toFixed(1)}}</td>
      <td class="insight"><div>${{p.ai_insight_potential || 'Potential: n/a'}}</div><div>${{p.ai_insight_risk || 'Risk: n/a'}}</div></td>`;
    body.appendChild(row);
  }});
}}

function renderLuxuryFive() {{
  const body = document.getElementById('luxury5-body');
  const empty = document.getElementById('luxury-empty');
  body.innerHTML = '';

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
    const row = document.createElement('tr');
    row.innerHTML = `<td><strong>${{p.property_id}}</strong><br><span style="color:#64748b">${{p.address}}</span><br>${{listing}}</td>
      <td>${{p.city || ''}}${{p.city && p.zip_code ? ', ' : ''}}${{p.zip_code || ''}}</td>
      <td>${{p.scenario_tier || 'n/a'}}</td>
      <td>${{currency.format(p.list_price)}}</td>
      <td>${{pct(p.coc_low || 0)}} / ${{pct(p.coc_med)}} / ${{pct(p.coc_high || 0)}}</td>
      <td>${{currency.format(p.annual_cash_flow_med)}}</td>
      <td>${{currency.format(p.annual_debt_service || 0)}}</td>
      <td>${{currency.format(p.total_cash_cost_to_buy || 0)}}</td>
      <td>${{(p.str_fit_score || 0).toFixed(1)}}</td>
      <td class="insight"><div>${{p.ai_insight_potential || 'Potential: n/a'}}</div><div>${{p.ai_insight_risk || 'Risk: n/a'}}</div></td>`;
    body.appendChild(row);
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
    const monthlyRevenue = adr * 30 * occ;
    const annualRevenue = monthlyRevenue * 12;
    const annualOperating = home.annual_fixed_operating_costs + (annualRevenue * home.operating_variable_ratio);
    const annualCashFlow = annualRevenue - annualOperating - home.annual_debt_service;
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

  document.getElementById('luxury-note').textContent = payload.luxury_widget_note || '';
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

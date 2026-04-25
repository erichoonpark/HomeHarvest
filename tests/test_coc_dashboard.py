from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


def _load_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "examples" / "coc_dashboard.py"
    examples_dir = str(module_path.parent)
    if examples_dir not in sys.path:
        sys.path.insert(0, examples_dir)

    spec = importlib.util.spec_from_file_location("coc_dashboard", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sample_scored_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "property_id": "A",
                "status": "FOR_SALE",
                "street": "100 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 900000,
                "scenario_tier": "palm_springs_normal",
                "property_url": "https://example.com/a",
                "monthly_debt_payment": 5000,
                "annual_debt_service": 60000,
                "total_cash_cost_to_buy": 220000,
                "annual_fixed_operating_costs": 22000,
                "adr_low": 300,
                "adr_med": 420,
                "adr_high": 550,
                "occupancy_low": 0.50,
                "occupancy_med": 0.62,
                "occupancy_high": 0.74,
                "annual_revenue_med": 93744,
                "annual_operating_cost_med": 49500,
                "annual_cash_flow_low": -2000,
                "annual_cash_flow_med": 8000,
                "annual_cash_flow_high": 24000,
                "coc_low": -0.009,
                "coc_med": 0.036,
                "coc_high": 0.109,
                "str_fit_pass": True,
                "str_fit_score": 90,
                "str_fit_reasons_pass": "STR-supported neighborhood; Pool requirement met",
                "str_fit_reasons_fail": "",
            },
            {
                "property_id": "B",
                "status": "FOR_SALE",
                "street": "200 Main St",
                "city": "Indio",
                "state": "CA",
                "zip_code": "92201",
                "list_price": 600000,
                "scenario_tier": "fallback",
                "property_url": "https://example.com/b",
                "monthly_debt_payment": 3300,
                "annual_debt_service": 39600,
                "total_cash_cost_to_buy": 140000,
                "annual_fixed_operating_costs": 16000,
                "adr_low": 220,
                "adr_med": 300,
                "adr_high": 380,
                "occupancy_low": 0.45,
                "occupancy_med": 0.58,
                "occupancy_high": 0.68,
                "annual_revenue_med": 62640,
                "annual_operating_cost_med": 33000,
                "annual_cash_flow_low": -4000,
                "annual_cash_flow_med": 5000,
                "annual_cash_flow_high": 14000,
                "coc_low": -0.028,
                "coc_med": 0.036,
                "coc_high": 0.10,
                "str_fit_pass": False,
                "str_fit_score": 70,
                "str_fit_reasons_pass": "Beds/Baths meets 3+/2+",
                "str_fit_reasons_fail": "Pool requirement met",
            },
        ]
    )


def test_build_dashboard_payload_has_widgets_data():
    module = _load_module()
    payload = module.build_dashboard_payload(_sample_scored_df(), top_n=1, homes_limit=2)

    assert payload["total_ingested"] == 2
    assert payload["total_str_fit_passed"] == 1
    assert len(payload["top_properties"]) == 1
    assert len(payload["homes"]) == 1
    assert "total_cash_cost_to_buy" in payload["homes"][0]
    assert "adr_low" in payload["homes"][0]
    assert "property_url" in payload["top_properties"][0]
    assert "ai_insight_potential" in payload["top_properties"][0]
    assert "ai_insight_risk" in payload["top_properties"][0]
    assert "ai_insight_potential" in payload["homes"][0]
    assert "ai_insight_risk" in payload["homes"][0]


def test_render_dashboard_html_contains_expected_sections():
    module = _load_module()
    payload = module.build_dashboard_payload(_sample_scored_df(), top_n=2, homes_limit=2)
    html = module.render_dashboard_html(payload)

    assert "Total Ingested" in html
    assert "STR Fit Passed" in html
    assert "Top 5 STR-Passing Properties by COC Return" in html
    assert "View Listing" in html
    assert 'target="_blank"' in html
    assert "Potential:" in html
    assert "Risk:" in html
    assert "STR Filter Snapshot" in html
    assert "Home Breakdown with ADR + Occupancy Sliders" in html
    assert "payload" in html


def test_write_dashboard_html_creates_file(tmp_path: Path):
    module = _load_module()
    payload = module.build_dashboard_payload(_sample_scored_df(), top_n=2, homes_limit=2)
    out = tmp_path / "dash.html"
    module.write_dashboard_html(payload, out)

    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "COC Dashboard" in text


def test_top_properties_are_str_fit_only_and_deterministic_tiebreak():
    module = _load_module()
    df = pd.DataFrame(
        [
            {
                "property_id": "Z9",
                "status": "FOR_SALE",
                "street": "9 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 500000,
                "property_url": "https://example.com/z9",
                "coc_med": 0.08,
                "str_fit_score": 95,
                "str_fit_pass": True,
                "annual_cash_flow_med": 10000,
            },
            {
                "property_id": "A1",
                "status": "FOR_SALE",
                "street": "1 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 510000,
                "property_url": "https://example.com/a1",
                "coc_med": 0.08,
                "str_fit_score": 95,
                "str_fit_pass": True,
                "annual_cash_flow_med": 9000,
            },
            {
                "property_id": "B2",
                "status": "FOR_SALE",
                "street": "2 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 520000,
                "property_url": "https://example.com/b2",
                "coc_med": 0.12,
                "str_fit_score": 80,
                "str_fit_pass": True,
                "annual_cash_flow_med": 12000,
            },
            {
                "property_id": "X0",
                "status": "FOR_SALE",
                "street": "0 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 530000,
                "property_url": "https://example.com/x0",
                "coc_med": 0.20,
                "str_fit_score": 99,
                "str_fit_pass": False,
                "annual_cash_flow_med": 15000,
            },
        ]
    )

    payload = module.build_dashboard_payload(df, top_n=5, homes_limit=10)
    top_ids = [row["property_id"] for row in payload["top_properties"]]

    assert "X0" not in top_ids
    assert top_ids == ["B2", "A1", "Z9"]
    assert len(top_ids) <= 5

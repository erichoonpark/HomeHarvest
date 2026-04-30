from __future__ import annotations

import importlib.util
import json
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
                "dscr": 1.21,
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
                "coc_pre_tax": 0.05,
                "coc_post_tax": 0.04,
                "str_fit_pass": True,
                "str_fit_score": 90,
                "str_fit_reasons_pass": "STR-supported neighborhood; Pool requirement met",
                "str_fit_reasons_fail": "",
                "pool_enrichment_needed": False,
                "pool_enrichment_attempted": False,
                "pool_enrichment_result": "not_needed",
                "private_pool_verified": True,
                "is_palm_springs_priority_candidate": True,
                "priority_score": 0.82,
                "priority_rank": 1,
                "priority_reason_summary": "Ranked high for attractive price per sqft, strong lot-size utility.",
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
                "coc_pre_tax": 0.03,
                "coc_post_tax": 0.02,
                "str_fit_pass": False,
                "str_fit_score": 70,
                "str_fit_reasons_pass": "Beds/Baths meets 3+/2+",
                "str_fit_reasons_fail": "Private pool unknown",
                "pool_enrichment_needed": True,
                "pool_enrichment_attempted": True,
                "pool_enrichment_result": "still_unknown",
                "private_pool_verified": False,
                "pool_signal_confidence": "low",
                "pool_signal_sources": "none",
                "pool_evidence": "n/a",
                "is_palm_springs_priority_candidate": False,
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
    assert "beds" in payload["top_properties"][0]
    assert "full_baths" in payload["top_properties"][0]
    assert "sqft" in payload["top_properties"][0]
    assert "lot_sqft" in payload["top_properties"][0]
    assert "adr_med" in payload["top_properties"][0]
    assert "price_per_sqft" in payload["top_properties"][0]
    assert "coc_med" in payload["top_properties"][0]
    assert "coc_pre_tax" in payload["top_properties"][0]
    assert "coc_post_tax" in payload["top_properties"][0]
    assert "monthly_debt_payment" in payload["top_properties"][0]
    assert "total_cash_cost_to_buy" in payload["top_properties"][0]
    assert "dscr" in payload["top_properties"][0]
    assert "ai_insight_potential" in payload["top_properties"][0]
    assert "ai_insight_risk" in payload["top_properties"][0]
    assert "ai_insight_potential" in payload["homes"][0]
    assert "ai_insight_risk" in payload["homes"][0]
    assert "top_properties_luxury" in payload
    assert "top_properties_palm_springs_priority" in payload
    assert "total_palm_springs_priority_candidates" in payload
    assert "total_palm_springs_strict_pass" in payload
    assert "priority_ranking_note" in payload
    assert "total_luxury_candidates" in payload
    assert "luxury_widget_note" in payload
    assert "top_properties_luxury_value_budget" in payload
    assert "pool_verification_watchlist" in payload
    assert "total_pool_unknown_candidates" in payload
    assert "total_pool_verified_after_enrichment" in payload
    assert "total_luxury_value_budget_candidates" in payload
    assert "luxury_value_budget_cap" in payload
    assert "luxury_value_note" in payload


def test_render_dashboard_html_contains_expected_sections():
    module = _load_module()
    payload = module.build_dashboard_payload(_sample_scored_df(), top_n=2, homes_limit=2)
    html = module.render_dashboard_html(payload)

    assert "Palm Springs / Bermuda Dunes / Indio STR Review Queue" in html
    assert "Total Listings" in html
    assert "Full scrape: unavailable" in html
    assert "STR Fit Passed" in html
    assert "Today's Listing Update" in html
    assert "Fetched 0 listings, 0 were new." in html
    assert "Priority Candidates" not in html
    assert "Top Priority Score" not in html
    assert "Listings Overview" in html
    assert "Rank" in html
    assert "Property ID" in html
    assert "Address" in html
    assert "City" in html
    assert "ZIP" in html
    assert "List Price" in html
    assert "Price / Sq Ft" in html
    assert "Sq Ft" in html
    assert "Beds" in html
    assert "Baths" in html
    assert "Pre-Tax COC" in html
    assert "Post-Tax COC" in html
    assert "ADR (Med)" in html
    assert "Occ (Med)" in html
    assert "Total Cash To Buy" in html
    assert "Monthly Debt" in html
    assert "Scenario Tier" not in html
    assert "STR Fit Score" in html
    assert "View Listing" not in html
    assert 'target="_blank"' not in html
    assert "STR Filter Snapshot" in html
    assert "<table" in html
    assert "Rows/page" in html
    assert "page-prev" in html
    assert "page-next" in html
    assert "Financing Options" in html
    assert "Second Home" in html
    assert "Investment Home" in html
    assert "HELOC enabled" in html
    assert "mortgage-second-home" in html
    assert "mortgage-investment" in html
    assert "heloc-enabled" in html
    assert "function mortgagePayment" in html
    assert "function scenarioForRow" in html
    assert "computeScenarioRows()" in html
    assert "top5-potential-body" not in html
    assert "pool-watchlist-body" not in html
    assert "home-select" not in html
    assert "Home Breakdown with ADR + Occupancy Sliders" not in html
    assert "Luxury STR Opportunities" not in html
    assert "payload" in html


def test_build_dashboard_payload_includes_full_scrape_timestamp():
    module = _load_module()
    payload = module.build_dashboard_payload(
        _sample_scored_df(),
        top_n=1,
        homes_limit=2,
        full_scrape_completed_at="2026-04-30T08:15:00-07:00",
    )
    assert payload["full_scrape_completed_at"] == "2026-04-30T08:15:00-07:00"


def test_palm_springs_priority_widget_orders_by_pre_tax_coc():
    module = _load_module()
    rows = [
        {
            "property_id": "PS3",
            "status": "FOR_SALE",
            "street": "3 Palm St",
            "city": "Palm Springs",
            "state": "CA",
            "zip_code": "92262",
            "list_price": 900000,
            "sqft": 2000,
            "property_url": "https://example.com/ps3",
            "coc_post_tax": 0.05,
            "coc_pre_tax": 0.11,
            "str_fit_score": 90,
            "str_fit_pass": True,
            "is_palm_springs_priority_candidate": True,
            "priority_rank": 2,
            "priority_score": 0.80,
            "priority_reason_summary": "Reason 3",
        },
        {
            "property_id": "PS1",
            "status": "FOR_SALE",
            "street": "1 Palm St",
            "city": "Palm Springs",
            "state": "CA",
            "zip_code": "92262",
            "list_price": 850000,
            "sqft": 1900,
            "property_url": "https://example.com/ps1",
            "coc_post_tax": 0.09,
            "coc_pre_tax": 0.04,
            "str_fit_score": 92,
            "str_fit_pass": True,
            "is_palm_springs_priority_candidate": True,
            "priority_rank": 1,
            "priority_score": 0.75,
            "priority_reason_summary": "Reason 1",
        },
        {
            "property_id": "NON",
            "status": "FOR_SALE",
            "street": "1 Other St",
            "city": "Indio",
            "state": "CA",
            "zip_code": "92201",
            "list_price": 600000,
            "sqft": 1800,
            "property_url": "https://example.com/non",
            "coc_post_tax": 0.30,
            "str_fit_score": 99,
            "str_fit_pass": True,
            "is_palm_springs_priority_candidate": False,
        },
    ]
    payload = module.build_dashboard_payload(pd.DataFrame(rows), top_n=10, homes_limit=10)
    priority_ids = [row["property_id"] for row in payload["top_properties_palm_springs_priority"]]
    assert priority_ids == ["PS3", "PS1"]
    assert payload["total_palm_springs_priority_candidates"] == 2


def test_render_dashboard_html_removes_legacy_modules():
    module = _load_module()
    payload = module.build_dashboard_payload(_sample_scored_df(), top_n=2, homes_limit=2)
    html = module.render_dashboard_html(payload)

    assert "Pool Verification Watchlist" not in html
    assert "Luxury STR Value Under $1.5M" not in html
    assert "Top STR-Passing Properties by COC Return" not in html
    assert "renderPalmSpringsPriority" not in html


def test_default_top_n_is_10():
    module = _load_module()
    many_rows = []
    for idx in range(12):
        many_rows.append(
            {
                "property_id": f"P{idx}",
                "status": "FOR_SALE",
                "street": f"{idx} Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 500000 + idx,
                "property_url": f"https://example.com/p{idx}",
                "coc_med": 0.20 - (idx * 0.01),
                "str_fit_score": 90 - idx,
                "str_fit_pass": True,
                "annual_cash_flow_med": 10000 + idx,
                "beds": 3,
                "full_baths": 2,
                "adr_med": 450,
                "scenario_tier": "palm_springs_normal",
            }
        )
    df = pd.DataFrame(many_rows)

    payload = module.build_dashboard_payload(df, homes_limit=20)
    assert len(payload["top_properties"]) == 10


def test_write_dashboard_html_creates_file(tmp_path: Path):
    module = _load_module()
    payload = module.build_dashboard_payload(_sample_scored_df(), top_n=2, homes_limit=2)
    out = tmp_path / "dash.html"
    module.write_dashboard_html(payload, out)

    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "COC Dashboard" in text


def test_build_dashboard_payload_includes_health_report_kpis():
    module = _load_module()
    health_report = {
        "batch_run_at": "2026-04-28T08:15:00-07:00",
        "summary": {"new_rows": 14, "fetched_rows": 27},
    }

    payload = module.build_dashboard_payload(_sample_scored_df(), top_n=1, homes_limit=2, health_report=health_report)

    assert payload["new_listings_today"] == 14
    assert payload["fetched_rows_today"] == 27
    assert payload["listings_pulled_at"] == "2026-04-28T08:15:00-07:00"


def test_build_dashboard_payload_missing_health_report_defaults():
    module = _load_module()
    payload = module.build_dashboard_payload(_sample_scored_df(), top_n=1, homes_limit=2, health_report={})

    assert payload["new_listings_today"] == 0
    assert payload["fetched_rows_today"] == 0
    assert payload["listings_pulled_at"] is None


def test_load_incremental_health_report_handles_missing_and_invalid(tmp_path: Path):
    module = _load_module()
    missing = tmp_path / "missing.json"
    assert module._load_incremental_health_report(missing) == {}

    bad = tmp_path / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")
    assert module._load_incremental_health_report(bad) == {}

    ok = tmp_path / "ok.json"
    ok.write_text(
        json.dumps({"batch_run_at": "2026-04-28T07:00:00-07:00", "summary": {"new_rows": 3, "fetched_rows": 9}}),
        encoding="utf-8",
    )
    loaded = module._load_incremental_health_report(ok)
    assert loaded["summary"]["new_rows"] == 3


def test_render_dashboard_html_wires_new_kpi_dom_ids():
    module = _load_module()
    health_report = {
        "batch_run_at": "2026-04-28T08:15:00-07:00",
        "summary": {"new_rows": 14, "fetched_rows": 27},
    }
    payload = module.build_dashboard_payload(_sample_scored_df(), top_n=2, homes_limit=2, health_report=health_report)
    html = module.render_dashboard_html(payload)

    assert 'id="new-listings-today"' in html
    assert 'id="listing-update-detail"' in html
    assert 'id="listings-pulled-at"' in html
    assert "formatPullTimestamp" in html
    assert "formatListingUpdateDetail" in html
    assert "Last run date: unavailable" in html
    assert "payload.new_listings_today" in html
    assert "payload.fetched_rows_today" in html
    assert "payload.listings_pulled_at" in html


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
                "coc_post_tax": 0.01,
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
                "coc_post_tax": 0.06,
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
                "coc_post_tax": 0.03,
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
                "coc_post_tax": 0.20,
                "str_fit_score": 99,
                "str_fit_pass": False,
                "annual_cash_flow_med": 15000,
            },
        ]
    )

    payload = module.build_dashboard_payload(df, top_n=5, homes_limit=10)
    top_ids = [row["property_id"] for row in payload["top_properties"]]

    assert "X0" not in top_ids
    assert top_ids == ["A1", "B2", "Z9"]
    assert len(top_ids) <= 5


def test_luxury_widget_filters_and_orders_with_max_five():
    module = _load_module()
    rows = []
    for idx in range(7):
        rows.append(
            {
                "property_id": f"L{idx}",
                "status": "FOR_SALE",
                "street": f"{idx} Luxury Ave",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 2_000_000 + idx * 10_000,
                "property_url": f"https://example.com/l{idx}",
                "scenario_tier": "palm_springs_luxury",
                "coc_med": 0.20 - (idx * 0.01),
                "coc_post_tax": 0.10 - (idx * 0.005),
                "str_fit_score": 90 - idx,
                "str_fit_pass": True,
                "annual_cash_flow_med": 10000 + idx,
            }
        )
    rows.append(
        {
            "property_id": "N0",
            "status": "FOR_SALE",
            "street": "0 Normal St",
            "city": "Palm Springs",
            "state": "CA",
            "zip_code": "92262",
            "list_price": 600000,
            "property_url": "https://example.com/n0",
            "scenario_tier": "palm_springs_normal",
            "coc_med": 0.50,
            "coc_post_tax": 0.50,
            "str_fit_score": 99,
            "str_fit_pass": True,
            "annual_cash_flow_med": 20000,
        }
    )
    rows.append(
        {
            "property_id": "L_FAIL",
            "status": "FOR_SALE",
            "street": "1 Luxury Fail Ave",
            "city": "Palm Springs",
            "state": "CA",
            "zip_code": "92262",
            "list_price": 2_500_000,
            "property_url": "https://example.com/l_fail",
            "scenario_tier": "palm_springs_luxury",
            "coc_med": 0.80,
            "coc_post_tax": 0.80,
            "str_fit_score": 100,
            "str_fit_pass": False,
            "annual_cash_flow_med": 50000,
        }
    )
    df = pd.DataFrame(rows)

    payload = module.build_dashboard_payload(df, top_n=5, homes_limit=20)
    luxury_ids = [row["property_id"] for row in payload["top_properties_luxury"]]

    assert payload["total_luxury_candidates"] == 0
    assert len(luxury_ids) == 0
    assert "N0" not in luxury_ids
    assert "L_FAIL" not in luxury_ids


def test_luxury_widget_empty_state_renders():
    module = _load_module()
    df = _sample_scored_df().copy()
    df["scenario_tier"] = "palm_springs_normal"

    payload = module.build_dashboard_payload(df, top_n=5, homes_limit=10)
    html = module.render_dashboard_html(payload)

    assert payload["total_luxury_candidates"] == 0
    assert payload["top_properties_luxury"] == []
    assert "Luxury STR Opportunities" not in html


def test_budget_luxury_value_widget_filters_orders_and_caps_to_30():
    module = _load_module()
    rows = []
    for idx in range(35):
        rows.append(
            {
                "property_id": f"B{idx:02d}",
                "status": "FOR_SALE",
                "street": f"{idx} Value Way",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 1_000_000 + (idx * 5_000),
                "sqft": 2000 + idx,
                "property_url": f"https://example.com/b{idx}",
                "coc_pre_tax": 0.03 + (idx * 0.001),
                "coc_post_tax": 0.05 - (idx * 0.0005),
                "str_fit_score": 95 - idx,
                "str_fit_pass": True,
                "annual_cash_flow_med": 8_000 + idx,
            }
        )
    rows.append(
        {
            "property_id": "OVER_BUDGET",
            "status": "FOR_SALE",
            "street": "1 Over Budget Dr",
            "city": "Palm Springs",
            "state": "CA",
            "zip_code": "92262",
            "list_price": 1_600_000,
            "sqft": 2500,
            "property_url": "https://example.com/over",
            "coc_pre_tax": 0.40,
            "coc_post_tax": 0.30,
            "str_fit_score": 99,
            "str_fit_pass": True,
            "annual_cash_flow_med": 30_000,
        }
    )
    rows.append(
        {
            "property_id": "NOT_FIT",
            "status": "FOR_SALE",
            "street": "2 Not Fit Dr",
            "city": "Palm Springs",
            "state": "CA",
            "zip_code": "92262",
            "list_price": 1_200_000,
            "sqft": 2200,
            "property_url": "https://example.com/notfit",
            "coc_pre_tax": 0.50,
            "coc_post_tax": 0.40,
            "str_fit_score": 100,
            "str_fit_pass": False,
            "annual_cash_flow_med": 45_000,
        }
    )
    df = pd.DataFrame(rows)

    payload = module.build_dashboard_payload(df, top_n=10, homes_limit=20)
    widget_rows = payload["top_properties_luxury_value_budget"]
    widget_ids = [r["property_id"] for r in widget_rows]

    assert payload["luxury_value_budget_cap"] == 1_500_000
    assert payload["total_luxury_value_budget_candidates"] == 35
    assert len(widget_rows) == 30
    assert "OVER_BUDGET" not in widget_ids
    assert "NOT_FIT" not in widget_ids
    assert all("value_score" in r for r in widget_rows)
    assert all("price_per_sqft" in r for r in widget_rows)
    assert all(r["ranking_metric_used"] in {"coc_post_tax", "coc_pre_tax"} for r in widget_rows)

    for prior, curr in zip(widget_rows, widget_rows[1:]):
        if prior["value_score"] != curr["value_score"]:
            assert prior["value_score"] > curr["value_score"]
        elif prior["coc_post_tax"] != curr["coc_post_tax"]:
            assert prior["coc_post_tax"] > curr["coc_post_tax"]
        elif prior["price_per_sqft"] != curr["price_per_sqft"]:
            assert prior["price_per_sqft"] < curr["price_per_sqft"]
        else:
            assert prior["property_id"] < curr["property_id"]


def test_budget_luxury_value_widget_empty_state_renders():
    module = _load_module()
    df = _sample_scored_df().copy()
    df["list_price"] = 2_000_000
    df["str_fit_pass"] = True

    payload = module.build_dashboard_payload(df, top_n=10, homes_limit=10)
    html = module.render_dashboard_html(payload)

    assert payload["top_properties_luxury_value_budget"] == []
    assert payload["total_luxury_value_budget_candidates"] == 0
    assert "Luxury STR Value Under $1.5M" not in html


def test_pool_watchlist_empty_state_renders():
    module = _load_module()
    df = _sample_scored_df().copy()
    df["pool_enrichment_needed"] = False
    df["private_pool_verified"] = True

    payload = module.build_dashboard_payload(df, top_n=10, homes_limit=10)
    html = module.render_dashboard_html(payload)

    assert payload["pool_verification_watchlist"] == []
    assert payload["total_pool_unknown_candidates"] == 0
    assert "Pool Verification Watchlist" not in html


def test_excluded_coownership_listing_is_hard_removed():
    module = _load_module()
    df = pd.DataFrame(
        [
            {
                "property_id": "2310318356",
                "status": "FOR_SALE",
                "street": "1961 S Palm Canyon Dr",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92264",
                "list_price": 299000,
                "sqft": 2728,
                "str_fit_pass": True,
                "str_fit_score": 110,
                "coc_post_tax": 0.29,
                "is_palm_springs_priority_candidate": True,
                "priority_rank": 1,
                "priority_score": 0.99,
                "priority_reason_summary": "Excluded co-ownership test row.",
            },
            {
                "property_id": "SAFE1",
                "status": "FOR_SALE",
                "street": "123 Safe St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92264",
                "list_price": 800000,
                "sqft": 2000,
                "str_fit_pass": True,
                "str_fit_score": 100,
                "coc_post_tax": 0.08,
                "is_palm_springs_priority_candidate": True,
                "priority_rank": 2,
                "priority_score": 0.70,
                "priority_reason_summary": "Safe retained row.",
            },
        ]
    )

    payload = module.build_dashboard_payload(df, top_n=10, homes_limit=10)

    assert payload["total_ingested"] == 1
    assert payload["total_str_fit_passed"] == 1
    top_ids = [row["property_id"] for row in payload["top_properties"]]
    priority_ids = [row["property_id"] for row in payload["top_properties_palm_springs_priority"]]
    assert "2310318356" not in top_ids
    assert "2310318356" not in priority_ids
    assert top_ids == ["SAFE1"]

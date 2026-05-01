from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd


def _load_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "examples" / "coc_scorecard.py"
    examples_dir = str(module_path.parent)
    if examples_dir not in sys.path:
        sys.path.insert(0, examples_dir)

    spec = importlib.util.spec_from_file_location("coc_scorecard", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _assumptions() -> dict:
    return {
        "financing": {
            "down_payment_pct": 0.10,
            "interest_rate_annual": 0.0575,
            "loan_term_years": 30,
        },
        "cost_model": {
            "closing_cost_pct": 0.025,
            "furnishing_pct": 0.08,
            "rehab_reserve_pct": 0.03,
            "initial_reserve_pct": 0.01,
            "management_fee_pct": 0.18,
            "capex_pct": 0.05,
            "maintenance_pct": 0.06,
            "vacancy_buffer_pct": 0.04,
            "turnover_buffer_pct": 0.03,
            "insurance_rate_pct_annual": 0.004,
            "property_tax_rate_pct_annual": 0.012,
            "utilities_monthly": 650,
        },
        "scenario_routing": {"luxury_price_threshold": 2_000_000},
        "adr_engine": {
            "base_adr_market": 430,
            "pool_multiplier": 1.12,
            "renovation_multiplier": 1.08,
            "bedroom_multipliers": {"1": 0.75, "2": 0.9, "3": 1.0, "4": 1.15, "5+": 1.3},
            "luxury_uplift_pct": 0.35,
        },
        "contract_policy": {
            "annual_bookable_nights": 365,
            "max_str_bookings_per_year": 26,
            "avg_stay_nights_per_booking": 4,
        },
        "mtr": {"mtr_adr_multiplier": 0.55, "mtr_occupancy": 0.72},
        "heloc": {
            "enabled": False,
            "interest_only": True,
            "rate_annual": 0.085,
            "draw_strategy": "down_payment_only",
        },
        "tax": {
            "effective_combined_tax_rate": 0.37,
            "analysis_year": 1,
            "building_allocation_pct": 0.8,
            "standard_recovery_years": 27.5,
            "cost_seg_start_year": 2,
            "cost_seg_bonus_pct": 0.2,
        },
        "ranking_metric": "coc_post_tax",
        "scenario_presets": {
            "palm_springs_normal": {
                "low": {"adr": 340, "occupancy_rate": 0.52},
                "med": {"adr": 430, "occupancy_rate": 0.62},
                "high": {"adr": 520, "occupancy_rate": 0.72},
            },
            "palm_springs_luxury": {
                "low": {"adr": 950, "occupancy_rate": 0.45},
                "med": {"adr": 1250, "occupancy_rate": 0.58},
                "high": {"adr": 1650, "occupancy_rate": 0.70},
            },
            "fallback": {
                "low": {"adr": 260, "occupancy_rate": 0.48},
                "med": {"adr": 330, "occupancy_rate": 0.58},
                "high": {"adr": 420, "occupancy_rate": 0.68},
            },
        },
    }


def test_mortgage_payment_math():
    module = _load_module()
    payment = module.mortgage_payment(400000, 0.0575, 30)
    assert round(payment, 2) == 2334.29


def test_tier_routing_thresholds():
    module = _load_module()

    normal = pd.Series({"city": "Palm Springs", "list_price": 1_500_000})
    luxury = pd.Series({"city": "Palm Springs", "list_price": 2_500_000})
    fallback = pd.Series({"city": "Indio", "list_price": 1_100_000})

    assert module.choose_scenario_tier(normal, 2_000_000) == "palm_springs_normal"
    assert module.choose_scenario_tier(luxury, 2_000_000) == "palm_springs_luxury"
    assert module.choose_scenario_tier(fallback, 2_000_000) == "fallback"


def test_coc_columns_exist_and_rank_stable():
    module = _load_module()
    assumptions = _assumptions()

    df = pd.DataFrame(
        [
            {
                "property_id": "A",
                "status": "FOR_SALE",
                "street": "100 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 900000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 1800,
                "property_url": "https://example.com/a",
                "str_fit_pass": True,
            },
            {
                "property_id": "B",
                "status": "FOR_SALE",
                "street": "200 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92264",
                "list_price": 2200000,
                "beds": 4,
                "full_baths": 3,
                "sqft": 3200,
                "property_url": "https://example.com/b",
                "str_fit_pass": True,
            },
            {
                "property_id": "C",
                "status": "SOLD",
                "street": "300 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 800000,
                "property_url": "https://example.com/c",
                "str_fit_pass": True,
            },
        ]
    )

    scored = module.score_properties(df, assumptions)

    assert set(scored["property_id"]) == {"A", "B"}
    assert all(
        col in scored.columns
        for col in [
            "monthly_debt_payment",
            "total_cash_cost_to_buy",
            "coc_low",
            "coc_med",
            "coc_high",
            "adr_assumed",
            "str_nights_capped",
            "mtr_nights",
            "annual_revenue_total",
            "annual_cash_flow_pre_tax",
            "coc_pre_tax",
            "taxable_income",
            "tax_impact",
            "annual_cash_flow_post_tax",
            "coc_post_tax",
            "heloc_interest_annual",
            "mortgage_interest_annual",
            "depreciation_annual",
            "depreciation_costseg_annual",
        ]
    )
    assert scored["coc_post_tax"].iloc[0] >= scored["coc_post_tax"].iloc[1]


def test_workbook_generation_contains_required_sheets(tmp_path: Path):
    module = _load_module()
    assumptions = _assumptions()

    df = pd.DataFrame(
        [
            {
                "property_id": "A",
                "status": "FOR_SALE",
                "street": "100 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 900000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 1800,
                "property_url": "https://example.com/a",
                "str_fit_pass": True,
            }
        ]
    )

    scored = module.score_properties(df, assumptions)
    out = tmp_path / "coc_scorecard.xlsx"
    module.write_scorecard(scored, assumptions, out, top_n=25)

    wb = pd.ExcelFile(out)
    assert set(["Top25_COC", "Assumptions", "All_Scored"]).issubset(set(wb.sheet_names))

    top = pd.read_excel(out, sheet_name="Top25_COC")
    assert "monthly_debt_payment" in top.columns
    assert "total_cash_cost_to_buy" in top.columns
    assert "coc_pre_tax" in top.columns
    assert "coc_post_tax" in top.columns


def test_workbook_generation_uses_dynamic_top_sheet_name(tmp_path: Path):
    module = _load_module()
    assumptions = _assumptions()

    df = pd.DataFrame(
        [
            {
                "property_id": "A",
                "status": "FOR_SALE",
                "street": "100 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 900000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 1800,
                "property_url": "https://example.com/a",
                "str_fit_pass": True,
            }
        ]
    )

    scored = module.score_properties(df, assumptions)
    out = tmp_path / "coc_scorecard_top10.xlsx"
    module.write_scorecard(scored, assumptions, out, top_n=10)

    wb = pd.ExcelFile(out)
    assert set(["Top10_COC", "Assumptions", "All_Scored"]).issubset(set(wb.sheet_names))


def test_load_assumptions_from_json(tmp_path: Path):
    module = _load_module()
    path = tmp_path / "assumptions.json"
    path.write_text(json.dumps(_assumptions()), encoding="utf-8")
    loaded = module.load_assumptions(path)
    assert loaded["financing"]["interest_rate_annual"] == 0.0575


def test_score_properties_prioritizes_str_fit_rows_in_ranking():
    module = _load_module()
    assumptions = _assumptions()

    df = pd.DataFrame(
        [
            {
                "property_id": "A",
                "status": "FOR_SALE",
                "street": "100 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 900000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 1800,
                "property_url": "https://example.com/a",
                "str_fit_pass": True,
            },
            {
                "property_id": "MOBILE",
                "status": "FOR_SALE",
                "street": "55 Desert Mobile Home Park",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92264",
                "list_price": 450000,
                "beds": 2,
                "full_baths": 2,
                "sqft": 900,
                "property_url": "https://example.com/mobile",
                "str_fit_pass": False,
            },
            {
                "property_id": "LOT",
                "status": "FOR_SALE",
                "street": "80394 Avenue 48",
                "city": "Indio",
                "state": "CA",
                "zip_code": "92201",
                "list_price": 30000,
                "beds": None,
                "full_baths": None,
                "sqft": None,
                "property_url": "https://example.com/lot",
                "str_fit_pass": False,
            },
            {
                "property_id": "SHARE_A",
                "status": "FOR_SALE",
                "street": "1961 S Palm Canyon Dr",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92264",
                "list_price": 260000,
                "beds": 3,
                "full_baths": 3,
                "sqft": 2728,
                "property_url": "https://www.realtor.com/realestateandhomes-detail/1961-S-Palm-Canyon-Dr-3_Palm-Springs_CA_92264_M95667-30278",
                "str_fit_pass": False,
            },
            {
                "property_id": "SHARE_B",
                "status": "FOR_SALE",
                "street": "1961 S Palm Canyon Dr",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92264",
                "list_price": 299000,
                "beds": 3,
                "full_baths": 3,
                "sqft": 2728,
                "property_url": "https://www.realtor.com/realestateandhomes-detail/1961-S-Palm-Canyon-Dr_Palm-Springs_CA_92264_M23103-18356",
                "str_fit_pass": False,
            },
        ]
    )

    scored = module.score_properties(df, assumptions)
    assert set(scored["property_id"]) == {"A", "MOBILE", "LOT", "SHARE_A", "SHARE_B"}
    assert scored.iloc[0]["property_id"] == "A"
    assert bool(scored.iloc[0]["str_fit_pass"]) is True


def test_score_properties_excludes_manual_coownership_addresses():
    module = _load_module()
    assumptions = _assumptions()

    df = pd.DataFrame(
        [
            {
                "property_id": "1086968872",
                "status": "FOR_SALE",
                "street": "470 E Avenida Olancha",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92264",
                "list_price": 175000,
                "beds": 5,
                "full_baths": None,
                "sqft": 1550,
                "property_url": "https://www.realtor.com/realestateandhomes-detail/470-E-Avenida-Olancha_Palm-Springs_CA_92264_M10869-68872",
                "str_fit_pass": False,
            },
            {
                "property_id": "A",
                "status": "FOR_SALE",
                "street": "100 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 900000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 1800,
                "property_url": "https://example.com/a",
                "str_fit_pass": True,
            },
        ]
    )

    scored = module.score_properties(df, assumptions)
    assert set(scored["property_id"]) == {"A"}
    assert scored.iloc[0]["property_id"] == "A"


def test_score_properties_excludes_stevens_rd_manual_exclusion():
    module = _load_module()
    assumptions = _assumptions()

    df = pd.DataFrame(
        [
            {
                "property_id": "STEVENS",
                "status": "FOR_SALE",
                "street": "594 W Stevens Rd",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 1_250_000,
                "beds": 4,
                "full_baths": 3,
                "sqft": 2600,
                "property_url": "https://example.com/stevens",
                "str_fit_pass": True,
            },
            {
                "property_id": "A",
                "status": "FOR_SALE",
                "street": "100 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 900000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 1800,
                "property_url": "https://example.com/a",
                "str_fit_pass": True,
            },
        ]
    )

    scored = module.score_properties(df, assumptions)
    assert set(scored["property_id"]) == {"A"}


def test_score_properties_requires_str_fit_by_default():
    module = _load_module()
    assumptions = _assumptions()
    df = pd.DataFrame(
        [
            {
                "property_id": "A",
                "status": "FOR_SALE",
                "street": "100 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 900000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 1800,
                "property_url": "https://example.com/a",
            }
        ]
    )

    try:
        module.score_properties(df, assumptions)
    except ValueError as exc:
        assert "str_fit_pass" in str(exc)
    else:
        raise AssertionError("Expected score_properties to require str_fit_pass by default.")


def test_score_properties_run_all_override():
    module = _load_module()
    assumptions = _assumptions()
    df = pd.DataFrame(
        [
            {
                "property_id": "A",
                "status": "FOR_SALE",
                "street": "100 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 900000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 1800,
                "property_url": "https://example.com/a",
            }
        ]
    )

    scored = module.score_properties(df, assumptions, require_str_fit=False)
    assert set(scored["property_id"]) == {"A"}


def test_palm_springs_26_booking_cap_and_mtr_fallback():
    module = _load_module()
    assumptions = _assumptions()
    assumptions["contract_policy"]["avg_stay_nights_per_booking"] = 3

    df = pd.DataFrame(
        [
            {
                "property_id": "A",
                "status": "FOR_SALE",
                "street": "100 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 900000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 1800,
                "property_url": "https://example.com/a",
                "str_fit_pass": True,
            }
        ]
    )

    scored = module.score_properties(df, assumptions)
    row = scored.iloc[0]
    assert float(row["str_nights_capped"]) == 78.0
    assert float(row["mtr_nights"]) > 0
    assert float(row["mtr_revenue"]) > 0


def test_adr_multipliers_and_luxury_uplift_raise_assumed_adr():
    module = _load_module()
    assumptions = _assumptions()

    df = pd.DataFrame(
        [
            {
                "property_id": "NORMAL",
                "status": "FOR_SALE",
                "street": "100 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 900000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 1800,
                "has_pool_inferred": False,
                "property_url": "https://example.com/normal",
                "str_fit_pass": True,
            },
            {
                "property_id": "LUX",
                "status": "FOR_SALE",
                "street": "200 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 2500000,
                "beds": 4,
                "full_baths": 3,
                "sqft": 3200,
                "has_pool_inferred": True,
                "description": "Fully renovated designer home with resort pool",
                "property_url": "https://example.com/lux",
                "str_fit_pass": True,
            },
        ]
    )

    scored = module.score_properties(df, assumptions)
    normal_adr = float(scored[scored["property_id"] == "NORMAL"]["adr_assumed"].iloc[0])
    lux_adr = float(scored[scored["property_id"] == "LUX"]["adr_assumed"].iloc[0])
    assert lux_adr > normal_adr


def test_heloc_interest_and_post_tax_columns_present_when_enabled():
    module = _load_module()
    assumptions = _assumptions()
    assumptions["heloc"]["enabled"] = True
    assumptions["heloc"]["draw_strategy"] = "down_payment_and_closing"

    df = pd.DataFrame(
        [
            {
                "property_id": "A",
                "status": "FOR_SALE",
                "street": "100 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 900000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 1800,
                "property_url": "https://example.com/a",
                "str_fit_pass": True,
            }
        ]
    )

    scored = module.score_properties(df, assumptions)
    row = scored.iloc[0]
    assert float(row["heloc_interest_annual"]) > 0
    assert "coc_pre_tax" in scored.columns
    assert "coc_post_tax" in scored.columns


def test_year_two_costseg_increases_depreciation():
    module = _load_module()
    assumptions_year1 = _assumptions()
    assumptions_year2 = _assumptions()
    assumptions_year2["tax"]["analysis_year"] = 2

    df = pd.DataFrame(
        [
            {
                "property_id": "A",
                "status": "FOR_SALE",
                "street": "100 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 900000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 1800,
                "property_url": "https://example.com/a",
                "str_fit_pass": True,
            }
        ]
    )

    row1 = module.score_properties(df, assumptions_year1).iloc[0]
    row2 = module.score_properties(df, assumptions_year2).iloc[0]
    assert float(row1["depreciation_costseg_annual"]) == 0.0
    assert float(row2["depreciation_costseg_annual"]) > 0.0


def test_auto_tier_and_provenance_columns_present():
    module = _load_module()
    assumptions = _assumptions()
    df = pd.DataFrame(
        [
            {
                "property_id": "AUTO_LUX",
                "status": "FOR_SALE",
                "street": "500 Vista Lux",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 2100000,
                "beds": 5,
                "full_baths": 4,
                "sqft": 4100,
                "has_pool_inferred": True,
                "eligible_geo_cap_zip": True,
                "str_fit_pass": True,
            }
        ]
    )
    scored = module.score_properties(df, assumptions)
    row = scored.iloc[0]
    assert row["tier_auto"] in {"palm_springs_normal", "palm_springs_luxury", "fallback"}
    assert row["tier_final"] in {"palm_springs_normal", "palm_springs_luxury", "fallback"}
    assert row["tier_source"] in {"auto", "manual"}
    assert float(row["adr_auto"]) > 0
    assert float(row["adr_final"]) > 0
    assert row["adr_source"] in {"auto", "manual"}
    assert float(row["occupancy_auto"]) > 0
    assert float(row["occupancy_final"]) > 0
    assert row["occupancy_source"] in {"auto", "manual"}


def test_manual_overrides_take_precedence(tmp_path: Path):
    module = _load_module()
    assumptions = _assumptions()
    overrides_path = tmp_path / "property_overrides.json"
    overrides_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "property_id": "OVR1",
                        "tier": "luxury",
                        "adr": 1777,
                        "occupancy": 0.66,
                        "updated_at": "2026-04-30T12:00:00Z",
                        "note": "manual analyst override",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    overrides = module.load_property_overrides(overrides_path, assumptions)
    df = pd.DataFrame(
        [
            {
                "property_id": "OVR1",
                "status": "FOR_SALE",
                "street": "700 Override Ave",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 1300000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 1900,
                "has_pool_inferred": False,
                "str_fit_pass": True,
            }
        ]
    )
    scored = module.score_properties(df, assumptions, overrides_by_property_id=overrides)
    row = scored.iloc[0]
    assert row["tier_final"] == "palm_springs_luxury"
    assert row["tier_source"] == "manual"
    assert float(row["adr_final"]) == 1777.0
    assert row["adr_source"] == "manual"
    assert float(row["occupancy_final"]) == 0.66
    assert row["occupancy_source"] == "manual"
    assert "manual analyst override" in str(row["override_note"])

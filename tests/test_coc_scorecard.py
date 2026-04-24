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
        for col in ["monthly_debt_payment", "total_cash_cost_to_buy", "coc_low", "coc_med", "coc_high"]
    )
    assert scored["coc_med"].iloc[0] >= scored["coc_med"].iloc[1]


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


def test_score_properties_keeps_manual_coownership_for_audit_but_ranks_fit_first():
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
    assert set(scored["property_id"]) == {"A", "1086968872"}
    assert scored.iloc[0]["property_id"] == "A"


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

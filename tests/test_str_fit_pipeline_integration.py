from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _coc_assumptions() -> dict:
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


def _str_fit_assumptions() -> dict:
    return {
        "hard_gates": {
            "require_quality": True,
            "require_str_supported_neighborhood": True,
            "require_price_range": True,
            "require_beds_baths": True,
            "require_location": True,
            "require_geo_cap_zip": True,
            "min_beds": 2,
            "min_full_baths": 2,
            "min_list_price": 100000,
            "max_list_price": 3000000,
        },
        "location": {
            "enabled": True,
            "preferred_cities": ["Palm Springs", "Indio", "Bermuda Dunes"],
            "scope_zip_candidates": ["92262"],
        },
        "geography": {
            "enabled": True,
            "require_under_cap_zip": True,
            "cap_percentage_max": 0.20,
            "neighborhood_cap_workbook": "examples/zips/palm_springs_neighborhood_cap_by_zip.xlsx",
            "zip_codes_column": "zip_codes",
            "primary_zip_column": "primary_zip",
            "percentage_column": "current_neighborhood_percentage",
            "fail_open_if_missing_cap_data": True,
        },
        "ranking_weights": {
            "quality": 30,
            "str_support": 25,
            "beds_baths": 15,
            "price_range": 5,
            "location": 5,
            "geo_cap_zip": 10,
            "pool_signal": 20,
        },
        "shortlist": {
            "enabled": True,
            "target_pass_rate_min": 0.10,
            "target_pass_rate_max": 0.20,
            "target_pass_rate_target": 0.15,
            "ranking_metric": "coc_med",
            "ranking_direction": "desc",
            "coc_assumptions_path": "examples/data/coc_assumptions.json",
        },
    }


def test_combined_to_str_fit_to_coc_pipeline():
    repo_root = Path(__file__).resolve().parents[1]
    examples_dir = str(repo_root / "examples")
    if examples_dir not in sys.path:
        sys.path.insert(0, examples_dir)

    str_fit = _load_module("str_suitability_filters", repo_root / "examples" / "str_suitability_filters.py")
    coc = _load_module("coc_scorecard", repo_root / "examples" / "coc_scorecard.py")

    combined = pd.DataFrame(
        [
            {
                "property_id": "PASS",
                "status": "FOR_SALE",
                "street": "100 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 900000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 1800,
                "str_nbhd_under_cap_current": 1,
                "is_private_pool": True,
                "is_private_pool_known": True,
                "property_url": "https://example.com/pass",
            },
            {
                "property_id": "FAIL",
                "status": "FOR_SALE",
                "street": "200 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 900000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 1800,
                "str_nbhd_under_cap_current": 0,
                "is_private_pool": False,
                "is_private_pool_known": True,
                "property_url": "https://example.com/fail",
            },
        ]
    )

    str_fit_df = str_fit.evaluate_str_fit(combined, _str_fit_assumptions())
    assert set(str_fit_df["property_id"]) == {"PASS", "FAIL"}
    assert set(str_fit_df[str_fit_df["str_fit_pass"]]["property_id"]) == {"PASS"}

    scored = coc.score_properties(str_fit_df, _coc_assumptions())
    assert set(scored["property_id"]) == {"PASS", "FAIL"}
    assert scored.iloc[0]["property_id"] == "PASS"

    scored_all = coc.score_properties(str_fit_df, _coc_assumptions(), require_str_fit=False)
    assert set(scored_all["property_id"]) == {"PASS", "FAIL"}

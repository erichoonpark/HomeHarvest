from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


def _load_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "examples" / "str_suitability_filters.py"
    examples_dir = str(module_path.parent)
    if examples_dir not in sys.path:
        sys.path.insert(0, examples_dir)

    spec = importlib.util.spec_from_file_location("str_suitability_filters", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _assumptions() -> dict:
    return {
        "thresholds": {
            "min_beds": 3,
            "min_full_baths": 2,
            "min_list_price": 100000,
            "max_list_price": 3000000,
        },
        "requirements": {
            "require_str_supported_neighborhood": True,
            "require_pool": True,
            "exclude_unknown_private_pool": True,
        },
        "location": {
            "enabled": True,
            "preferred_cities": ["Palm Springs", "Indio", "Bermuda Dunes"],
        },
        "scoring_weights": {
            "quality": 30,
            "str_support": 25,
            "pool": 20,
            "beds_baths": 15,
            "price_range": 5,
            "location": 5,
        },
    }


def test_evaluate_str_fit_gates_and_scores():
    module = _load_module()
    assumptions = _assumptions()

    df = pd.DataFrame(
        [
            {
                "property_id": "PASS",
                "status": "FOR_SALE",
                "street": "100 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 950000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 1800,
                "str_nbhd_under_cap_current": 1,
                "is_private_pool": True,
                "is_private_pool_known": True,
                "property_url": "https://example.com/pass",
            },
            {
                "property_id": "FAIL_NO_POOL",
                "status": "FOR_SALE",
                "street": "200 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 950000,
                "beds": 4,
                "full_baths": 3,
                "sqft": 2000,
                "str_nbhd_under_cap_current": 1,
                "is_private_pool": False,
                "is_private_pool_known": True,
                "property_url": "https://example.com/no-pool",
            },
        ]
    )

    scored = module.evaluate_str_fit(df, assumptions)
    assert len(scored) == 2

    pass_row = scored[scored["property_id"] == "PASS"].iloc[0]
    fail_row = scored[scored["property_id"] == "FAIL_NO_POOL"].iloc[0]

    assert bool(pass_row["str_fit_pass"]) is True
    assert pass_row["str_fit_score"] == 100
    assert bool(fail_row["str_fit_pass"]) is False
    assert bool(fail_row["eligible_pool"]) is False
    assert "Private pool requirement met" in str(fail_row["str_fit_reasons_fail"])


def test_evaluate_str_fit_applies_quality_guards():
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
                "full_baths": 2,
                "sqft": 1550,
                "str_nbhd_under_cap_current": 1,
                "is_private_pool": True,
                "is_private_pool_known": True,
                "property_url": "https://www.realtor.com/realestateandhomes-detail/470-E-Avenida-Olancha_Palm-Springs_CA_92264_M10869-68872",
            }
        ]
    )

    scored = module.evaluate_str_fit(df, assumptions)
    row = scored.iloc[0]
    assert bool(row["quality_pass"]) is False
    assert bool(row["str_fit_pass"]) is False
    assert "Manually excluded co-ownership" in str(row["quality_exclusion_reason"])


def test_unknown_private_pool_excluded_by_default():
    module = _load_module()
    assumptions = _assumptions()

    df = pd.DataFrame(
        [
            {
                "property_id": "UNKNOWN",
                "status": "FOR_SALE",
                "street": "300 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 950000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 2000,
                "str_nbhd_under_cap_current": 1,
                "is_private_pool": False,
                "is_private_pool_known": False,
                "property_url": "https://example.com/unknown",
            }
        ]
    )
    scored = module.evaluate_str_fit(df, assumptions)
    row = scored.iloc[0]
    assert bool(row["eligible_pool"]) is False
    assert bool(row["str_fit_pass"]) is False

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


def _assumptions(cap_workbook: Path) -> dict:
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
            "scope_zip_candidates": ["92258", "92262", "92263", "92264", "92201", "92203"],
        },
        "geography": {
            "enabled": True,
            "require_under_cap_zip": True,
            "cap_percentage_max": 0.20,
            "neighborhood_cap_workbook": str(cap_workbook),
            "zip_codes_column": "zip_codes",
            "primary_zip_column": "primary_zip",
            "percentage_column": "current_neighborhood_percentage",
            "fail_open_if_missing_cap_data": False,
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


def _write_cap_workbook(path: Path) -> None:
    df = pd.DataFrame(
        [
            {
                "organized_neighborhood": "Cap Eligible A",
                "zip_codes": "92262|92264",
                "primary_zip": "92262",
                "current_neighborhood_percentage": 0.10,
                "total_residential_units": 100,
            },
            {
                "organized_neighborhood": "Over Cap",
                "zip_codes": "92201",
                "primary_zip": "92201",
                "current_neighborhood_percentage": 0.25,
                "total_residential_units": 100,
            },
        ]
    )
    df.to_excel(path, index=False)


def test_unknown_private_pool_does_not_auto_fail_stage1(tmp_path: Path):
    module = _load_module()
    cap_workbook = tmp_path / "cap_by_zip.xlsx"
    _write_cap_workbook(cap_workbook)
    assumptions = _assumptions(cap_workbook)

    df = pd.DataFrame(
        [
            {
                "property_id": "UNKNOWN_POOL",
                "status": "FOR_SALE",
                "street": "100 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 950000,
                "beds": 2,
                "full_baths": 2,
                "sqft": 1800,
                "str_nbhd_under_cap_current": 1,
                "is_private_pool": False,
                "is_private_pool_known": False,
                "property_url": "https://example.com/pass",
            }
        ]
    )

    scored = module.evaluate_str_fit(df, assumptions)
    assert len(scored) == 1
    row = scored.iloc[0]
    assert bool(row["str_fit_pass"]) is True
    assert bool(row["eligible_pool"]) is False
    assert "Private pool unknown" in str(row["str_fit_reasons_fail"])


def test_str_support_remains_hard_fail(tmp_path: Path):
    module = _load_module()
    cap_workbook = tmp_path / "cap_by_zip.xlsx"
    _write_cap_workbook(cap_workbook)
    assumptions = _assumptions(cap_workbook)

    df = pd.DataFrame(
        [
            {
                "property_id": "NO_STR_SUPPORT",
                "status": "FOR_SALE",
                "street": "111 No Str Support Ln",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 650000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 1700,
                "str_nbhd_under_cap_current": 0,
                "is_private_pool": True,
                "is_private_pool_known": True,
                "property_url": "https://example.com/no-support",
            }
        ]
    )

    scored = module.evaluate_str_fit(df, assumptions)
    row = scored.iloc[0]
    assert bool(row["quality_pass"]) is True
    assert bool(row["str_fit_pass"]) is False
    assert "Neighborhood is not STR-supported under current cap" in str(row["str_fit_reasons_fail"])


def test_beds_baths_boundary_2_2(tmp_path: Path):
    module = _load_module()
    cap_workbook = tmp_path / "cap_by_zip.xlsx"
    _write_cap_workbook(cap_workbook)
    assumptions = _assumptions(cap_workbook)

    df = pd.DataFrame(
        [
            {
                "property_id": "PASS_2_2",
                "status": "FOR_SALE",
                "street": "300 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 950000,
                "beds": 2,
                "full_baths": 2,
                "sqft": 2000,
                "str_nbhd_under_cap_current": 1,
                "is_private_pool": True,
                "is_private_pool_known": True,
                "property_url": "https://example.com/pass22",
            },
            {
                "property_id": "FAIL_1_2",
                "status": "FOR_SALE",
                "street": "301 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 950000,
                "beds": 1,
                "full_baths": 2,
                "sqft": 1000,
                "str_nbhd_under_cap_current": 1,
                "is_private_pool": True,
                "is_private_pool_known": True,
                "property_url": "https://example.com/fail12",
            },
        ]
    )

    scored = module.evaluate_str_fit(df, assumptions)
    pass_row = scored[scored["property_id"] == "PASS_2_2"].iloc[0]
    fail_row = scored[scored["property_id"] == "FAIL_1_2"].iloc[0]
    assert bool(pass_row["eligible_beds_baths"]) is True
    assert bool(pass_row["str_fit_pass"]) is True
    assert bool(fail_row["eligible_beds_baths"]) is False
    assert bool(fail_row["str_fit_pass"]) is False
    assert "Beds/Baths below 2+/2+ threshold" in str(fail_row["str_fit_reasons_fail"])


def test_cap_zip_allowlist_derivation_and_reason(tmp_path: Path):
    module = _load_module()
    cap_workbook = tmp_path / "cap_by_zip.xlsx"
    _write_cap_workbook(cap_workbook)
    assumptions = _assumptions(cap_workbook)

    df = pd.DataFrame(
        [
            {
                "property_id": "ZIP_PASS",
                "status": "FOR_SALE",
                "street": "10 Cap St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 700000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 1700,
                "str_nbhd_under_cap_current": 1,
                "property_url": "https://example.com/zippass",
            },
            {
                "property_id": "ZIP_FAIL",
                "status": "FOR_SALE",
                "street": "20 Cap St",
                "city": "Indio",
                "state": "CA",
                "zip_code": "92201",
                "list_price": 700000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 1700,
                "str_nbhd_under_cap_current": 1,
                "property_url": "https://example.com/zipfail",
            },
        ]
    )
    scored = module.evaluate_str_fit(df, assumptions)
    zip_pass = scored[scored["property_id"] == "ZIP_PASS"].iloc[0]
    zip_fail = scored[scored["property_id"] == "ZIP_FAIL"].iloc[0]
    assert bool(zip_pass["eligible_geo_cap_zip"]) is True
    assert "zip_has_under_cap_neighborhood" in str(zip_pass["geo_cap_zip_reason"])
    assert bool(zip_fail["eligible_geo_cap_zip"]) is False
    assert "zip_not_in_under_cap_set" in str(zip_fail["geo_cap_zip_reason"])


def test_shortlist_flags_land_in_target_band(tmp_path: Path):
    module = _load_module()
    cap_workbook = tmp_path / "cap_by_zip.xlsx"
    _write_cap_workbook(cap_workbook)
    assumptions = _assumptions(cap_workbook)

    rows = []
    for i in range(40):
        rows.append(
            {
                "property_id": f"P{i:03d}",
                "status": "FOR_SALE",
                "street": f"{i} Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 450000 + (i * 2000),
                "beds": 3,
                "full_baths": 2,
                "sqft": 1700 + i,
                "str_nbhd_under_cap_current": 1,
                "is_private_pool": bool(i % 2),
                "is_private_pool_known": True,
                "property_url": f"https://example.com/{i}",
            }
        )
    scored = module.evaluate_str_fit(pd.DataFrame(rows), assumptions)
    eligible_count = int(scored["str_fit_pass"].fillna(False).astype(bool).sum())
    shortlist = scored[scored["is_shortlist_candidate"].fillna(False).astype(bool)].copy()

    assert eligible_count == 40
    assert 4 <= len(shortlist) <= 8
    ranks = shortlist["shortlist_rank"].dropna().astype(int).sort_values().tolist()
    assert ranks == list(range(1, len(shortlist) + 1))

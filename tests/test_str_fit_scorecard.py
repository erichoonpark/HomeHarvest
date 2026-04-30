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


def _assumptions(cap_workbook: Path) -> dict:
    return {
        "hard_gates": {
            "require_quality": True,
            "require_str_supported_neighborhood": True,
            "require_private_pool": True,
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
            "strict_neighborhood_match": False,
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
        "pool_verification": {
            "allow_high_conf_inferred_private": True,
            "high_conf_levels": ["high"],
            "min_verified_coverage_warn": 0.05,
            "fail_on_low_verified_coverage": False,
        },
        "enrichment_workflow": {
            "enabled": False,
            "listing_type": "for_sale",
            "past_days": 365,
        },
        "priority_ranking": {
            "enabled": True,
            "target_city": "Palm Springs",
            "require_for_sale_status": True,
            "require_str_fit_pass": True,
            "factor_weights": {
                "price_per_sqft": 0.40,
                "lot_size": 0.25,
                "neighborhood_support": 0.35,
            },
            "tie_break_metrics": ["coc_post_tax", "coc_pre_tax", "property_id"],
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


def test_unknown_private_pool_fails_when_private_pool_required(tmp_path: Path):
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
    row = scored.iloc[0]
    assert bool(row["str_fit_pass"]) is False
    assert bool(row["eligible_pool"]) is False
    assert "Private pool verification required" in str(row["str_fit_reasons_fail"])
    assert "Private pool unknown" in str(row["str_fit_reasons_fail"])


def test_high_conf_inferred_private_pool_can_pass_when_enabled(tmp_path: Path):
    module = _load_module()
    cap_workbook = tmp_path / "cap_by_zip.xlsx"
    _write_cap_workbook(cap_workbook)
    assumptions = _assumptions(cap_workbook)

    df = pd.DataFrame(
        [
            {
                "property_id": "HIGH_CONF_POOL",
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
                "is_private_pool_known": False,
                "pool_confidence": "high",
                "property_url": "https://example.com/pass",
            }
        ]
    )

    scored = module.evaluate_str_fit(df, assumptions)
    row = scored.iloc[0]
    assert bool(row["private_pool_verified"]) is True
    assert bool(row["eligible_pool"]) is True
    assert bool(row["str_fit_pass"]) is True


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
                "is_private_pool": True,
                "is_private_pool_known": True,
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
                "is_private_pool": True,
                "is_private_pool_known": True,
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

    assert eligible_count == 20
    assert 2 <= len(shortlist) <= 4
    ranks = shortlist["shortlist_rank"].dropna().astype(int).sort_values().tolist()
    assert ranks == list(range(1, len(shortlist) + 1))


def test_enrichment_stage_marks_queue_and_promotion(tmp_path: Path):
    module = _load_module()
    cap_workbook = tmp_path / "cap_by_zip.xlsx"
    _write_cap_workbook(cap_workbook)
    assumptions = _assumptions(cap_workbook)
    assumptions["enrichment_workflow"]["enabled"] = True

    df = pd.DataFrame(
        [
            {
                "property_id": "Q1",
                "status": "FOR_SALE",
                "street": "100 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 750000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 1800,
                "str_nbhd_under_cap_current": 1,
                "is_private_pool": False,
                "is_private_pool_known": False,
                "property_url": "https://example.com/q1",
            }
        ]
    )

    def _fake_fetch(queue_df: pd.DataFrame, _: dict) -> pd.DataFrame:
        assert list(queue_df["property_id"]) == ["Q1"]
        return pd.DataFrame(
            [
                {
                    "property_id": "Q1",
                    "is_private_pool": True,
                    "is_private_pool_known": False,
                    "pool_confidence": "high",
                    "enrichment_attempted_at": "2026-01-01T00:00:00+00:00",
                    "enrichment_source": "test",
                    "enrichment_round": 2,
                }
            ]
        )

    module._fetch_enriched_pool_rows = _fake_fetch
    scored = module.evaluate_str_fit(df, assumptions)
    row = scored.iloc[0]
    assert bool(row["pool_enrichment_needed"]) is True
    assert bool(row["pool_enrichment_attempted"]) is True
    assert row["pool_enrichment_result"] == "verified_after_enrichment"
    assert bool(row["private_pool_verified"]) is True
    assert bool(row["str_fit_pass"]) is True


def test_private_pool_inferred_from_raw_details_without_canonical_columns(tmp_path: Path):
    module = _load_module()
    cap_workbook = tmp_path / "cap_by_zip.xlsx"
    _write_cap_workbook(cap_workbook)
    assumptions = _assumptions(cap_workbook)

    df = pd.DataFrame(
        [
            {
                "property_id": "RAW_PRIVATE",
                "status": "FOR_SALE",
                "street": "400 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 980000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 2100,
                "str_nbhd_under_cap_current": 1,
                "property_url": "https://example.com/raw-private",
                "raw_details": '[{"category":"Exterior","text":["Pool private: yes"]}]',
            }
        ]
    )

    scored = module.evaluate_str_fit(df, assumptions)
    row = scored.iloc[0]
    assert bool(row["eligible_pool"]) is True
    assert bool(row["is_private_pool"]) is True
    assert bool(row["is_private_pool_known"]) is True
    assert bool(row["str_fit_pass"]) is True


def test_palm_springs_priority_ranking_is_deterministic(tmp_path: Path):
    module = _load_module()
    cap_workbook = tmp_path / "cap_by_zip.xlsx"
    _write_cap_workbook(cap_workbook)
    assumptions = _assumptions(cap_workbook)

    df = pd.DataFrame(
        [
            {
                "property_id": "PS1",
                "status": "FOR_SALE",
                "street": "1 Palm St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 900000,
                "sqft": 2000,
                "lot_sqft": 10000,
                "beds": 3,
                "full_baths": 2,
                "str_nbhd_under_cap_current": 1,
                "private_pool_verified": True,
                "is_private_pool": True,
                "is_private_pool_known": True,
                "property_url": "https://example.com/ps1",
                "coc_post_tax": 0.07,
                "coc_pre_tax": 0.09,
            },
            {
                "property_id": "PS2",
                "status": "FOR_SALE",
                "street": "2 Palm St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 850000,
                "sqft": 1900,
                "lot_sqft": 12000,
                "beds": 3,
                "full_baths": 2,
                "str_nbhd_under_cap_current": 1,
                "private_pool_verified": True,
                "is_private_pool": True,
                "is_private_pool_known": True,
                "property_url": "https://example.com/ps2",
                "coc_post_tax": 0.05,
                "coc_pre_tax": 0.07,
            },
            {
                "property_id": "INDIO1",
                "status": "FOR_SALE",
                "street": "3 Indio St",
                "city": "Indio",
                "state": "CA",
                "zip_code": "92201",
                "list_price": 700000,
                "sqft": 2100,
                "lot_sqft": 9000,
                "beds": 3,
                "full_baths": 2,
                "str_nbhd_under_cap_current": 1,
                "private_pool_verified": True,
                "is_private_pool": True,
                "is_private_pool_known": True,
                "property_url": "https://example.com/indio1",
                "coc_post_tax": 0.20,
                "coc_pre_tax": 0.22,
            },
        ]
    )
    scored = module.evaluate_str_fit(df, assumptions)
    ps = scored[scored["is_palm_springs_priority_candidate"].fillna(False).astype(bool)].copy()
    assert set(ps["property_id"].astype(str)) == {"PS1", "PS2"}
    ordered = ps.sort_values(by="priority_rank")["property_id"].astype(str).tolist()
    assert ordered == ["PS2", "PS1"]
    assert bool(scored.loc[scored["property_id"] == "INDIO1", "is_palm_springs_priority_candidate"].iloc[0]) is False


def test_priority_ranking_can_target_coachella_city_list(tmp_path: Path):
    module = _load_module()
    cap_workbook = tmp_path / "cap_by_zip.xlsx"
    _write_cap_workbook(cap_workbook)
    assumptions = _assumptions(cap_workbook)
    assumptions["priority_ranking"]["target_city"] = "Coachella Valley"
    assumptions["priority_ranking"]["target_cities"] = ["Palm Springs", "Bermuda Dunes"]
    assumptions["priority_ranking"]["region_label"] = "Coachella Valley"

    df = pd.DataFrame(
        [
            {
                "property_id": "PS_CITY",
                "status": "FOR_SALE",
                "street": "10 Palm St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 900000,
                "sqft": 2000,
                "lot_sqft": 10000,
                "beds": 3,
                "full_baths": 2,
                "str_organized_neighborhood": "Cap Eligible A",
                "str_nbhd_under_cap_current": 1,
                "private_pool_verified": True,
                "is_private_pool": True,
                "is_private_pool_known": True,
                "property_url": "https://example.com/ps_city",
                "coc_post_tax": 0.07,
                "coc_pre_tax": 0.09,
            },
            {
                "property_id": "BD_CITY",
                "status": "FOR_SALE",
                "street": "11 Dune St",
                "city": "Bermuda Dunes",
                "state": "CA",
                "zip_code": "92264",
                "list_price": 870000,
                "sqft": 1900,
                "lot_sqft": 11000,
                "beds": 3,
                "full_baths": 2,
                "str_organized_neighborhood": "Cap Eligible A",
                "str_nbhd_under_cap_current": 1,
                "private_pool_verified": True,
                "is_private_pool": True,
                "is_private_pool_known": True,
                "property_url": "https://example.com/bd_city",
                "coc_post_tax": 0.06,
                "coc_pre_tax": 0.08,
            },
        ]
    )

    scored = module.evaluate_str_fit(df, assumptions)
    candidates = scored[scored["is_palm_springs_priority_candidate"].fillna(False).astype(bool)].copy()
    assert set(candidates["property_id"].astype(str)) == {"PS_CITY", "BD_CITY"}


def test_str_support_fails_closed_when_cap_data_missing_and_strict_neighborhood_match_enabled(tmp_path: Path):
    module = _load_module()
    cap_workbook = tmp_path / "missing_cap_workbook.xlsx"
    assumptions = _assumptions(cap_workbook)
    assumptions["geography"]["fail_open_if_missing_cap_data"] = False
    assumptions["geography"]["strict_neighborhood_match"] = True

    df = pd.DataFrame(
        [
            {
                "property_id": "STRICT_FAIL",
                "status": "FOR_SALE",
                "street": "500 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 950000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 1800,
                "str_nbhd_under_cap_current": 1,
                "str_organized_neighborhood": "Cap Eligible A",
                "is_private_pool": True,
                "is_private_pool_known": True,
                "property_url": "https://example.com/strict-fail",
            }
        ]
    )

    scored = module.evaluate_str_fit(df, assumptions)
    row = scored.iloc[0]
    assert bool(row["eligible_str_supported"]) is False
    assert str(row["geo_cap_zip_reason"]) == "cap_data_unavailable_fail_closed"
    assert bool(row["str_fit_pass"]) is False
    assert "Neighborhood is not STR-supported under current cap" in str(row["str_fit_reasons_fail"])

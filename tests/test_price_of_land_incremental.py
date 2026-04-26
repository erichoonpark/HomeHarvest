from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


def _load_scrape_listings_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "examples" / "scrape_listings_core.py"
    examples_dir = str(module_path.parent)
    if examples_dir not in sys.path:
        sys.path.insert(0, examples_dir)

    spec = importlib.util.spec_from_file_location("scrape_listings_core", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_compute_previous_day_window():
    scrape_module = _load_scrape_listings_module()

    start, end = scrape_module.compute_previous_day_window(run_date=pd.Timestamp("2026-04-24").date())

    assert start.isoformat() == "2026-04-23T00:00:00-07:00"
    assert end.isoformat() == "2026-04-23T23:59:59-07:00"


def test_compute_recent_window_lookback_three_days():
    scrape_module = _load_scrape_listings_module()

    start, end = scrape_module.compute_recent_window(run_date=pd.Timestamp("2026-04-24").date(), lookback_days=3)

    assert start.isoformat() == "2026-04-21T00:00:00-07:00"
    assert end.isoformat() == "2026-04-23T23:59:59-07:00"


def test_resolve_window_from_args_override_dates():
    scrape_module = _load_scrape_listings_module()

    args = SimpleNamespace(run_date=None, date_from="2026-04-20", date_to="2026-04-21", lookback_days=3)
    start, end = scrape_module.resolve_window_from_args(args)

    assert start.isoformat() == "2026-04-20T00:00:00-07:00"
    assert end.isoformat() == "2026-04-21T23:59:59-07:00"


def test_dedupe_batch_by_property_id_deterministic_order():
    scrape_module = _load_scrape_listings_module()

    batch = pd.DataFrame(
        [
            {
                "property_id": "111",
                "status": "FOR_SALE",
                "list_date": "2026-04-20 12:00:00",
                "last_sold_date": None,
            },
            {
                "property_id": "111",
                "status": "PENDING",
                "list_date": "2026-04-21 12:00:00",
                "last_sold_date": None,
            },
            {
                "property_id": "222",
                "status": "FOR_SALE",
                "list_date": "2026-04-21 10:00:00",
                "last_sold_date": None,
            },
            {
                "property_id": "222",
                "status": "SOLD",
                "list_date": "2026-04-10 10:00:00",
                "last_sold_date": "2026-04-21 10:00:00",
            },
        ]
    )

    deduped = scrape_module.dedupe_batch_by_property_id(batch)

    assert len(deduped) == 2

    row_111 = deduped[deduped["property_id"] == "111"].iloc[0]
    row_222 = deduped[deduped["property_id"] == "222"].iloc[0]

    assert row_111["status"] == "PENDING"
    assert row_222["status"] == "SOLD"


def test_filter_new_property_rows_excludes_existing_ids():
    scrape_module = _load_scrape_listings_module()

    existing = pd.DataFrame([{"property_id": "111"}, {"property_id": "333"}])
    deduped_batch = pd.DataFrame(
        [
            {"property_id": "111", "status": "PENDING"},
            {"property_id": "222", "status": "FOR_SALE"},
        ]
    )

    new_rows = scrape_module.filter_new_property_rows(existing, deduped_batch)

    assert len(new_rows) == 1
    assert new_rows.iloc[0]["property_id"] == "222"


def test_filter_new_property_rows_bootstrap_empty_existing():
    scrape_module = _load_scrape_listings_module()

    existing = pd.DataFrame()
    deduped_batch = pd.DataFrame(
        [
            {"property_id": "111", "status": "PENDING"},
            {"property_id": "222", "status": "FOR_SALE"},
        ]
    )

    new_rows = scrape_module.filter_new_property_rows(existing, deduped_batch)

    assert len(new_rows) == 2
    assert set(new_rows["property_id"].tolist()) == {"111", "222"}


def test_summarize_incremental_batch_reports_overlap():
    scrape_module = _load_scrape_listings_module()

    existing = pd.DataFrame([{"property_id": "111"}, {"property_id": "333"}])
    fetched = pd.DataFrame(
        [
            {"property_id": "111", "status": "FOR_SALE"},
            {"property_id": "222", "status": "FOR_SALE"},
        ]
    )
    deduped = fetched.copy()
    new_rows = pd.DataFrame([{"property_id": "222", "status": "FOR_SALE"}])

    summary = scrape_module.summarize_incremental_batch(existing, fetched, deduped, new_rows)

    assert summary["fetched_rows"] == 2
    assert summary["deduped_rows"] == 2
    assert summary["existing_overlap_rows"] == 1
    assert summary["new_rows"] == 1


def test_apply_incremental_upserts_updates_status_and_appends_new():
    scrape_module = _load_scrape_listings_module()

    existing = pd.DataFrame(
        [
            {
                "property_id": "111",
                "status": "FOR_SALE",
                "street": "100 Main St",
            }
        ]
    )
    deduped_batch = pd.DataFrame(
        [
            {
                "property_id": "111",
                "status": "PENDING",
                "street": "100 Main St",
            },
            {
                "property_id": "222",
                "status": "FOR_SALE",
                "street": "200 Main St",
            },
        ]
    )

    combined, new_rows, updated_count, unchanged_count = scrape_module.apply_incremental_upserts(
        existing,
        deduped_batch,
        batch_run_at="2026-04-24T08:00:00-07:00",
        batch_window_start="2026-04-21T00:00:00-07:00",
        batch_window_end="2026-04-23T23:59:59-07:00",
    )

    assert updated_count == 1
    assert unchanged_count == 0
    assert len(new_rows) == 1
    assert len(combined) == 2

    updated_row = combined[combined["property_id"] == "111"].iloc[0]
    appended_row = combined[combined["property_id"] == "222"].iloc[0]

    assert updated_row["status"] == "PENDING"
    assert updated_row["is_status_updated_in_batch"] is True
    assert updated_row["status_previous"] == "FOR_SALE"
    assert updated_row["status_updated_to"] == "PENDING"
    assert updated_row["is_new_in_batch"] is False

    assert appended_row["status"] == "FOR_SALE"
    assert appended_row["is_new_in_batch"] is True
    assert appended_row["is_status_updated_in_batch"] is False


def test_apply_incremental_upserts_refreshes_same_status_when_fields_change():
    scrape_module = _load_scrape_listings_module()

    existing = pd.DataFrame(
        [
            {
                "property_id": "111",
                "status": "FOR_SALE",
                "street": "100 Main St",
                "list_price": 500000,
            }
        ]
    )
    deduped_batch = pd.DataFrame(
        [
            {
                "property_id": "111",
                "status": "FOR_SALE",
                "street": "100 Main St",
                "list_price": 525000,
            }
        ]
    )

    combined, new_rows, updated_count, unchanged_count = scrape_module.apply_incremental_upserts(
        existing,
        deduped_batch,
        batch_run_at="2026-04-24T08:00:00-07:00",
        batch_window_start="2026-04-21T00:00:00-07:00",
        batch_window_end="2026-04-23T23:59:59-07:00",
    )

    assert updated_count == 0
    assert unchanged_count == 0
    assert new_rows.empty

    refreshed_row = combined[combined["property_id"] == "111"].iloc[0]
    assert refreshed_row["status"] == "FOR_SALE"
    assert refreshed_row["list_price"] == 525000
    assert refreshed_row["is_status_updated_in_batch"] is False


def test_filter_home_listings_excludes_mobile_like_and_invalid_rows():
    scrape_module = _load_scrape_listings_module()

    rows = pd.DataFrame(
        [
            {
                "property_id": "ok1",
                "street": "100 Main St",
                "list_price": 450000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 1600,
                "property_url": "https://www.realtor.com/realestateandhomes-detail/100-Main-St_Palm-Springs_CA_92262_M11111-11111",
            },
            {
                "property_id": "mobile1",
                "street": "55 Desert Mobile Home Park",
                "list_price": 420000,
                "beds": 2,
                "full_baths": 2,
                "sqft": 900,
                "property_url": "https://www.realtor.com/realestateandhomes-detail/55-Desert-Mobile-Home-Park_Palm-Springs_CA_92264_M22222-22222",
            },
            {
                "property_id": "cheap1",
                "street": "200 Main St",
                "list_price": 45000,
                "beds": 2,
                "full_baths": 1,
                "sqft": 800,
                "property_url": "https://www.realtor.com/realestateandhomes-detail/200-Main-St_Palm-Springs_CA_92262_M33333-33333",
            },
            {
                "property_id": "missing_specs",
                "street": "300 Main St",
                "list_price": 510000,
                "beds": None,
                "full_baths": None,
                "sqft": None,
                "property_url": "https://www.realtor.com/realestateandhomes-detail/300-Main-St_Palm-Springs_CA_92262_M44444-44444",
            },
            {
                "property_id": "coown_variant",
                "street": "1961 S Palm Canyon Dr",
                "list_price": 265000,
                "beds": 3,
                "full_baths": 3,
                "sqft": 2728,
                "property_url": "https://www.realtor.com/realestateandhomes-detail/1961-S-Palm-Canyon-Dr-3_Palm-Springs_CA_92264_M96816-60407",
            },
        ]
    )

    filtered = scrape_module.filter_home_listings(rows)
    assert set(filtered["property_id"]) == {"ok1"}


def test_filter_home_listings_excludes_manual_co_ownership_address():
    scrape_module = _load_scrape_listings_module()

    rows = pd.DataFrame(
        [
            {
                "property_id": "1086968872",
                "street": "470 E Avenida Olancha",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92264",
                "list_price": 175000,
                "beds": 5,
                "full_baths": None,
                "sqft": 1550,
                "property_url": "https://www.realtor.com/realestateandhomes-detail/470-E-Avenida-Olancha_Palm-Springs_CA_92264_M10869-68872",
            },
            {
                "property_id": "ok2",
                "street": "101 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 450000,
                "beds": 3,
                "full_baths": 2,
                "sqft": 1600,
                "property_url": "https://www.realtor.com/realestateandhomes-detail/101-Main-St_Palm-Springs_CA_92262_M11111-22222",
            },
        ]
    )

    filtered = scrape_module.filter_home_listings(rows)
    assert set(filtered["property_id"]) == {"ok2"}


def test_enrich_and_enforce_required_baseline_fields():
    scrape_module = _load_scrape_listings_module()

    rows = pd.DataFrame(
        [
            {
                "property_id": "ok1",
                "property_url": "https://example.com/1",
                "style": "SINGLE_FAMILY",
                "street": "100 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 500000,
                "sqft": 2000,
                "lot_sqft": 6500,
                "raw_details": '[{"category":"Pool and Spa","text":["Pool Private: Yes"]}]',
            },
            {
                "property_id": "missing_lot",
                "property_url": "https://example.com/2",
                "style": "SINGLE_FAMILY",
                "street": "200 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "list_price": 600000,
                "sqft": 1800,
                "lot_sqft": None,
                "pool_features": "",
            },
        ]
    )

    out = scrape_module.enrich_and_enforce_required_baseline_fields(rows, zip_code="92262", listing_type="for_sale")
    assert set(out["property_id"]) == {"ok1"}
    kept = out.iloc[0]
    assert round(float(kept["price_per_sqft"]), 2) == 250.0
    assert bool(kept["has_pool_inferred"]) is True
    assert bool(kept["pool_available"]) is True
    assert bool(kept["is_private_pool"]) is True
    assert bool(kept["is_private_pool_known"]) is True
    assert bool(kept["private_pool_verified"]) is True


def test_extract_pool_mapping_uses_structured_details_private_yes():
    scrape_module = _load_scrape_listings_module()
    row = pd.Series(
        {
            "raw_details": '[{"category":"Pool and Spa","text":["Pool Private: Yes","Pool Features: In Ground, Private"]}]',
            "raw_tags": '["community_swimming_pool","swimming_pool"]',
            "raw_photo_tags": '[{"labels":["swimming_pool"]}]',
        }
    )

    mapped = scrape_module._extract_pool_mapping(row)
    assert mapped["pool_type"] in {"private", "both"}
    assert bool(mapped["pool_available"]) is True
    assert bool(mapped["is_private_pool"]) is True
    assert bool(mapped["is_private_pool_known"]) is True
    assert bool(mapped["private_pool_verified"]) is True
    assert mapped["pool_confidence"] == "high"


def test_extract_pool_mapping_uses_structured_details_private_no():
    scrape_module = _load_scrape_listings_module()
    row = pd.Series(
        {
            "raw_details": '[{"category":"Pool and Spa","text":["Pool Private: No","Pool Features: Community"]}]',
            "raw_tags": '["community_swimming_pool"]',
            "raw_photo_tags": "[]",
        }
    )

    mapped = scrape_module._extract_pool_mapping(row)
    assert mapped["pool_type"] in {"community", "unknown"}
    assert bool(mapped["pool_available"]) is True
    assert bool(mapped["is_private_pool"]) is False
    assert bool(mapped["is_private_pool_known"]) is True
    assert bool(mapped["private_pool_verified"]) is False
    assert mapped["pool_confidence"] == "high"


def test_extract_pool_mapping_marks_conflict_as_not_verified():
    scrape_module = _load_scrape_listings_module()
    row = pd.Series(
        {
            "raw_details": '[{"category":"Pool and Spa","text":["Pool Private: Yes","Pool Private: No"]}]',
            "raw_tags": '["swimming_pool"]',
            "raw_photo_tags": '[{"labels":["swimming_pool"]}]',
        }
    )

    mapped = scrape_module._extract_pool_mapping(row)
    assert bool(mapped["pool_conflict"]) is True
    assert bool(mapped["private_pool_verified"]) is False
    assert bool(mapped["is_private_pool_known"]) is True


def test_extract_pool_mapping_fallback_private_text_not_auto_verified():
    scrape_module = _load_scrape_listings_module()
    row = pd.Series(
        {
            "pool_features": "private pool and spa",
        }
    )

    mapped = scrape_module._extract_pool_mapping(row)
    assert bool(mapped["pool_available"]) is True
    assert bool(mapped["private_pool_verified"]) is False
    assert bool(mapped["is_private_pool_known"]) is False
    assert mapped["pool_confidence"] in {"medium", "low"}


def test_get_property_details_retains_baseline_alias_fields(monkeypatch):
    scrape_module = _load_scrape_listings_module()

    fake = pd.DataFrame(
        [
            {
                "property_url": "https://example.com/home/1",
                "property_id": "abc123",
                "style": "SINGLE_FAMILY",
                "status": "FOR_SALE",
                "street": "100 Main St",
                "city": "Palm Springs",
                "state": "CA",
                "zip_code": "92262",
                "county": "Riverside",
                "neighborhoods": "Baristo",
                "latitude": 33.8,
                "longitude": -116.5,
                "beds": 3,
                "full_baths": 2,
                "half_baths": 0,
                "sqft": 1800,
                "year_built": 1990,
                "days_on_mls": 2,
                "list_date": "2026-04-23 08:00:00",
                "last_sold_date": None,
                "list_price": 550000,
                "sold_price": None,
                "price_per_sqft": 100.0,
                "lot_sqft": 8712,
                "lot_size_sqft": 8712,
                "text": "A beautiful single-family listing.",
                "listing_description": "A beautiful single-family listing.",
                "hoa_fee": 365,
                "hoa_monthly_fee": 365,
                "raw_details": '[{"category":"Pool and Spa","text":["Pool Private: Yes"]}]',
                "raw_tags": '["swimming_pool"]',
                "raw_photo_tags": '[{"labels":["swimming_pool"]}]',
            }
        ]
    )

    monkeypatch.setattr(scrape_module, "scrape_property", lambda **kwargs: fake.copy())
    out = scrape_module.get_property_details("92262", "for_sale", past_days=30)
    assert len(out) == 1
    row = out.iloc[0]
    assert row["lot_sqft"] == 8712
    assert row["lot_size_sqft"] == 8712
    assert row["text"] == "A beautiful single-family listing."
    assert row["listing_description"] == "A beautiful single-family listing."
    assert row["hoa_fee"] == 365
    assert row["hoa_monthly_fee"] == 365
    assert bool(row["private_pool_verified"]) is True
    assert "raw_details" in out.columns
    assert "raw_tags" in out.columns
    assert "raw_photo_tags" in out.columns
    assert "pool_evidence" in out.columns
    assert "pool_signal_sources" in out.columns

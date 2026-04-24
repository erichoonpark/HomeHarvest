from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


def _load_price_of_land_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "examples" / "price_of_land.py"
    examples_dir = str(module_path.parent)
    if examples_dir not in sys.path:
        sys.path.insert(0, examples_dir)

    spec = importlib.util.spec_from_file_location("price_of_land", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_compute_previous_day_window():
    pol = _load_price_of_land_module()

    start, end = pol.compute_previous_day_window(run_date=pd.Timestamp("2026-04-24").date())

    assert start.isoformat() == "2026-04-23T00:00:00-07:00"
    assert end.isoformat() == "2026-04-23T23:59:59-07:00"


def test_compute_recent_window_lookback_three_days():
    pol = _load_price_of_land_module()

    start, end = pol.compute_recent_window(run_date=pd.Timestamp("2026-04-24").date(), lookback_days=3)

    assert start.isoformat() == "2026-04-21T00:00:00-07:00"
    assert end.isoformat() == "2026-04-23T23:59:59-07:00"


def test_resolve_window_from_args_override_dates():
    pol = _load_price_of_land_module()

    args = SimpleNamespace(run_date=None, date_from="2026-04-20", date_to="2026-04-21", lookback_days=3)
    start, end = pol.resolve_window_from_args(args)

    assert start.isoformat() == "2026-04-20T00:00:00-07:00"
    assert end.isoformat() == "2026-04-21T23:59:59-07:00"


def test_dedupe_batch_by_property_id_deterministic_order():
    pol = _load_price_of_land_module()

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

    deduped = pol.dedupe_batch_by_property_id(batch)

    assert len(deduped) == 2

    row_111 = deduped[deduped["property_id"] == "111"].iloc[0]
    row_222 = deduped[deduped["property_id"] == "222"].iloc[0]

    assert row_111["status"] == "PENDING"
    assert row_222["status"] == "SOLD"


def test_filter_new_property_rows_excludes_existing_ids():
    pol = _load_price_of_land_module()

    existing = pd.DataFrame([{"property_id": "111"}, {"property_id": "333"}])
    deduped_batch = pd.DataFrame(
        [
            {"property_id": "111", "status": "PENDING"},
            {"property_id": "222", "status": "FOR_SALE"},
        ]
    )

    new_rows = pol.filter_new_property_rows(existing, deduped_batch)

    assert len(new_rows) == 1
    assert new_rows.iloc[0]["property_id"] == "222"


def test_filter_new_property_rows_bootstrap_empty_existing():
    pol = _load_price_of_land_module()

    existing = pd.DataFrame()
    deduped_batch = pd.DataFrame(
        [
            {"property_id": "111", "status": "PENDING"},
            {"property_id": "222", "status": "FOR_SALE"},
        ]
    )

    new_rows = pol.filter_new_property_rows(existing, deduped_batch)

    assert len(new_rows) == 2
    assert set(new_rows["property_id"].tolist()) == {"111", "222"}


def test_summarize_incremental_batch_reports_overlap():
    pol = _load_price_of_land_module()

    existing = pd.DataFrame([{"property_id": "111"}, {"property_id": "333"}])
    fetched = pd.DataFrame(
        [
            {"property_id": "111", "status": "FOR_SALE"},
            {"property_id": "222", "status": "FOR_SALE"},
        ]
    )
    deduped = fetched.copy()
    new_rows = pd.DataFrame([{"property_id": "222", "status": "FOR_SALE"}])

    summary = pol.summarize_incremental_batch(existing, fetched, deduped, new_rows)

    assert summary["fetched_rows"] == 2
    assert summary["deduped_rows"] == 2
    assert summary["existing_overlap_rows"] == 1
    assert summary["new_rows"] == 1

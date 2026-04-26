from __future__ import annotations

from pathlib import Path


def test_daily_workflow_runs_full_pipeline_and_tracks_outputs():
    repo_root = Path(__file__).resolve().parents[1]
    workflow = repo_root / ".github" / "workflows" / "daily_incremental_scrape.yml"
    text = workflow.read_text(encoding="utf-8")

    assert "examples/daily_str_pipeline.py --mode incremental" in text
    assert "examples/zips/combined.csv" in text
    assert "examples/zips/combined.xlsx" in text
    assert "examples/zips/str_suitability_filter.xlsx" in text
    assert "examples/zips/coc_scorecard.xlsx" in text
    assert "examples/zips/coc_dashboard.html" in text

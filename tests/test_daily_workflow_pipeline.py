from __future__ import annotations

from pathlib import Path

import yaml


def _workflow_text_and_yaml() -> tuple[str, dict]:
    repo_root = Path(__file__).resolve().parents[1]
    workflow = repo_root / ".github" / "workflows" / "daily_incremental_scrape.yml"
    text = workflow.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    return text, data


def _workflow_on_block(workflow: dict) -> dict:
    on_block = workflow.get("on") or workflow.get(True) or workflow.get("'on'")
    assert isinstance(on_block, dict)
    return on_block


def test_daily_workflow_runs_full_pipeline_and_tracks_outputs():
    text, _ = _workflow_text_and_yaml()

    assert "examples/daily_str_pipeline.py" in text
    assert "--mode incremental" in text
    assert "examples/zips/combined.csv" in text
    assert "examples/zips/combined.xlsx" in text
    assert "examples/zips/str_suitability_filter.xlsx" in text
    assert "examples/zips/coc_scorecard.xlsx" in text
    assert "examples/zips/coc_dashboard.html" in text
    assert "examples/zips/incremental_health_report.json" in text
    assert "timeout-minutes: 45" in text
    assert "issues: write" in text
    assert '--health-report-output "$HEALTH_REPORT_PATH"' in text
    assert "Upload incremental health report" in text
    assert "Publish incremental scrape summary" in text
    assert "Check previous workflow conclusion" in text
    assert "Escalate reliability issue on consecutive failures" in text
    assert "Resolve reliability issue on recovery" in text
    assert "steps.previous_run_status.outputs.previous_failed == 'true'" in text


def test_daily_workflow_has_one_daily_cron_schedule():
    _, workflow = _workflow_text_and_yaml()
    schedule = _workflow_on_block(workflow)["schedule"]
    assert len(schedule) == 1
    assert schedule[0]["cron"] == "10 13 * * *"

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "examples" / "daily_str_pipeline.py"
    examples_dir = str(module_path.parent)
    if examples_dir not in sys.path:
        sys.path.insert(0, examples_dir)

    spec = importlib.util.spec_from_file_location("daily_str_pipeline", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_daily_pipeline_runs_four_stages(monkeypatch):
    module = _load_module()
    recorded: list[tuple[str, list[str]]] = []

    def _fake_run(label: str, cmd: list[str]) -> None:
        recorded.append((label, cmd))

    monkeypatch.setattr(module, "_run_step", _fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "daily_str_pipeline.py",
            "--mode",
            "incremental",
            "--run-date",
            "2026-04-25",
            "--top-n",
            "15",
            "--dashboard-top-n",
            "20",
        ],
    )

    module.main()

    assert [label for label, _ in recorded] == ["ingest", "str-fit", "coc", "dashboard"]
    ingest_cmd = recorded[0][1]
    assert "scrape_listings_core.py" in " ".join(ingest_cmd)
    assert "--mode" in ingest_cmd and "incremental" in ingest_cmd
    assert "--run-date" in ingest_cmd and "2026-04-25" in ingest_cmd
    assert any("str_suitability_filters.py" in " ".join(cmd) for _, cmd in recorded)
    assert any("coc_scorecard.py" in " ".join(cmd) for _, cmd in recorded)
    assert any("coc_dashboard.py" in " ".join(cmd) for _, cmd in recorded)


def test_daily_pipeline_rejects_partial_date_override(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(
        sys,
        "argv",
        ["daily_str_pipeline.py", "--mode", "incremental", "--date-from", "2026-04-01"],
    )
    try:
        module.main()
    except ValueError as exc:
        assert "--date-from and --date-to must be provided together." in str(exc)
    else:
        raise AssertionError("Expected ValueError for partial date override.")

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = PROJECT_ROOT / "examples"
ZIPS_DIR = EXAMPLES_DIR / "zips"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run daily STR pipeline: ingest -> str-fit -> coc -> dashboard")
    parser.add_argument("--mode", choices=["incremental", "full"], default="incremental")
    parser.add_argument("--run-date", help="Optional YYYY-MM-DD for incremental scrape anchoring.")
    parser.add_argument("--date-from", help="Optional ISO start datetime/date for incremental scrape.")
    parser.add_argument("--date-to", help="Optional ISO end datetime/date for incremental scrape.")
    parser.add_argument("--lookback-days", type=int, default=3, help="Incremental lookback window.")
    parser.add_argument(
        "--str-assumptions",
        default=str(EXAMPLES_DIR / "data" / "str_suitability_filters.json"),
        help="STR suitability assumptions JSON path.",
    )
    parser.add_argument(
        "--coc-assumptions",
        default=str(EXAMPLES_DIR / "data" / "coc_assumptions.json"),
        help="COC assumptions JSON path.",
    )
    parser.add_argument("--top-n", type=int, default=30, help="Top N rows for STR/COC scorecards.")
    parser.add_argument("--dashboard-top-n", type=int, default=30, help="Top N rows in dashboard widgets.")
    parser.add_argument("--homes-limit", type=int, default=200, help="Homes loaded into interactive dashboard panel.")
    parser.add_argument(
        "--allow-empty-incremental",
        action="store_true",
        help="Allow ingest step to pass when incremental scrape finds zero deduped listings.",
    )
    parser.add_argument(
        "--health-report-output",
        help="Optional path for the ingest step to write incremental health report JSON.",
    )
    return parser.parse_args()


def _run_step(label: str, cmd: list[str]) -> None:
    printable = " ".join(cmd)
    print(f"[daily-str-pipeline] {label}: {printable}")
    subprocess.run(cmd, check=True, cwd=str(PROJECT_ROOT))


def _print_ingest_health_report(path: str | None) -> None:
    if not path:
        return

    report_path = Path(path)
    if not report_path.exists():
        print(f"[daily-str-pipeline][ingest-health] missing report file at {report_path}")
        return

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    print(f"[daily-str-pipeline][ingest-health]{json.dumps(payload, sort_keys=True)}")


def main() -> None:
    args = parse_args()
    py = sys.executable

    scrape_cmd = [py, str(EXAMPLES_DIR / "scrape_listings_core.py"), "--mode", args.mode]
    if args.mode == "incremental":
        if args.run_date:
            scrape_cmd.extend(["--run-date", args.run_date])
        if args.date_from and args.date_to:
            scrape_cmd.extend(["--date-from", args.date_from, "--date-to", args.date_to])
        elif args.date_from or args.date_to:
            raise ValueError("--date-from and --date-to must be provided together.")
        scrape_cmd.extend(["--lookback-days", str(args.lookback_days)])
        if args.allow_empty_incremental:
            scrape_cmd.append("--allow-empty-incremental")
    if args.health_report_output:
        scrape_cmd.extend(["--health-report-output", args.health_report_output])

    str_cmd = [
        py,
        str(EXAMPLES_DIR / "str_suitability_filters.py"),
        "--input",
        str(ZIPS_DIR / "combined.xlsx"),
        "--output",
        str(ZIPS_DIR / "str_suitability_filter.xlsx"),
        "--assumptions",
        str(args.str_assumptions),
        "--top-n",
        str(args.top_n),
    ]

    coc_cmd = [
        py,
        str(EXAMPLES_DIR / "coc_scorecard.py"),
        "--input",
        str(ZIPS_DIR / "str_suitability_filter.xlsx"),
        "--output",
        str(ZIPS_DIR / "coc_scorecard.xlsx"),
        "--assumptions",
        str(args.coc_assumptions),
        "--top-n",
        str(args.top_n),
    ]

    dash_cmd = [
        py,
        str(EXAMPLES_DIR / "coc_dashboard.py"),
        "--input",
        str(ZIPS_DIR / "coc_scorecard.xlsx"),
        "--output",
        str(ZIPS_DIR / "coc_dashboard.html"),
        "--top-n",
        str(args.dashboard_top_n),
        "--homes-limit",
        str(args.homes_limit),
    ]

    try:
        _run_step("ingest", scrape_cmd)
    finally:
        _print_ingest_health_report(args.health_report_output)
    _run_step("str-fit", str_cmd)
    _run_step("coc", coc_cmd)
    _run_step("dashboard", dash_cmd)

    print(
        "[daily-str-pipeline] complete\n"
        f"- combined: {(ZIPS_DIR / 'combined.xlsx').resolve()}\n"
        f"- str suitability: {(ZIPS_DIR / 'str_suitability_filter.xlsx').resolve()}\n"
        f"- coc scorecard: {(ZIPS_DIR / 'coc_scorecard.xlsx').resolve()}\n"
        f"- dashboard: {(ZIPS_DIR / 'coc_dashboard.html').resolve()}"
    )


if __name__ == "__main__":
    main()

"""
Scrape STR-oriented Coachella Valley ZIP codes for single-family homes.

Modes:
- incremental (default): fetch previous-day window, append only new property_id rows
  into combined outputs.
- full: refresh per-ZIP exports and rebuild combined outputs.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Optional

import pandas as pd
from homeharvest import scrape_property

from str_enrichment import enrich_with_palm_springs_str_neighborhoods
from str_neighborhood_summary import build_neighborhood_zip_table

STR_FRIENDLY_ZIP_CODES = [
    "92258",  # North Palm Springs (Palm Springs)
    "92262",
    "92263",
    "92264",
    "92201",  # Indio
    "92202",  # Indio
    "92203",  # Indio / Bermuda Dunes postal area
]

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SUMMARY_PATH = PROJECT_ROOT / "regulation_data" / "Vacation Rental_Housing_All_Summary 4.9.26.xlsx"
CROSSWALK_PATH = SCRIPT_DIR / "data" / "palm_springs_organized_neighborhood_zips.csv"
ALIASES_PATH = SCRIPT_DIR / "data" / "palm_springs_neighborhood_aliases.json"
OUTPUT_DIR = SCRIPT_DIR / "zips"
COMBINED_XLSX_PATH = OUTPUT_DIR / "combined.xlsx"
COMBINED_CSV_PATH = OUTPUT_DIR / "combined.csv"

HOME_PROPERTY_TYPES = ["single_family"]

# (listing_type, past_days) for full mode.
LISTING_SCRAPES: tuple[tuple[str, Optional[int]], ...] = (
    ("for_sale", None),
    ("pending", 365),
    ("sold", 365),
)

LISTING_TYPES_INCREMENTAL = ("for_sale",)
LA_TIMEZONE = "America/Los_Angeles"

STATUS_PRIORITY = {
    "SOLD": 3,
    "PENDING": 2,
    "CONTINGENT": 2,
    "FOR_SALE": 1,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export STR-oriented HomeHarvest datasets")
    parser.add_argument("--mode", choices=["incremental", "full"], default="incremental")
    parser.add_argument(
        "--run-date",
        help="Anchor date (YYYY-MM-DD) used for default incremental window. Default is local today.",
    )
    parser.add_argument("--date-from", help="Optional override start datetime/date (ISO 8601).")
    parser.add_argument("--date-to", help="Optional override end datetime/date (ISO 8601).")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=3,
        help="Incremental reliability window when no explicit dates are provided (default: 3).",
    )
    return parser.parse_args()


def _normalize_property_id(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _normalize_status(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip().upper()


def compute_previous_day_window(
    *,
    run_date: date | None = None,
    tz_name: str = LA_TIMEZONE,
) -> tuple[datetime, datetime]:
    tz = ZoneInfo(tz_name)
    if run_date is None:
        run_date = datetime.now(tz).date()

    target_day = run_date - timedelta(days=1)
    window_start = datetime.combine(target_day, time(0, 0, 0), tzinfo=tz)
    window_end = datetime.combine(target_day, time(23, 59, 59), tzinfo=tz)
    return window_start, window_end


def compute_recent_window(
    *,
    run_date: date | None = None,
    lookback_days: int = 3,
    tz_name: str = LA_TIMEZONE,
) -> tuple[datetime, datetime]:
    if lookback_days < 1:
        raise ValueError("lookback_days must be >= 1.")

    tz = ZoneInfo(tz_name)
    if run_date is None:
        run_date = datetime.now(tz).date()

    end_day = run_date - timedelta(days=1)
    start_day = run_date - timedelta(days=lookback_days)
    window_start = datetime.combine(start_day, time(0, 0, 0), tzinfo=tz)
    window_end = datetime.combine(end_day, time(23, 59, 59), tzinfo=tz)
    return window_start, window_end


def _parse_cli_datetime(value: str, *, tz_name: str = LA_TIMEZONE, is_end: bool = False) -> datetime:
    tz = ZoneInfo(tz_name)
    if "T" in value:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)

    parsed_date = date.fromisoformat(value)
    parsed_time = time(23, 59, 59) if is_end else time(0, 0, 0)
    return datetime.combine(parsed_date, parsed_time, tzinfo=tz)


def resolve_window_from_args(args: argparse.Namespace) -> tuple[datetime, datetime]:
    if bool(args.date_from) != bool(args.date_to):
        raise ValueError("--date-from and --date-to must be provided together.")

    if args.date_from and args.date_to:
        start = _parse_cli_datetime(args.date_from, is_end=False)
        end = _parse_cli_datetime(args.date_to, is_end=True)
        if end < start:
            raise ValueError("--date-to must be greater than or equal to --date-from.")
        return start, end

    run_date = date.fromisoformat(args.run_date) if args.run_date else None
    lookback_days = getattr(args, "lookback_days", 3)
    return compute_recent_window(run_date=run_date, lookback_days=lookback_days)


def get_property_details(
    zip_code: str,
    listing_type: str,
    *,
    past_days: Optional[int] = 365,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> pd.DataFrame:
    scrape_kwargs: dict[str, object] = {
        "location": zip_code,
        "listing_type": listing_type,
        "property_type": HOME_PROPERTY_TYPES,
    }

    if date_from and date_to:
        scrape_kwargs["date_from"] = date_from
        scrape_kwargs["date_to"] = date_to
    else:
        scrape_kwargs["past_days"] = past_days

    properties = scrape_property(**scrape_kwargs)
    if properties.empty:
        return properties

    selected_columns = [
        "property_url",
        "property_id",
        "style",
        "status",
        "street",
        "city",
        "state",
        "zip_code",
        "county",
        "neighborhoods",
        "latitude",
        "longitude",
        "beds",
        "full_baths",
        "half_baths",
        "sqft",
        "year_built",
        "days_on_mls",
        "list_date",
        "last_sold_date",
        "list_price",
        "sold_price",
        "price_per_sqft",
        "lot_sqft",
    ]
    missing = [c for c in selected_columns if c not in properties.columns]
    if missing:
        raise RuntimeError(f"Unexpected missing columns: {missing}")
    return properties[selected_columns]


def _event_timestamp(row: pd.Series) -> pd.Timestamp:
    status = str(row.get("status", "")).upper()
    raw_date = row.get("last_sold_date") if status == "SOLD" else row.get("list_date")
    dt = pd.to_datetime(raw_date, errors="coerce", utc=True)
    return pd.Timestamp.min.tz_localize("UTC") if pd.isna(dt) else dt


def dedupe_batch_by_property_id(batch_df: pd.DataFrame) -> pd.DataFrame:
    if batch_df.empty:
        return batch_df

    df = batch_df.copy()
    df["_property_id_key"] = df["property_id"].map(_normalize_property_id)
    df = df[df["_property_id_key"] != ""]
    if df.empty:
        return df

    df["_event_ts"] = df.apply(_event_timestamp, axis=1)
    df["_status_priority"] = df["status"].map(lambda x: STATUS_PRIORITY.get(str(x).upper(), 0))

    df = df.sort_values(
        by=["_property_id_key", "_event_ts", "_status_priority"],
        ascending=[True, False, False],
        kind="mergesort",
    )

    deduped = df.drop_duplicates(subset=["_property_id_key"], keep="first").copy()
    return deduped.drop(columns=["_property_id_key", "_event_ts", "_status_priority"])


def filter_new_property_rows(existing_df: pd.DataFrame, deduped_batch_df: pd.DataFrame) -> pd.DataFrame:
    """Keep rows whose property_id does not already exist in historical combined data."""
    existing_ids = {
        _normalize_property_id(v)
        for v in existing_df.get("property_id", pd.Series(dtype="object")).tolist()
        if _normalize_property_id(v)
    }

    if deduped_batch_df.empty:
        return deduped_batch_df.copy()

    candidate_df = deduped_batch_df.copy()
    candidate_df["_property_id_key"] = candidate_df["property_id"].map(_normalize_property_id)
    return candidate_df[~candidate_df["_property_id_key"].isin(existing_ids)].drop(columns=["_property_id_key"])


def summarize_incremental_batch(
    existing_df: pd.DataFrame,
    fetched_df: pd.DataFrame,
    deduped_batch_df: pd.DataFrame,
    new_rows_df: pd.DataFrame,
    status_updated_rows: int = 0,
    unchanged_overlap_rows: int = 0,
) -> dict[str, int]:
    existing_ids = {
        _normalize_property_id(v)
        for v in existing_df.get("property_id", pd.Series(dtype="object")).tolist()
        if _normalize_property_id(v)
    }
    deduped_ids = {
        _normalize_property_id(v)
        for v in deduped_batch_df.get("property_id", pd.Series(dtype="object")).tolist()
        if _normalize_property_id(v)
    }
    overlap_count = len(deduped_ids & existing_ids)
    return {
        "fetched_rows": len(fetched_df),
        "deduped_rows": len(deduped_batch_df),
        "existing_overlap_rows": overlap_count,
        "new_rows": len(new_rows_df),
        "status_updated_rows": status_updated_rows,
        "unchanged_overlap_rows": unchanged_overlap_rows,
    }


def apply_incremental_upserts(
    existing_df: pd.DataFrame,
    deduped_batch_df: pd.DataFrame,
    *,
    batch_run_at: str,
    batch_window_start: str,
    batch_window_end: str,
) -> tuple[pd.DataFrame, pd.DataFrame, int, int]:
    """
    Upsert deduped batch into existing rows.

    - New property_id -> append as new row.
    - Existing property_id with changed status -> update existing row in place.
    - Existing property_id with same status -> leave unchanged.
    """
    combined_df = existing_df.copy()

    if deduped_batch_df.empty:
        return combined_df, deduped_batch_df.copy(), 0, 0

    if "property_id" not in combined_df.columns:
        combined_df["property_id"] = pd.NA

    index_by_property_id: dict[str, int] = {}
    for idx, value in combined_df["property_id"].items():
        property_id = _normalize_property_id(value)
        if property_id:
            # Keep last occurrence so updates target the most recent row.
            index_by_property_id[property_id] = idx

    new_rows: list[dict[str, object]] = []
    status_updated_rows = 0
    unchanged_overlap_rows = 0

    for _, incoming_row in deduped_batch_df.iterrows():
        incoming_dict = incoming_row.to_dict()
        property_id = _normalize_property_id(incoming_dict.get("property_id"))
        if not property_id:
            continue

        existing_idx = index_by_property_id.get(property_id)
        incoming_status = _normalize_status(incoming_dict.get("status"))

        if existing_idx is None:
            incoming_dict["batch_run_at"] = batch_run_at
            incoming_dict["batch_window_start"] = batch_window_start
            incoming_dict["batch_window_end"] = batch_window_end
            incoming_dict["ingest_mode"] = "incremental"
            incoming_dict["is_new_in_batch"] = True
            incoming_dict["is_status_updated_in_batch"] = False
            incoming_dict["status_previous"] = pd.NA
            incoming_dict["status_updated_to"] = incoming_status if incoming_status else pd.NA
            new_rows.append(incoming_dict)
            continue

        previous_status = (
            _normalize_status(combined_df.at[existing_idx, "status"]) if "status" in combined_df.columns else ""
        )
        if incoming_status and incoming_status != previous_status:
            # Refresh existing row with incoming listing fields.
            for col, value in incoming_dict.items():
                combined_df.at[existing_idx, col] = value

            combined_df.at[existing_idx, "batch_run_at"] = batch_run_at
            combined_df.at[existing_idx, "batch_window_start"] = batch_window_start
            combined_df.at[existing_idx, "batch_window_end"] = batch_window_end
            combined_df.at[existing_idx, "ingest_mode"] = "incremental"
            combined_df.at[existing_idx, "is_new_in_batch"] = False
            combined_df.at[existing_idx, "is_status_updated_in_batch"] = True
            combined_df.at[existing_idx, "status_previous"] = previous_status if previous_status else pd.NA
            combined_df.at[existing_idx, "status_updated_to"] = incoming_status
            status_updated_rows += 1
        else:
            unchanged_overlap_rows += 1

    new_rows_df = pd.DataFrame(new_rows)
    if not new_rows_df.empty:
        combined_df = pd.concat([combined_df, new_rows_df], ignore_index=True, sort=False)

    return combined_df, new_rows_df, status_updated_rows, unchanged_overlap_rows


def output_zip_folder(zip_code: str, frames: dict[str, pd.DataFrame]) -> None:
    zip_folder = OUTPUT_DIR / zip_code
    zip_folder.mkdir(parents=True, exist_ok=True)
    for name, df in frames.items():
        base = zip_folder / f"{zip_code}_{name}"
        df.to_csv(f"{base}.csv", index=False)
        df.to_excel(f"{base}.xlsx", index=False)


def run_full_mode() -> None:
    combined_df = pd.DataFrame()
    for zip_code in STR_FRIENDLY_ZIP_CODES:
        frames = {lt: get_property_details(zip_code, lt, past_days=pdays) for lt, pdays in LISTING_SCRAPES}
        combined_df = pd.concat([combined_df, *frames.values()], ignore_index=True)
        output_zip_folder(zip_code, frames)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    neighborhood_zip_csv = OUTPUT_DIR / "palm_springs_neighborhood_cap_by_zip.csv"
    neighborhood_zip_xlsx = OUTPUT_DIR / "palm_springs_neighborhood_cap_by_zip.xlsx"

    combined_df = enrich_with_palm_springs_str_neighborhoods(
        combined_df,
        summary_path=SUMMARY_PATH,
        crosswalk_path=CROSSWALK_PATH,
        aliases_path=ALIASES_PATH,
    )
    neighborhood_zip_df = build_neighborhood_zip_table(SUMMARY_PATH, CROSSWALK_PATH)

    combined_df.to_csv(COMBINED_CSV_PATH, index=False)
    combined_df.to_excel(COMBINED_XLSX_PATH, index=False)
    neighborhood_zip_df.to_csv(neighborhood_zip_csv, index=False)
    neighborhood_zip_df.to_excel(neighborhood_zip_xlsx, index=False)

    status_counts = combined_df["status"].value_counts().to_dict() if not combined_df.empty else {}
    print(
        f"Wrote {len(combined_df)} rows to:\n"
        f"  {COMBINED_CSV_PATH}\n"
        f"  {COMBINED_XLSX_PATH}\n"
        f"  {neighborhood_zip_csv}\n"
        f"  {neighborhood_zip_xlsx}\n"
        f"Status column counts: {status_counts}"
    )


def run_incremental_mode(args: argparse.Namespace) -> None:
    window_start, window_end = resolve_window_from_args(args)

    frames: list[pd.DataFrame] = []
    for zip_code in STR_FRIENDLY_ZIP_CODES:
        for listing_type in LISTING_TYPES_INCREMENTAL:
            df = get_property_details(
                zip_code,
                listing_type,
                date_from=window_start,
                date_to=window_end,
            )
            if not df.empty:
                frames.append(df)

    fetched_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not fetched_df.empty:
        fetched_df = enrich_with_palm_springs_str_neighborhoods(
            fetched_df,
            summary_path=SUMMARY_PATH,
            crosswalk_path=CROSSWALK_PATH,
            aliases_path=ALIASES_PATH,
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    existing_df = pd.read_excel(COMBINED_XLSX_PATH) if COMBINED_XLSX_PATH.exists() else pd.DataFrame()

    deduped_batch = dedupe_batch_by_property_id(fetched_df)

    batch_run_at = datetime.now(ZoneInfo(LA_TIMEZONE)).isoformat()
    combined_df, incremental_new_rows, status_updated_rows, unchanged_overlap_rows = apply_incremental_upserts(
        existing_df,
        deduped_batch,
        batch_run_at=batch_run_at,
        batch_window_start=window_start.isoformat(),
        batch_window_end=window_end.isoformat(),
    )
    summary = summarize_incremental_batch(
        existing_df,
        fetched_df,
        deduped_batch,
        incremental_new_rows,
        status_updated_rows=status_updated_rows,
        unchanged_overlap_rows=unchanged_overlap_rows,
    )

    combined_df.to_csv(COMBINED_CSV_PATH, index=False)
    combined_df.to_excel(COMBINED_XLSX_PATH, index=False)

    print(
        f"Incremental window: {window_start.isoformat()} -> {window_end.isoformat()}\n"
        f"Fetched rows: {summary['fetched_rows']}\n"
        f"Rows after in-batch property_id dedupe: {summary['deduped_rows']}\n"
        f"Overlap with existing property_id rows: {summary['existing_overlap_rows']}\n"
        f"New rows appended: {summary['new_rows']}\n"
        f"Existing rows updated due to status change: {summary['status_updated_rows']}\n"
        f"Existing rows unchanged (same status): {summary['unchanged_overlap_rows']}\n"
        f"Skipped existing property_id rows: {max(0, summary['existing_overlap_rows'] - summary['status_updated_rows'])}\n"
        f"Combined total rows: {len(combined_df)}\n"
        f"Wrote: {COMBINED_CSV_PATH}\n"
        f"Wrote: {COMBINED_XLSX_PATH}"
    )


def main() -> None:
    args = parse_args()
    if args.mode == "full":
        run_full_mode()
    else:
        run_incremental_mode(args)


if __name__ == "__main__":
    main()

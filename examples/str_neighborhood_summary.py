from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import pandas as pd


SUMMARY_SHEET_NAME = "Vacation Rental by Neighborhood"
NEIGHBORHOOD_CAP_DEFAULT = 0.20


@dataclass(frozen=True)
class NeighborhoodStats:
    organized_neighborhood: str
    neighborhood_key: str
    registered_vacation_rentals: int
    applications_processing: int
    current_neighborhood_percentage: float
    projected_neighborhood_percentage: float
    current_number_on_wait_list: int
    total_residential_units: int


def canonicalize_neighborhood_name(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(name).strip().lower()).strip()
    return normalized


def load_neighborhood_summary(summary_path: str | Path) -> pd.DataFrame:
    summary_path = Path(summary_path)
    if not summary_path.exists():
        raise FileNotFoundError(f"Summary workbook not found: {summary_path}")

    raw = pd.read_excel(summary_path, sheet_name=SUMMARY_SHEET_NAME, header=1)
    data = raw[raw["Organized Neighborhood"].notna()].copy()
    data["Organized Neighborhood"] = data["Organized Neighborhood"].astype(str).str.strip()
    data = data[data["Organized Neighborhood"].str.lower() != "total"].copy()

    rename_map = {
        "Registered Vacation Rentals -4.9.26": "registered_vacation_rentals",
        "Applications Processing - 4.9.26": "applications_processing",
        "Current Neighborhood Percentage": "current_neighborhood_percentage",
        "Projected Neighborhood Percentage": "projected_neighborhood_percentage",
        "Current Number on Wait List": "current_number_on_wait_list",
        "Total Residential Units": "total_residential_units",
    }
    data = data.rename(columns=rename_map)
    expected = ["Organized Neighborhood", *rename_map.values()]
    missing = [col for col in expected if col not in data.columns]
    if missing:
        raise RuntimeError(f"Workbook missing expected columns: {missing}")

    for col in (
        "registered_vacation_rentals",
        "applications_processing",
        "current_number_on_wait_list",
        "total_residential_units",
    ):
        data[col] = pd.to_numeric(data[col], errors="coerce").fillna(0).astype(int)

    for col in ("current_neighborhood_percentage", "projected_neighborhood_percentage"):
        data[col] = pd.to_numeric(data[col], errors="coerce").fillna(0.0).astype(float)

    data["neighborhood_key"] = data["Organized Neighborhood"].map(canonicalize_neighborhood_name)
    data = data.rename(columns={"Organized Neighborhood": "organized_neighborhood"})

    return data[
        [
            "organized_neighborhood",
            "neighborhood_key",
            "registered_vacation_rentals",
            "applications_processing",
            "current_neighborhood_percentage",
            "projected_neighborhood_percentage",
            "current_number_on_wait_list",
            "total_residential_units",
        ]
    ].sort_values("organized_neighborhood", ignore_index=True)


def summary_as_dataclasses(summary_df: pd.DataFrame) -> list[NeighborhoodStats]:
    return [NeighborhoodStats(**row) for row in summary_df.to_dict(orient="records")]


def build_neighborhood_zip_table(summary_path: str | Path, crosswalk_path: str | Path) -> pd.DataFrame:
    summary_df = load_neighborhood_summary(summary_path)
    crosswalk_df = pd.read_csv(crosswalk_path)
    xwalk = crosswalk_df[
        ["organized_neighborhood", "neighborhood_key", "primary_zip", "zip_codes", "source_note"]
    ].copy()
    merged = xwalk.merge(
        summary_df,
        on=["organized_neighborhood", "neighborhood_key"],
        how="left",
        validate="one_to_one",
    )
    return merged.sort_values(["primary_zip", "organized_neighborhood"], ignore_index=True)

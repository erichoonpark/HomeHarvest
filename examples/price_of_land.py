"""
Scrape STR-oriented Coachella Valley ZIP codes for single-family homes:

- sold: closed sales (past year by list/sold dates per HomeHarvest)
- pending: pending / contingent style pipeline listings
- for_sale: actively listed for sale

ZIP list favors cities where whole-home STR remains realistically obtainable (always
verify current ordinance, permit caps, and HOA rules for a specific address).

Writes per-ZIP CSV/XLSX per listing type plus combined outputs.
"""

import os
from pathlib import Path
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

HOME_PROPERTY_TYPES = ["single_family"]

# (listing_type, past_days) — sold/pending use a 1-year window; for_sale uses no date cut so
# long-on-market actives are not dropped (past_days would filter by list_date).
LISTING_SCRAPES: tuple[tuple[str, Optional[int]], ...] = (
    ("for_sale", None),
    ("pending", 365),
    ("sold", 365),
)


def get_property_details(
    zip_code: str,
    listing_type: str,
    *,
    past_days: Optional[int] = 365,
) -> pd.DataFrame:
    properties = scrape_property(
        location=zip_code,
        listing_type=listing_type,
        property_type=HOME_PROPERTY_TYPES,
        past_days=past_days,
    )
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


def output_zip_folder(zip_code: str, frames: dict[str, pd.DataFrame]) -> None:
    root_folder = os.getcwd()
    zip_folder = os.path.join(root_folder, "zips", zip_code)
    os.makedirs(zip_folder, exist_ok=True)
    for name, df in frames.items():
        base = os.path.join(zip_folder, f"{zip_code}_{name}")
        df.to_csv(f"{base}.csv", index=False)
        df.to_excel(f"{base}.xlsx", index=False)


if __name__ == "__main__":
    combined_df = pd.DataFrame()
    for zip_code in STR_FRIENDLY_ZIP_CODES:
        frames = {lt: get_property_details(zip_code, lt, past_days=pdays) for lt, pdays in LISTING_SCRAPES}
        combined_df = pd.concat([combined_df, *frames.values()], ignore_index=True)
        output_zip_folder(zip_code, frames)

    zips_dir = os.path.join(os.getcwd(), "zips")
    os.makedirs(zips_dir, exist_ok=True)
    combined_csv = os.path.join(zips_dir, "combined.csv")
    combined_xlsx = os.path.join(zips_dir, "combined.xlsx")
    neighborhood_zip_csv = os.path.join(zips_dir, "palm_springs_neighborhood_cap_by_zip.csv")
    neighborhood_zip_xlsx = os.path.join(zips_dir, "palm_springs_neighborhood_cap_by_zip.xlsx")
    combined_df = enrich_with_palm_springs_str_neighborhoods(
        combined_df,
        summary_path=SUMMARY_PATH,
        crosswalk_path=CROSSWALK_PATH,
        aliases_path=ALIASES_PATH,
    )
    neighborhood_zip_df = build_neighborhood_zip_table(SUMMARY_PATH, CROSSWALK_PATH)
    combined_df.to_csv(combined_csv, index=False)
    combined_df.to_excel(combined_xlsx, index=False)
    neighborhood_zip_df.to_csv(neighborhood_zip_csv, index=False)
    neighborhood_zip_df.to_excel(neighborhood_zip_xlsx, index=False)

    status_counts = combined_df["status"].value_counts().to_dict() if not combined_df.empty else {}
    print(
        f"Wrote {len(combined_df)} rows to:\n"
        f"  {combined_csv}\n"
        f"  {combined_xlsx}\n"
        f"  {neighborhood_zip_csv}\n"
        f"  {neighborhood_zip_xlsx}\n"
        f"Status column counts: {status_counts}"
    )

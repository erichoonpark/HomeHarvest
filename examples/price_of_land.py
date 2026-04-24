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
from typing import Optional

import pandas as pd
from homeharvest import scrape_property

# Cities still issuing (or clearly allowing) vacation-rental-style permits for many
# single-family homes — contrast with e.g. Rancho Mirage (citywide STR ban) or
# Cathedral City / La Quinta (severe limits on new non-exempt STR permits).
# Palm Springs: STR allowed with city permit and annual night caps by zone.
# Desert Hot Springs: vacation rental permit program (citywide cap, spacing rules).
STR_FRIENDLY_ZIP_CODES = [
    "92258",  # North Palm Springs (Palm Springs)
    "92262",
    "92263",
    "92264",
    "92240",  # Desert Hot Springs (core city ZCTA; verify STR rules vs county pockets)
]

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
        frames = {
            lt: get_property_details(zip_code, lt, past_days=pdays)
            for lt, pdays in LISTING_SCRAPES
        }
        combined_df = pd.concat([combined_df, *frames.values()], ignore_index=True)
        output_zip_folder(zip_code, frames)

    zips_dir = os.path.join(os.getcwd(), "zips")
    os.makedirs(zips_dir, exist_ok=True)
    combined_csv = os.path.join(zips_dir, "combined.csv")
    combined_xlsx = os.path.join(zips_dir, "combined.xlsx")
    combined_df.to_csv(combined_csv, index=False)
    combined_df.to_excel(combined_xlsx, index=False)

    status_counts = combined_df["status"].value_counts().to_dict() if not combined_df.empty else {}
    print(
        f"Wrote {len(combined_df)} rows to:\n"
        f"  {combined_csv}\n"
        f"  {combined_xlsx}\n"
        f"Status column counts: {status_counts}"
    )

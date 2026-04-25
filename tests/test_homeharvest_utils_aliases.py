from __future__ import annotations

from homeharvest.core.scrapers.models import Address, Description, Property, PropertyType
from homeharvest.utils import process_result


def test_process_result_exposes_baseline_alias_fields():
    prop = Property(
        property_url="https://example.com/home/1",
        property_id="123",
        status="FOR_SALE",
        list_price=550000,
        hoa_fee=365,
        address=Address(
            full_line="100 Main St",
            street="100 Main St",
            city="Palm Springs",
            state="CA",
            zip="92262",
        ),
        description=Description(
            style=PropertyType.SINGLE_FAMILY,
            beds=3,
            baths_full=2,
            sqft=1800,
            lot_sqft=8712,
            text="Pool and spa home with mountain views.",
        ),
    )

    df = process_result(prop)
    row = df.iloc[0]

    assert row["lot_sqft"] == 8712
    assert row["lot_size_sqft"] == 8712
    assert row["hoa_fee"] == 365
    assert row["hoa_monthly_fee"] == 365
    assert row["text"] == "Pool and spa home with mountain views."
    assert row["listing_description"] == "Pool and spa home with mountain views."

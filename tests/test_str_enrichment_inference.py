from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd


def _load_str_enrichment_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "examples" / "str_enrichment.py"
    examples_dir = str(module_path.parent)
    if examples_dir not in sys.path:
        sys.path.insert(0, examples_dir)

    spec = importlib.util.spec_from_file_location("str_enrichment", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _build_summary_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "organized_neighborhood": "Racquet Club Estates",
                "neighborhood_key": "racquet club estates",
                "registered_vacation_rentals": 10,
                "applications_processing": 2,
                "current_neighborhood_percentage": 0.12,
                "projected_neighborhood_percentage": 0.14,
                "current_number_on_wait_list": 4,
                "total_residential_units": 800,
            },
            {
                "organized_neighborhood": "Vista Norte",
                "neighborhood_key": "vista norte",
                "registered_vacation_rentals": 8,
                "applications_processing": 1,
                "current_neighborhood_percentage": 0.11,
                "projected_neighborhood_percentage": 0.13,
                "current_number_on_wait_list": 3,
                "total_residential_units": 300,
            },
        ]
    )


def test_infer_neighborhood_from_address_tokens(tmp_path: Path):
    module = _load_str_enrichment_module()

    summary_df = _build_summary_df()
    module.load_neighborhood_summary = lambda _: summary_df

    crosswalk_path = tmp_path / "crosswalk.csv"
    crosswalk_path.write_text(
        "organized_neighborhood,neighborhood_key,primary_zip,zip_codes,source_note\n"
        "Racquet Club Estates,racquet club estates,92262,92262,Test\n"
        "Vista Norte,vista norte,92262,92262,Test\n",
        encoding="utf-8",
    )

    aliases_path = tmp_path / "aliases.json"
    aliases_path.write_text(json.dumps({}), encoding="utf-8")

    props = pd.DataFrame(
        [
            {
                "street": "123 Racquet Club Dr",
                "city": "Palm Springs",
                "zip_code": "92262",
                "neighborhoods": pd.NA,
            }
        ]
    )

    enriched = module.enrich_with_palm_springs_str_neighborhoods(
        props,
        summary_path="unused.xlsx",
        crosswalk_path=crosswalk_path,
        aliases_path=aliases_path,
    )

    assert enriched.loc[0, "neighborhoods"] == "Racquet Club Estates"
    assert enriched.loc[0, "str_organized_neighborhood"] == "Racquet Club Estates"
    assert "street/address tokens" in str(enriched.loc[0, "str_nbhd_headroom_notes"]).lower()


def test_non_palm_springs_rows_fill_zip_placeholder(tmp_path: Path):
    module = _load_str_enrichment_module()

    summary_df = _build_summary_df()
    module.load_neighborhood_summary = lambda _: summary_df

    crosswalk_path = tmp_path / "crosswalk.csv"
    crosswalk_path.write_text(
        "organized_neighborhood,neighborhood_key,primary_zip,zip_codes,source_note\n"
        "Racquet Club Estates,racquet club estates,92262,92262,Test\n",
        encoding="utf-8",
    )

    aliases_path = tmp_path / "aliases.json"
    aliases_path.write_text(json.dumps({}), encoding="utf-8")

    props = pd.DataFrame(
        [
            {
                "street": "500 Example St",
                "city": "Indio",
                "zip_code": "92201",
                "neighborhoods": pd.NA,
            }
        ]
    )

    enriched = module.enrich_with_palm_springs_str_neighborhoods(
        props,
        summary_path="unused.xlsx",
        crosswalk_path=crosswalk_path,
        aliases_path=aliases_path,
    )

    assert enriched.loc[0, "neighborhoods"] == "ZIP 92201"
    assert "not applicable" in str(enriched.loc[0, "str_nbhd_headroom_notes"]).lower()

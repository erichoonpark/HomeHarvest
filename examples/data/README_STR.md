# Palm Springs STR enrichment reference data

- `palm_springs_organized_neighborhood_zips.csv`:
  - Stores a practical neighborhood-to-ZIP crosswalk used to narrow candidate matches.
  - `primary_zip` is a best-effort assignment for reporting.
  - `zip_codes` can contain multiple ZIPs (`|` delimited) when neighborhood boundaries overlap postal boundaries.

- `palm_springs_neighborhood_aliases.json`:
  - Maps common or alternate neighborhood labels to canonical workbook names.
  - Used before fuzzy matching.

## Sources and caveats

- Neighborhood labels come from the City of Palm Springs vacation-rental percentage workbook.
- Grouping logic references ONE-PS neighborhood regions (north/central/south) and is intended for
  enrichment assistance, not legal permit determination.
- ZIP boundaries do not perfectly align with organized neighborhood boundaries; always verify
  individual addresses in the city's mapping and permitting workflow.

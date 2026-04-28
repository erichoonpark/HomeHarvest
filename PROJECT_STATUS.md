# HomeHarvest Project Status

Last updated: April 28, 2026

## Purpose

HomeHarvest is a Python library focused on scraping and normalizing residential listing data from Realtor.com into MLS-like records.
This status file tracks what is complete, what is partially complete, and what remains.

## Project Instructions For Status Updates

- Update `Last updated` whenever this file changes.
- Move items between `Completed`, `In Progress`, and `Left To Do` as work lands.
- Keep each bullet concrete and verifiable.
- If a roadmap item is completed, move it to `Completed` and add a brief note of where it was implemented (file, test, or workflow).

## Completed

- Public API is established via `scrape_property()` with location, listing type, date windows, filters, sorting, pagination strategy, and output controls.
- Multiple return modes are in place: pandas, raw dictionaries, and Pydantic models.
- Model layer is strong and typed (`Property` and nested models).
- Time filtering supports `past_days`, `past_hours`, and `date_from`/`date_to` with precision handling.
- End-to-end STR example pipeline exists (`examples/daily_str_pipeline.py`).
- Dashboard generation and publish packaging exist (`examples/coc_dashboard.py`, `scripts/build_dashboard_publish.sh`, `publish/`).
- Daily automation workflow is implemented for incremental pipeline runs with health reporting and reliability escalation (`.github/workflows/daily_incremental_scrape.yml`).
- Core and pipeline tests are present across scraper behavior, STR fit, COC scoring, dashboard payloads, and workflow regression checks (`tests/`).

## In Progress / Partially Complete

- Test strategy split is partially complete.
- There are deterministic tests for many pipeline components.
- Live scrape tests still exist and are not fully isolated with marker-based tiering/cadence.

## Left To Do

### 1. Test reliability and speed

- Separate test suites into deterministic unit tests vs live integration tests with explicit markers.
- Ensure CI default path runs only deterministic tests unless integration is requested.

### 2. Scraper resilience and anti-breakage monitoring

- Add lightweight canary checks for critical fields (IDs, prices, status, dates).
- Expand parser fallback/null-hardening for unstable nested fields.
- Add compatibility notes/changelog entries when output behavior changes.

### 3. Documentation ergonomics

- Add a decision table for `past_days` vs `past_hours` vs `date_from`/`date_to`.
- Document practical guidance for `parallel=False`.
- Add offset/limit chunking recipes and timezone-aware `updated_since` examples.

### 4. Data contracts and versioning discipline

- Define stable vs best-effort fields in output schema.
- Add snapshot-style schema checks for pandas columns and Pydantic serialization.
- Standardize release notes for added/renamed/deprecated fields.

### 5. Performance observability

- Add optional scrape debug metrics (pages fetched, rows filtered client-side, total retained).
- Add benchmark scripts for representative search scenarios.
- Publish usage guidance by workload shape (broad metro search vs narrow comp search).

## Near-Term Roadmap (Next 1-2 Releases)

1. Add explicit unit/integration test separation and CI defaults for deterministic execution.
2. Publish an advanced filtering and pagination guide.
3. Add minimal scraper health/canary checks.
4. Introduce output schema contract checks.
5. Add optional scrape performance/debug telemetry.

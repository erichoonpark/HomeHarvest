# HomeHarvest Project Status (April 26, 2026)

## Current State

HomeHarvest is a Python library focused on scraping and normalizing residential listing data from Realtor.com into MLS-like records.

### What is currently working well

- **Clear public API:** `scrape_property()` exposes a broad but coherent search interface for location, listing types, date windows, filters, sorting, pagination strategy, and output format.
- **Multiple return modes:** Users can request Pandas, raw dictionaries, or typed Pydantic objects.
- **Strong typing/model layer:** The `Property` model and related nested models provide rich structure for downstream analytics or app integration.
- **Flexible temporal filtering:** The project supports `past_days`, `past_hours`, and explicit `date_from`/`date_to`, including datetime precision handling and conversion.
- **Operational examples:** The `examples/` directory includes practical scripts and sample data for STR suitability, dashboards, and scorecards, showing real workflows beyond basic scraping.
- **Test coverage breadth:** Existing tests cover core scrape flows, listing type behavior, filtering semantics, integration scorecards, and specific regressions.

## Areas Needing More Attention

### 1. Test strategy reliability and speed

Many tests call live scrape paths and therefore can be sensitive to provider behavior, network availability, and data volatility. The project would benefit from a two-tier test strategy:

- fast deterministic unit tests for query generation and parsing
- recorded/integration tests isolated by marker and run cadence

This would reduce CI flakiness and make refactoring safer.

### 2. Scraper resilience and anti-breakage monitoring

Because the core dependency is an upstream site/API surface, schema/query changes can break extraction. Priority improvements:

- lightweight canary checks for critical fields (e.g., IDs, prices, status, dates)
- parser fallbacks and stricter null-handling for optional nested blocks
- a compatibility matrix or changelog notes for behavior changes by version

### 3. Documentation ergonomics for advanced parameters

The README is comprehensive, but parameter interactions are increasingly complex (e.g., `past_days` vs `past_hours`, auto-sorting logic, pagination mode effects). Additional high-impact documentation:

- decision table for time/date filters
- “when to use `parallel=False`” guidance
- explicit offset/limit chunking recipes
- examples of timezone-aware `updated_since`

### 4. Data contracts and versioning discipline

Given the large output surface area, consumers would benefit from stronger contract guarantees:

- clear “stable vs best-effort” field labeling
- schema snapshot tests for pandas columns and pydantic serialization
- release notes that call out added/renamed/deprecated fields

### 5. Performance observability

The library offers parallel and sequential pagination, but users lack visibility into runtime tradeoffs. Consider:

- optional debug/perf telemetry (pages fetched, records kept after client-side filters)
- benchmark scripts for representative query types
- recommendations by use case (broad metro search vs narrow radius comps)

## Suggested Near-Term Roadmap (next 1–2 releases)

1. Add deterministic parser/query unit tests and mark live tests as integration.
2. Publish an “advanced filtering and pagination” guide with edge-case examples.
3. Add minimal scraping health checks to catch upstream drift early.
4. Introduce schema snapshot tests for returned columns/models.
5. Add optional debug metrics in scrape execution for operational transparency.

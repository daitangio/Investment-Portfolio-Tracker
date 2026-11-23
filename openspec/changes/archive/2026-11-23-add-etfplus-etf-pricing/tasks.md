# Tasks

## 1. Venue-aware ISIN-to-ticker resolution

- [x] 1.1 Make `resolve_isin_to_ticker` venue-aware for EUR ETF assets: prefer the Italian listing, validate the chosen candidate's Yahoo chart-meta currency against the asset currency, and reject candidates whose currency disagrees. Verify with unit tests next to the existing `test_resolve_isin_to_ticker` (mocked search/chart responses): `LU1900066033` → `CHIP.MI` (not `CHIP.SW`), and a USD-labelled-only candidate resolves to nothing.
- [x] 1.2 Add scheda-page ticker extraction: parse the alfanumerico code from the Borsa ETFPlus scheda HTML and form the `{CODE}.MI` ticker; use it as primary resolution, Yahoo search only as fallback when no scheda page exists. Verify with a unit test against a fixture snippet of the real `LU1900066033` scheda page (expects `CHIP.MI`).

## 2. ETF spot pricing by ISIN

- [x] 2.1 Add the ETF branch to the spot chain: for `asset_class == "ETF"` with ISIN symbol, try the Borsa ETFPlus scheda page (new `etf` segment on `_borsa_italiana_page`/`_borsa_italiana_spot`) before Yahoo, and confirm `_normalize_bond_price` does not divide ETF prices. Verify with unit tests: mock scheda HTML returning 81.39 for `LU1900066033` → `get_price` returns 81.39 (never 0.8139); page missing → falls back to the stored ticker path.
- [x] 2.2 Confirm the stored-Price fallback the bond spec requires covers failed ETF spot requests in the portfolio path (provider down + newest Price row exists → portfolio still values the ETF). Verify with a unit test using the fake-DB pattern from the bond tests.

## 3. History path uses the resolved ticker

- [x] 3.1 Thread an optional `{asset_class, ticker}` meta (same shape as `get_batch_prices`'s `symbol_meta`) through `get_historical_prices`, `get_chart_ohlcv` and `get_price_at_date`; when a ticker is present use it for Polygon/Yahoo lookups instead of the raw ISIN. Verify with unit tests: mocked Yahoo chart shows history requests for `LU1900066033` hit `CHIP.MI`, and an asset with no ticker still degrades to empty history without error.
- [x] 3.2 Update the callers that hold an `Asset` (portfolio engine and analytics paths, and the `/prices/{symbol}/history` router by resolving the Asset first) to pass the stored ticker as meta. Verify with a unit test at the engine level (fake asset with `polygon_ticker` set → history returned) and manually via `GET /api/v1/market-data/prices/LU1900066033/history` returning daily rows.

## 4. Daily ETF price history

- [x] 4.1 Spike: locate the official-close value in the ETF scheda EN page HTML (live probe). If no per-ETF official close exists on that page, use the last-trade price for the daily row. Deliverable: the selector decision recorded in the test fixture; verify the parsed values match the live page for `LU1900066033` and `IE00B1YZSC51` within last-trade tolerance.
- [x] 4.2 Extend the low-priority daily refresh task to select ETF/ISIN assets and append one EUR Price row per asset per day, without touching previous rows and without duplicating the same date. Verify with a unit test (fake DB session: task run appends the row; second run same date does not duplicate) and one manual run against the dev DB showing a new Price row for `LU1900066033`.

## 5. Backfill of existing ETF assets

- [x] 5.1 Add `backend/scripts/repair_etf_tickers.py` (dry-run by default, `APPLY=1` commits) plus a Makefile target, following the `repair-assets` pattern; it fills `polygon_ticker` for ETF/ISIN assets where it is NULL, using the resolver from task 1. Verify by running the dry run first: it reports `LU1900066033` → `CHIP.MI` and `IE00B1YZSC51` → `IMEU.MI`; after `APPLY=1`, the DB shows both tickers populated.
- [x] 5.2 End-to-end regression: with the backfill applied, the portfolio summary prices both ETFPLUS ETFs live in EUR (e.g. `LU1900066033` ≈ 81.39) and converts to the display currency via the FX service, no longer stalling on the import-time snapshot. Verify with a backend test covering the spec's regression requirement and a manual dashboard check.

## 6. Integration checks

- [x] 6.1 Run the full backend suite (`make test`) green, and check each scenario in `specs/etf-market-data/spec.md` maps to a test case (spot EUR no-normalization, fallback, non-ISIN unaffected, venue preference, currency-mismatch rejection, backfill, history via `CHIP.MI`, past-date price, unresolvable-degrades, refresh appends, provider-down leaves rows, regression).
- [x] 6.2 Run `openspec validate add-etfplus-etf-pricing --strict` clean and run one live smoke of the ETF spot (`rtk proxy curl :8010/api/v1/market-data/prices/LU1900066033` style check with auth) returning a fresh EUR price.

## Workflow follow-up

- After review and verified tasks, archive the change: `/openspec-archive-change`.
- Append the required WIP entry to LOG.md at the end of the implementation session (AGENTS.md convention, model + version).

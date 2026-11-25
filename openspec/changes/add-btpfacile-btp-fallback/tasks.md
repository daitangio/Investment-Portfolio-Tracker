# Tasks

## 1. Capture btpfacile fixtures

- [x] 1.1 Fetch a live btpfacile per-ISIN page (e.g. `https://btpfacile.it/it/btp/IT0005622128`) with curl, save raw HTML under `openspec/changes/add-btpfacile-btp-fallback/fixtures/`, and identify the exact HTML anchors for the quote ("prezzo di X") and the "ultima quotazione" timestamp. Verify: fixture files exist and anchors are documented in a comment.
- [x] 1.2 Capture a 404 response for a non-BTP ISIN (or confirm per-ISIN page behavior for a BOT ISIN) and save as fixture. Verify: fixture file exists.

## 2. MarketDataService: btpfacile fetch + parse methods

- [x] 2.1 Add `_BTPFACILE_BASE`, `_btpfacile_page(isin)` (None on any non-200/exception, same `_http` client and UA), `_parse_btpfacile_quote(html)` and `_parse_btpfacile_quote_date(html)` to `backend/services/market_data_service.py`. Verify: `cd backend && ../.venv/bin/python -m pytest tests/test_btpfacile.py -q` passes for the new parse tests against the fixtures.
- [x] 2.2 Add `_btpfacile_spot(isin)` (applies `_market_isin`, returns quote ÷100 via `_borsa_price_per_eur`) and `btpfacile_official_close(isin)` (returns `(price, quote_timestamp or None)`). Verify: unit tests with `FakeHttp` (same pattern as `tests/test_borsa_italiana.py`) pass.

## 3. Wire the fallback chain

- [x] 3.1 In `get_price` BOND branch and `_get_equity_price` BOND branch, try `_borsa_italiana_spot` → `_btpfacile_spot` → Yahoo/Polygon, eliminating the current duplicate Borsa fetch on the failure path. Verify: `pytest tests/test_borsa_italiana.py tests/test_btpfacile.py tests/test_etf_market_data.py -q` all pass, including a new test asserting btpfacile is NOT requested when Borsa succeeds and IS requested on 429.
- [x] 3.2 In `workers/tasks/market_data_tasks.py::_refresh_bond_prices`, on `borsa_italiana_official_close` returning None, fall back to `btpfacile_official_close(isin)` and store the Price row with `source="BTPFACILE"` (date = parsed quote timestamp when plausible, else run date at midnight UTC). Verify: a test (fake DB session, following existing worker test patterns if any, else a service-level test of the fallback function) shows a BTPFACILE row appended and deduped on re-run.

## 4. Tests and verification

- [x] 4.1 Add `backend/tests/test_btpfacile.py` covering: quote parsing (it-locale comma decimal), 404 → None, garbage HTML → None, alias resolution before lookup, ÷100 normalization, spot fallback ordering (Borsa 429 → btpfacile → Yahoo), and daily-close BTPFACILE row semantics. Verify: `cd backend && ../.venv/bin/python -m pytest tests/test_btpfacile.py -q` passes.
- [x] 4.2 Extra unit tests for `_parse_btpfacile_quote_date` date parsing specifically: absolute `DD/MM/YYYY HH:MM` form (e.g. "02/10/2026 17:29"), relative wording ("oggi ore 17:56" → today at that time), missing timestamp → None, garbage/unparseable → None, and implausible dates outside the ~2-year plausibility window → None. Verify: dedicated `test_parse_btpfacile_quote_date_*` cases in `tests/test_btpfacile.py` pass under `cd backend && ../.venv/bin/python -m pytest tests/test_btpfacile.py -q`.
- [x] 4.3 Run the full backend suite and confirm no regressions in bond/ETF pricing tests. Verify: `cd backend && ../.venv/bin/python -m pytest tests -q` (i.e. `make test`) exits 0.

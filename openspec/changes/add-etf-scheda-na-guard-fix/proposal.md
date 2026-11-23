# Proposal

## Why

ETF scheda pages on borsaitaliana.it quote "**Closing Price: N.A.**" while the market is open (verified live 2026-11-23 ~12:00 CET: IE00B1YZSC51 last 39.27 / Closing Price N.A.; LU1900066033 last 83.97 / Closing Price N.A.). `_parse_borsa_closing_price` scans forward with an unbounded `.*?` when the cell doesn't match, and picks up an unrelated numeric cell further down the page — the manual `refresh_bond_prices` run during task 3.2 of `add-bond-isin-alias-pricing` wrote garbage Price rows (19.00 for IE00B1YZSC51, 134.00 for LU1900066033; observed, deleted). The current celery-beat schedule floats (86400s from worker start), so the refresh can fire during trading hours and persist corrupt valuation rows. The same unbounded-scan pattern exists in the bond `_parse_borsa_official_close` price cell.

## What Changes

- Anchor the ETF scheda "Closing Price" parse to the label's own table cell: the value must appear in the cell that follows the `<strong>Closing Price</strong></span></td><td>` span boundary within a bounded window; a quoted cell that is "N.A." (or non-numeric) yields `None`, never a forward scan.
- Apply the same bounded-cell rule to the bond "Official Close" price cell in `_parse_borsa_official_close` (the date cell is already bounded by the `add-bond-isin-alias-pricing` rework).
- The daily refresh task then simply skips such assets for that run (existing behavior when a close is `None`) — no `Price` row, no corrupt history.
- Fixture tests for the N.A. cell (mid-session markup captured live), the populated cell (post-close markup), and a worker-level test asserting no row is appended when the scheda shows N.A.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `etf-market-data`: adds a requirement that quoted "N.A." cells must never be published as prices, with cell-bounded parsing. Note: this capability currently exists only as the un-archived delta of `add-etfplus-etf-pricing`; archiving that change before this one keeps the merged main spec clean (both are pure ADDED deltas, so either order technically merges, but ETFPlus-first is the natural sequence).

## Impact

- `backend/services/market_data_service.py` — `_parse_borsa_closing_price` (primary), `_parse_borsa_official_close` price cell (same hardening).
- `backend/tests/test_etf_market_data.py` / `backend/tests/test_borsa_italiana.py` — N.A. fixtures and regression tests.
- `LOG.md` session entry (work in progress log).
- No frontend/API/schema changes; no data repair needed (the two garbage rows were already deleted).

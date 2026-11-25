# Proposal

## Why

Borsa Italiana MOT is the sole primary price source for Italian government bonds (BTP/BOT/CCT/CTZ) held by ISIN. When borsaitaliana.it returns an error or a 429 too-many-requests response, every MOT segment fetch fails and pricing falls through to Yahoo/Polygon (or the stored Price row), losing the authoritative Italian market quote. btpfacile.it publishes live BTP quotes keyed by ISIN (`/it/btp/{ISIN}`, quote as % of nominal plus an "ultima quotazione" timestamp) and should serve as a dedicated fallback provider so bond pricing survives Borsa Italiana outages and rate limiting.

## What Changes

- Add btpfacile.it as a fallback price provider for BOND assets, tried after all Borsa Italiana MOT segments fail and before the Yahoo/Polygon fallback — for both live spot prices (`get_price` / `_get_equity_price`) and the daily official-close refresh task.
- New fetch + parse methods on `MarketDataService` for the btpfacile per-ISIN page, applying the same `_market_isin` dual-ISIN alias resolution and the same ÷100 normalization (% of nominal → EUR per EUR of nominal).
- Daily refresh stores btpfacile-derived closes as Price rows with `source="BTPFACILE"` when Borsa Italiana is unavailable.
- Non-BTP bonds (BOT/CCT/CTZ have no btpfacile page) silently skip this fallback (404 → None) and follow the existing chain unchanged.
- Tests with captured HTML fixtures, mirroring `tests/test_borsa_italiana.py`.

## Capabilities

### New Capabilities
(none — this extends an existing capability)

### Modified Capabilities
- `bond-market-data`: the provider fallback chain for BOND assets gains a btpfacile.it step between Borsa Italiana and Yahoo/Polygon, for spot prices and daily closes, with a new `BTPFACILE` Price source.

## Impact

- `backend/services/market_data_service.py`: new `_btpfacile_*` fetch/parse methods; fallback wiring in `get_price`, `_get_equity_price` (BOND branch), and `borsa_italiana_official_close` path.
- `backend/workers/tasks/market_data_tasks.py`: daily refresh falls back to btpfacile close and stores `source="BTPFACILE"` Price rows.
- `backend/tests/test_borsa_italiana.py` (or a new `test_btpfacile.py`): fixture-based tests for parsing, fallback ordering, alias resolution, and normalization.
- No API, schema, or frontend changes: `Price.source` is a free-form `String(30)` and the unique constraint is per-source, so `BTPFACILE` rows coexist with `BORSA_ITALIANA` rows.

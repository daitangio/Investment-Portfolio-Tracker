# Proposal

## Why

InvestIQ can already import trade histories (CommSec, IBKR, Kraken...) and bank statements (CBA, PayPal, Wise...), but users holding assets at Intesa Sanpaolo have no way to bring those positions in. The bank's "patrimonio" Excel export (`docs/intesa-sample/patrimonio.xlsx`) is a holdings snapshot — current positions with ISIN, quantity, average fiscal cost price and market value in EUR — not a trade list, so it does not fit the existing broker-signature importer. Without this, Intesa-held BTPs and ETFs are invisible to the portfolio engine, FX conversion and ATO tax calculations.

## What Changes

- New parser `backend/services/isp_portfolio_import.py` that reads the Intesa Sanpaolo `patrimonio.xlsx` holdings snapshot (Italian-locale text cells, multi-section layout with repeated headers, section totals, and a cash section) and normalizes each holding into an asset + opening-balance transaction.
- New router `backend/routers/isp_import.py` with an upload → preview → confirm flow, mirroring the bank-import pattern. Confirm **replaces** all previously imported snapshot rows for the account (tagged `source="INTESA_SNAPSHOT"`), so re-importing a newer snapshot never double-counts lots.
- Assets are keyed by ISIN (`Asset.symbol` = ISIN, `Asset.isin` set, `currency="EUR"`, `asset_class` = `BOND` for Italian government bonds, `ETF` otherwise). Bonds normalize price from "% of nominal" to EUR-per-EUR so `quantity × price_per_unit = market value` holds in the FIFO engine.
- Each holding becomes a `TRANSFER_IN` transaction dated at a user-picked as-of date (UI date picker, default today), with `price_per_unit` = average fiscal price (cost basis) and EUR→AUD FX enrichment via the existing `FXService` (RBA FXREUR). The cash section becomes a `DEPOSIT`.
- New BTP/bond pricing source: `MarketDataService` gains a Borsa Italiana MOT branch for `BOND` assets, fetching the per-ISIN scheda page (`borsaitaliana.it/borsa/obbligazioni/mot/{type}/scheda/{ISIN}-MOTX.html`) and parsing the server-rendered last-trade/official-close price. The snapshot's own market price is stored as a `Price` row at import as a fallback, and a daily low-priority task refreshes bond closes.
- Frontend: a separate small panel on `/dashboard/import` for Intesa Sanpaolo with a holdings-shaped preview (ISIN, quantity, cost basis, market value), as-of date picker, and account selector.

## Capabilities

### New Capabilities
- `holdings-import`: Importing portfolio holdings snapshots (positions + cash) from external institutions — parsing, snapshot-replace semantics, dedup, preview/confirm API, and the frontend panel. Starts with Intesa Sanpaolo `patrimonio.xlsx`.
- `bond-market-data`: Pricing fixed-income assets (Italian government bonds) by ISIN from Borsa Italiana MOT, with stored-`Price` fallback and daily refresh; resolving non-ASX ETF ISINs to Yahoo tickers.

### Modified Capabilities
- None. EUR currency support already exists (`currency` spec); this change consumes it but does not alter its requirements.

## Impact

- Backend: new `services/isp_portfolio_import.py`, `routers/isp_import.py` (registered in `main.py`); extension of `services/market_data_service.py` (bond branch) and `shared/assets.py` (ISIN-aware asset creation); optional `workers/tasks/` daily bond-price refresh; new tests under `backend/tests/` using the sample file in `docs/intesa-sample/`.
- Frontend: new panel in `frontend/src/app/dashboard/import/page.tsx` (or a sibling component) with date picker and holdings preview table.
- No database migration: `Asset.isin`, `Asset.asset_class` (BOND|ETF), `Transaction.source`, `import_hash`, and `Price` already exist; `String(3)` currency fields already hold "EUR".
- External dependency: best-effort scraping of borsaitaliana.it (server-rendered HTML, no auth); failures fall back to stored prices.

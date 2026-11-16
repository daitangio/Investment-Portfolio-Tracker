# Proposal

## Why

The existing Intesa Sanpaolo importer (`add-intesa-sanpaolo-import`) only handles the `patrimonio.xlsx` holdings snapshot — it creates opening-balance lots but no trade history. Users who buy/sell BTPs, bonds, and ETFs through Intesa receive per-trade "CONFERMA OPERAZIONI IN TITOLI" PDF confirmations (one trade per page, multi-page PDFs contain multiple trades). Without importing these, the FIFO portfolio engine has no cost-basis lots for Intesa trades, realized P&L is wrong, and ATO CGT calculations are incomplete. Sample PDFs are in `docs/intesa-sample/sample-transactions/`.

## What Changes

- New PDF parser `backend/services/isp_trade_import.py` that extracts text from Intesa trade-confirmation PDFs using `pypdf`, splits multi-page documents into per-"Ordine" trade blocks, and normalizes each into a BUY or SELL transaction candidate.
- New endpoints on the existing `isp_import` router: `POST /api/v1/isp-import/trades/upload` (parse + FX-enrich a PDF, return preview) and `POST /api/v1/isp-import/trades/confirm` (persist approved trades as `Transaction` rows tagged `source="INTESA_TRADE"`).
- Trade mapping: `ACQUISTO` → `BUY`, `VENDITA` → `SELL`. Bond prices are % of nominal (normalized /100 like the snapshot importer); ETF prices are per-unit. All fee-like line items (COMMISSIONI BANCA, SPESE, COSTI DI ESECUZIONE, RATEO LORDO, IMPOSTA SUL RATEO) are folded into the `fees` field with a `# folded fees here` code comment; `TOTALE` is the authoritative `net_amount`. The `Ordine` number (e.g. `INTE1020026863576693`) is the `import_hash` dedup key.
- `pypdf` added to `backend/requirements.txt`.
- New frontend panel `IspTradePanel.tsx` on `/dashboard/import` — separate from the snapshot panel — accepting one PDF at a time, showing a preview table of parsed trades (date, ISIN, description, BUY/SELL, qty, price, fees, net, AUD), with per-row selection and confirm.

## Capabilities

### New Capabilities
- `trade-import`: Importing individual trade confirmations (BUY/SELL with ISIN, quantity, price, fees, execution date) from institution PDF documents — parsing, per-trade dedup via order ID, FX enrichment, preview/confirm API, and frontend panel. Starts with Intesa Sanpaolo "CONFERMA OPERAZIONI IN TITOLI" PDFs (one trade per page, multi-trade per file).

### Modified Capabilities
- None. The `currency` spec already covers EUR; this change consumes it.

## Impact

- Backend: new `backend/services/isp_trade_import.py`; new endpoints in `backend/routers/isp_import.py`; `pypdf` added to `backend/requirements.txt`; new tests `backend/tests/test_isp_trade_import.py` using the 3 sample PDFs in `docs/intesa-sample/sample-transactions/`.
- Frontend: new `frontend/src/app/dashboard/import/IspTradePanel.tsx` rendered from `frontend/src/app/dashboard/import/page.tsx`.
- No database migration: `Transaction.source`, `import_hash`, `institution`, `raw_data`, and all BUY/SELL fields already exist.
- External dependency: `pypdf` (pure-Python PDF text extraction; the Intesa PDFs have proper text streams).

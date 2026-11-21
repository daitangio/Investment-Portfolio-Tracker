# Proposal

## Why

The existing Intesa Sanpaolo importer (`add-intesa-sanpaolo-import`) only handles the `patrimonio.xlsx` holdings snapshot — it creates opening-balance lots but no trade history. Users who buy/sell BTPs, bonds, and ETFs through Intesa receive per-trade "CONFERMA OPERAZIONI IN TITOLI" PDF confirmations (one trade per page, multi-page PDFs contain multiple trades). Without importing these, the FIFO portfolio engine has no cost-basis lots for Intesa trades, realized P&L is wrong, and ATO CGT calculations are incomplete. Sample PDFs are in `docs/intesa-sample/sample-transactions/`.

## What Changes

- New PDF parser `backend/services/isp_trade_import.py` that extracts text from Intesa trade-confirmation PDFs using `pypdf`, splits multi-page documents into per-"Ordine" trade blocks, and normalizes each into a BUY or SELL transaction candidate.
- Intesa Sanpaolo is added as a broker in the "Add Portfolio" section of `/dashboard/transactions` (the existing `BROKERS` grid + `BrokerUploadPanel`). The dropzone accepts `.pdf`; uploading a "CONFERMA OPERAZIONI IN TITOLI" PDF auto-creates (or reuses) an account with `institution_name="Intesa Sanpaolo"`, `currency="EUR"`, `type="BROKERAGE"`, then imports directly.
- Backend: `POST /api/v1/transactions/import` accepts `.pdf` and, when `broker_hint="intesa_sanpaolo"`, dispatches to `isp_trade_import` instead of `TransactionImporter`. The result is mapped to the existing `ImportResultResponse` so the broker panel's toast works unchanged. The standalone `/isp-import/trades/*` endpoints and `IspTradePanel.tsx` are removed.
- Trade mapping: `ACQUISTO` → `BUY`, `VENDITA` → `SELL`. Bond prices are % of nominal (normalized /100 like the snapshot importer); ETF prices are per-unit. All fee-like line items (COMMISSIONI BANCA, SPESE, COSTI DI ESECUZIONE, RATEO LORDO, IMPOSTA SUL RATEO) are folded into the `fees` field with a `# folded fees here` code comment; `TOTALE` is the authoritative `net_amount`. The `Ordine` number (e.g. `INTE1020026863576693`) is the `import_hash` dedup key.
- `pypdf` added to `backend/requirements.txt`.

## Capabilities

### New Capabilities
- `trade-import`: Importing individual trade confirmations (BUY/SELL with ISIN, quantity, price, fees, execution date) from institution PDF documents — parsing, per-trade dedup via order ID, FX enrichment, and integration into the broker "Add Portfolio" import flow. Starts with Intesa Sanpaolo "CONFERMA OPERAZIONI IN TITOLI" PDFs (one trade per page, multi-trade per file).

### Modified Capabilities
- None. The `currency` spec already covers EUR; this change consumes it.

## Impact

- Backend: new `backend/services/isp_trade_import.py` (parser + confirm logic, unchanged from initial implementation); `backend/routers/transactions.py` extended to accept `.pdf` with `broker_hint` dispatch to `isp_trade_import`; standalone `/isp-import/trades/*` endpoints removed from `backend/routers/isp_import.py`; `pypdf` added to `backend/requirements.txt`; tests updated in `backend/tests/test_isp_trade_import.py`.
- Frontend: `frontend/src/app/dashboard/transactions/page.tsx` gains an Intesa entry in `BROKERS[]` and `application/pdf` in the dropzone accept map; `IspTradePanel.tsx` deleted and its render removed from `frontend/src/app/dashboard/import/page.tsx`. The snapshot panel `IspImportPanel` stays on `/dashboard/import`.
- No database migration: `Transaction.source`, `import_hash`, `institution`, `raw_data`, and all BUY/SELL fields already exist.
- External dependency: `pypdf` (pure-Python PDF text extraction; the Intesa PDFs have proper text streams).

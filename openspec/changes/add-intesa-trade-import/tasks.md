# Tasks

## 1. Backend — PDF dispatch inside the broker import endpoint

- [x] 1.1 Extend `POST /api/v1/transactions/import` in `backend/routers/transactions.py`: accept `.pdf` in the extension whitelist. When `ext == "pdf"` and `broker_hint == "intesa_sanpaolo"`, call `isp_trade_import.parse_pdf(content)` then `isp_trade_import.confirm_trades(db, user_id, account_id, items, approved_hashes=all)` with FX enrichment, and wrap the result in `ImportResultResponse(total_rows=len(trades), imported=saved, duplicates=skipped, errors=0, error_details=[], transaction_ids=[], broker_detected="Intesa Sanpaolo")`. On `ValueError` from parsing, return HTTP 422. Verify: router test posts a sample PDF with broker_hint and gets `imported > 0, broker_detected == "Intesa Sanpaolo"`.
- [x] 1.2 FX enrichment inside the dispatch: `preview_trades`-style per-date EUR→AUD lookup must run before `confirm_trades` so `fx_rate_to_aud`/`net_amount_aud`/`price_per_unit_aud` are populated. Verify: persisted Transaction rows have non-null AUD fields.
- [x] 1.3 Remove the standalone `POST /api/v1/isp-import/trades/upload` and `/trades/confirm` endpoints + their schemas from `backend/routers/isp_import.py` (the snapshot upload/confirm stay). Verify: `grep -n "trades/upload\|trades/confirm" backend/routers/isp_import.py` returns nothing; backend imports cleanly.

## 2. Backend — tests

- [x] 2.1 Update `backend/tests/test_isp_trade_import.py`: parser/fee/hash/preview tests stay unchanged (they test the service module). Replace the `RouterTests` class that hit `/isp-import/trades/*` with tests hitting `transactions.import_transactions` with a `.pdf` file + `broker_hint="intesa_sanpaolo"`: 422 on non-Intesa PDF, successful import of the double PDF (2 trades), dedup on second import. Verify: `cd backend && ../.venv/bin/python -m pytest tests/test_isp_trade_import.py -q` all pass.
- [x] 2.2 Run full backend suite: `make test`. Verify: all tests pass, no regressions.

## 3. Frontend — Intesa broker card in Add Portfolio

- [x] 3.1 Add Intesa entry to `BROKERS[]` in `frontend/src/app/dashboard/transactions/page.tsx`: `{ id: "intesa_sanpaolo", label: "Intesa Sanpaolo", country: "IT", currency: "EUR", fileTypes: "PDF", instructions: [<how to download Conferma Operazioni in Titoli PDFs from Intesa app/site>] }`. Verify: `make type-check` passes.
- [x] 3.2 Add `"application/pdf": [".pdf"]` to the `accept` map in `BrokerUploadPanel`'s `useDropzone`. Verify: `make type-check` passes.
- [x] 3.3 Account auto-creation: confirm `BrokerUploadPanel.getOrCreateAccountId` creates the account with `institution_name="Intesa Sanpaolo"`, `account_type="BROKERAGE"`, `currency="EUR"` (the existing code already does this from `broker.label`/`broker.currency` — verify the ternary `broker.id === "kraken" ? "CRYPTO_EXCHANGE" : "BROKERAGE"` yields BROKERAGE for `intesa_sanpaolo`). Verify: `make type-check` passes; manual check of the code path.

## 4. Frontend — remove the old standalone panel

- [x] 4.1 Delete `frontend/src/app/dashboard/import/IspTradePanel.tsx`. Verify: file gone.
- [x] 4.2 Remove the `import IspTradePanel from "./IspTradePanel"` line and `<IspTradePanel />` render from `frontend/src/app/dashboard/import/page.tsx`. Verify: `make type-check` passes.

## 5. Final verification

- [x] 5.1 Run `make test` (backend) and `make type-check` (frontend). Verify: all green.
- [x] 5.2 Manual smoke: on /dashboard/transactions click "Add Portfolio" → select "Intesa Sanpaolo" → drop each of the 3 sample PDFs → confirm toast shows imported count and the transaction table shows the trades with EUR amounts and AUD equivalents. Verify: UI shows success toast with saved count.

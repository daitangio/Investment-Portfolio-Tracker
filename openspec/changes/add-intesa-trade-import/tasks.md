# Tasks

## 1. Backend — dependency and parser service

- [x] 1.1 Add `pypdf` to `backend/requirements.txt`. Verify: `.venv/bin/pip install pypdf` succeeds and `python -c "import pypdf"` works.
- [x] 1.2 Create `backend/services/isp_trade_import.py` with: `extract_pdf_pages(bytes) -> list[str]` (pypdf per-page text), `split_trade_blocks(pages) -> list[str]` (split on "Ordine :"), `parse_trade_block(block) -> IspTrade` (regex on labels: Ordine, ISIN, ACQUISTO/VENDITA, quantity, PREZZO, fee lines, TOTALE, execution datetime, settlement date, sede). Verify: `python -c "from services.isp_trade_import import parse_pdf; t=parse_pdf(open('docs/intesa-sample/sample-transactions/TFAMB00001_etf.pdf','rb').read()); print(t[0].isin, t[0].transaction_type, t[0].quantity, t[0].price_per_unit)"` prints `IE00B1YZSC51 BUY 25 39.64`.
- [x] 1.3 Bond vs ETF detection + price normalization in `parse_trade_block`: if sede contains MOT/HMTF/TIT.STATO or description matches BOND_PREFIX_SEGMENTS (import from `isp_portfolio_import`), divide PREZZO by 100. Verify: parsing `TFAMB00001_btp.pdf` gives price_per_unit 1.0 for PREZZO 100.000000; parsing `TFAMB00001_etf.pdf` gives 39.64 (no division).
- [x] 1.4 Fee folding: sum COMMISSIONI BANCA + SPESE + COSTI DI ESECUZIONE + RATEO LORDO + IMPOSTA SUL RATEO (with printed signs) into `fees`, marked with `# folded fees here` comment; TOTALE → net_amount. Verify: parsing `TFAMB00001_etf.pdf` gives fees=6.50, net=997.50; `TFAMB00001_double.pdf` SELL gives fees=31.74, net=4929.29.
- [x] 1.5 `import_hash` per trade: `sha256("INTESA_TRADE|{ordine_number}")` scoped per account. Verify: same PDF parsed twice gives identical hashes; different orders give different hashes.
- [x] 1.6 `preview_trades(file_bytes, existing_hashes, account_id) -> IspTradePreview`: parse + per-date FX enrich (EUR→AUD via FXService at each trade's execution date) + duplicate flags. Verify: unit test with fake FX returns correct AUD fields.

## 2. Backend — API endpoints

- [x] 2.1 Add `POST /api/v1/isp-import/trades/upload` to `backend/routers/isp_import.py`: accepts one PDF (multipart), optional account_id, returns preview (list of trades with all fields + AUD + duplicate flags). Reject non-Intesa PDFs with 422. Verify: `pytest backend/tests/test_isp_trade_import.py -q` router tests pass.
- [x] 2.2 Add `POST /api/v1/isp-import/trades/confirm` to `backend/routers/isp_import.py`: accepts account_id + approved import_hashes + trade payloads; inserts `Transaction` rows with type BUY/SELL, source="INTESA_TRADE", institution="intesa_sanpaolo", asset resolved via `get_or_create_asset_by_isin`, skips duplicates. Verify: confirm twice → second run skips all.
- [x] 2.3 Ensure `INTESA_TRADE` rows are NOT touched by snapshot confirm (only `INTESA_SNAPSHOT` rows are replaced). Verify: test that after importing trades and then confirming a snapshot, trade rows remain.

## 3. Backend — tests

- [x] 3.1 Create `backend/tests/test_isp_trade_import.py` with tests against all 3 sample PDFs: ETF buy parsing, BTP buy parsing, double PDF (2 trades: buy + sell), fee folding, bond price normalization, import_hash stability, dedup on re-import, preview FX enrichment (fake FX), router upload 422 on non-PDF, router confirm insert/skip. Verify: `cd backend && ../.venv/bin/python -m pytest tests/test_isp_trade_import.py -q` all pass.
- [x] 3.2 Run full backend test suite to check no regressions: `make test`. Verify: all tests pass.

## 4. Frontend — trade panel

- [x] 4.1 Create `frontend/src/app/dashboard/import/IspTradePanel.tsx`: account selector, single-PDF file input (accept=".pdf"), preview table (date, ISIN, description, BUY/SELL badge, qty, price, fees, net EUR, net AUD, dup flag), per-row checkboxes, confirm button → calls `/api/v1/isp-import/trades/upload` then `/trades/confirm`. Verify: `make type-check` passes (tsc --noEmit).
- [x] 4.2 Render `<IspTradePanel />` in `frontend/src/app/dashboard/import/page.tsx` below `<IspImportPanel />`. Verify: `make type-check` passes.

## 5. Final verification

- [x] 5.1 Run `make test` (backend) and `make type-check` (frontend). Verify: all green.
- [x] 5.2 Manual smoke: upload each of the 3 sample PDFs via the UI panel, confirm preview shows correct trades, confirm import, verify transactions appear. Verify: UI shows success message with saved count.

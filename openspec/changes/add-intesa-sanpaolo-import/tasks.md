# Tasks

## 1. Parser core — `backend/services/isp_portfolio_import.py`

- [x] 1.1 Implement `parse_it_number` (Italian locale: "." thousands, "," decimal, " €"/" %" suffixes, negatives) and verify with unit tests covering every numeric cell of `docs/intesa-sample/patrimonio.xlsx`
- [x] 1.2 Implement sheet walker that skips title/blank rows, repeated "Descrizione" header rows and "Totale ..." totals, and verify against the sample file: exactly 8 holdings + cash 10595.12 EUR extracted
- [x] 1.3 Implement bond-vs-ETF detection (`qty × price / 100 ≈ fiscal value` → bond; price normalized to EUR-per-EUR) and verify sample BTP row gives price_per_unit 1.01039081 while ETF row keeps 39.274983
- [x] 1.4 Emit normalized `IspHolding` dataclasses (ISIN, description, quantity, fiscal price, market price, fiscal value, market value, asset_class, bond type segment) and cash amount; verify with a test that parses the sample xlsx end-to-end (`cd backend && ../.venv/bin/python -m pytest tests/test_isp_import.py -q`)

## 2. Persistence — assets, transactions, replace semantics

- [x] 2.1 Add ISIN-aware asset resolution (symbol = ISIN, isin set, currency EUR, asset_class BOND/ETF, name from Descrizione) reusing `shared/assets.py`; verify no duplicate Asset on repeated ISIN in a fake-DB test
- [x] 2.2 Build TRANSFER_IN rows per holding (quantity, price_per_unit = fiscal price, as-of date, source = "INTESA_SNAPSHOT", import_hash) + one DEPOSIT for cash; verify row count/types against the sample file
- [x] 2.3 Implement confirm-time replace: delete existing `source="INTESA_SNAPSHOT"` rows for the account in the same transaction before insert; verify with a fake-DB test that a second confirm leaves only the new rows
- [x] 2.4 Enrich every row with EUR→AUD via `FXService.get_aud_rate` (fx_rate_to_aud, net_amount_aud, price_per_unit_aud) at the as-of date; verify consistency `net_amount × fx = net_amount_aud` in tests

## 3. Router — `backend/routers/isp_import.py` wired in `main.py`

- [x] 3.1 Implement `POST /api/v1/isp-import/upload` (multipart file + as_of + optional account_id; returns holdings preview with import_hash, FX-enriched, persists nothing); verify route is registered (`openspec`-free check: import `main.app` and assert the route exists)
- [x] 3.2 Implement `POST /api/v1/isp-import/confirm` (auth via `get_current_user`, account ownership check, replace + insert selected rows, returns saved/skipped); verify with a fake-DB test that double-confirm skips duplicates
- [x] 3.3 Reject non-Intesa files with 422; verify by uploading a CSV to the endpoint in a test

## 4. Bond market data — `market_data_service.py` + Price fallback + daily task

- [x] 4.1 Add `_borsa_italiana_spot(isin, bond_type)` (httpx + UA, MOT scheda page, regex last-trade/official-close, candidate type segments) and branch `get_price` to it for `asset_class == "BOND"`; verify with a mocked httpx response fixture for IT0005622128 returning ~99.54
- [x] 4.2 Add fallback chain for BOND assets: Borsa → Yahoo → newest `Price` row; verify holding still prices when the HTTP call raises
- [x] 4.3 Write each holding's Prezzo Mercato as a `Price` row (EUR, as-of date) at import; verify 8 Price rows after importing the sample file
- [x] 4.4 Resolve ETF ISINs to a Yahoo ticker once at import (Yahoo symbol search with UA) and store on the Asset; verify with a mocked search response
- [x] 4.5 Add low-priority Celery task `refresh_bond_prices` that appends daily official closes for BOND assets to `Price`; verify task appends one row per asset per run in a fake-DB test

## 5. Frontend panel — `frontend/src/app/dashboard/import/`

- [x] 5.1 Add an "Intesa Sanpaolo" panel component: file picker (.xlsx), as-of date input (default today), account selector, upload → preview table (ISIN, description, qty, cost basis, market value, AUD) with row checkboxes and confirm button calling `/api/v1/isp-import/upload|confirm`; verify `make type-check` (tsc --noEmit) passes
- [x] 5.2 Show saved/skipped counts and a CGT note ("lots dated as-of; CGT discount applies after 365 days") after confirm; verify via type-check and a manual render check

## 6. Integration verification

- [x] 6.1 Run full backend suite (`make test`) and confirm all tests incl. new `test_isp_import.py` pass
- [x] 6.2 Run `make type-check` and `openspec validate add-intesa-sanpaolo-import` and confirm both pass

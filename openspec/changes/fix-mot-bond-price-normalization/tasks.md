# Tasks

## 1. Backend: Normalize bond prices across all sources in MarketDataService

- [x] 1.1 Add `_normalize_bond_price(price, asset_class, symbol)` helper to `backend/services/market_data_service.py` that divides by 100 when `asset_class == "BOND"` or (symbol matches ISIN regex AND price ≥ 10). Verify with a quick Python snippet that IT0005735201 at raw 101.70 → 1.017 and IE00B1YZSC51 at 39.64 → 39.64 (unchanged).
- [x] 1.2 Apply the helper in `_get_equity_price` for the Yahoo/Polygon fallback paths (after Borsa returns None). Verify: `cd backend && ../.venv/bin/python -m pytest tests/test_borsa_italiana.py -q` passes.
- [x] 1.3 Apply the helper in `_get_batch_equity_prices` when storing results for BOND symbols. Verify batch prices for a BOND ISIN return normalized values.
- [x] 1.4 Apply the helper in `_yahoo_chart_history` and `_get_equity_history` for BOND/ISIN symbols so historical prices and charts are also normalized. Verify: `get_historical_prices("IT0005735201", ...)` returns closes ≈ 1.017, not 101.70.

## 2. Frontend: Display bond price as % of nominal (×100)

- [x] 2.1 In `frontend/src/components/portfolio/HoldingsTable.tsx`, display `h.last_price * 100` in the Price column when `h.asset_class === "BOND"`, otherwise `h.last_price`. No new API field needed. Verify: `make type-check` passes and the UI shows 101.70 for bond rows.

## 4. Tests: Regression coverage for IT0005735201

- [x] 4.1 Add regression test to `backend/tests/test_borsa_italiana.py`: Yahoo fallback for BOND ISIN IT0005735201 returning raw 101.70 → normalized 1.017. Verify: `cd backend && ../.venv/bin/python -m pytest tests/test_borsa_italiana.py -q` passes.
- [x] 4.2 Add regression test asserting market value: 3000 nominal × 1.017 = 3051, UI price = 101.70 (last_price × 100), unrealized_gain_pct ≈ 1.70%. Verify test passes.
- [x] 4.3 Add test for `_normalize_bond_price` heuristic: ETF ISIN price 39.64 unchanged, BOND ISIN price 101.70 → 1.017, BOND ISIN price 0.99 (already per-EUR) unchanged. Verify test passes.
- [x] 4.4 Run full backend test suite: `make test` passes with no regressions.

## 5. Integration verification

- [x] 5.1 Run `make type-check` — frontend type check passes.
- [x] 5.2 Run `openspec validate fix-mot-bond-price-normalization --strict` — change artifacts validate cleanly.

# Proposal

## Why

Borsa Italiana MOT bond prices are computed inconsistently across price sources. The Borsa Italiana scraping path (`_borsa_italiana_spot`, `borsa_italiana_official_close`) normalizes MOT quotes (% of nominal, e.g. 101.70) by dividing by 100 → 1.017 EUR per EUR of nominal. But when Borsa Italiana is unreachable and the system falls back to Yahoo Finance or Polygon for a bond ISIN, the raw price (e.g. 101.70) is returned without the /100 normalization. This produces market values and P/L that are 100× too large on fallback paths. Additionally, the `last_price` displayed in the UI for bonds shows the normalized value (1.02) instead of the market convention (101.70), confusing users. Concretely, IT0005735201 (a BTP imported from Intesa Sanpaolo, 3000 EUR nominal at cost 100%) shows P/L +143 EUR at a displayed price of 1.02 EUR, but the correct MOT last price is 101.70 (+1.70% vs nominal) and the correct final value is 3051 EUR.

## What Changes

- Normalize bond ISIN prices consistently across ALL price sources: Borsa Italiana spot/official-close AND Yahoo/Polygon fallbacks must all return EUR-per-EUR-of-nominal (i.e., divide raw MOT % quotes by 100), so `quantity × price = market value` always holds.
- Frontend displays `last_price × 100` for BOND rows so the UI shows the raw MOT quote (101.70) instead of the normalized price (1.02).
- Fix historical price / chart paths for bond ISINs so they also return normalized prices (divide Yahoo raw bond prices by 100), keeping period return calculations correct.
- Add regression tests with IT0005735201 asserting price ≈ 1.017 internally, displayed quote 101.70, and market value 3051 EUR for 3000 nominal.

## Capabilities

### New Capabilities
- `bond-market-data`: Pricing fixed-income assets (Italian government bonds) by ISIN from Borsa Italiana MOT and fallback providers, with consistent %→per-EUR-of-nominal normalization across ALL sources, a frontend ×100 display for bonds, and stored-Price fallback. (Introduced in `add-intesa-sanpaolo-import` but never synced to main specs; this change creates the main-spec delta and fixes the normalization bug.)

### Modified Capabilities
- None.

## Impact

- Backend: `backend/services/market_data_service.py` — apply /100 normalization to Yahoo/Polygon fallback prices for BOND/ISIN symbols in `_get_equity_price`, `_get_batch_equity_prices`, `_get_equity_history`, `_yahoo_chart_history`, `_yahoo_spot`. `backend/services/portfolio_engine.py` — display `last_price × 100` for BOND rows. `backend/routers/portfolio.py` — add `quoted_price` to `HoldingResponse`.
- Frontend: `frontend/src/lib/hooks/usePortfolio.ts` — no interface change needed. `frontend/src/components/portfolio/HoldingsTable.tsx` — display `last_price × 100` for BOND rows.
- Tests: extend `backend/tests/test_borsa_italiana.py` with regression tests for IT0005735201 and Yahoo-fallback normalization.
- No database migration needed.

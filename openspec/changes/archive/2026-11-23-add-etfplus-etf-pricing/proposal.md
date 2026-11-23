# Proposal

## Why

ETF assets imported from Intesa Sanpaolo are keyed by ISIN with EUR currency and `exchange=ETFPLUS` (e.g. `LU1900066033` Amundi MSCI Semiconductors, `IE00B1YZSC51` iShares Core MSCI Europe), but the pricing chain throws the raw ISIN at Polygon/Yahoo, which only speak tickers — so these holdings show no live price and no chart history. The existing ISIN→Yahoo-ticker resolution left both rows with `NULL polygon_ticker` and is venue-blind: today it resolves `LU1900066033` to `CHIP.SW` (the Swiss listing, whose Yahoo metadata even mislabels currency), ~27% off the fund's actual EUR price on Borsa Italiana — a silent valuation error of the same class the `fix-mot-bond-price-normalization` change just eradicated for bonds.

justETF was evaluated as an additional provider and deliberately rejected for this scope: it has no official public API (third-party wrappers and the `justetf` package rely on undocumented endpoints / session impersonation, ToS-gray and fragile), and its only marginal value is coverage of ETFs *not* listed on Borsa Italiana — a case the portfolio does not contain. Revisit if a future import contains an XETRA-only fund.

## What Changes

- **ETF spot pricing by ISIN from Borsa Italiana ETFPlus**: when an ETF asset is keyed by ISIN, fetch the ISIN-keyed scheda page (`/borsa/etf/scheda/{ISIN}.html`) before the Yahoo fallback, reusing the existing `_borsa_italiana_page` + `_parse_borsa_last_price` machinery from the MOT bond work. Prices are used as-is in EUR — **no ÷100 normalization** (that is bond-percent-of-nominal specific).
- **Venue-aware ISIN→ticker resolution**: prefer the Italian listing for ETFPLUS/EUR assets — extract the alfanumerico code from the Borsa scheda page and store `{CODE}.MI` (verified live: `CHIP.MI` and `IMEU.MI` exist on Yahoo in EUR on MIL); fall back to Yahoo ISIN search only when Borsa has no page, choosing an EUR-venue candidate rather than the first hit. Never store a venue whose Yahoo metadata currency disagrees with the asset currency.
- **Thread the resolved ticker through the history path**: `get_historical_prices`, `get_chart_ohlcv` and `get_price_at_date` currently use the raw symbol only; accept the same `{asset_class, ticker}` meta the spot path already gets, so charts, period returns and analytics work for ISIN-ETFs.
- **Backfill existing broken rows**: one-off repair (pattern of `scripts/repair_asx_assets.py` / `make repair-assets`) that populates `polygon_ticker` for ETF/ISIN assets with no ticker, using the new venue-aware resolver. Must ship after the resolver fix — running the old resolver would store `CHIP.SW` and misprice the holding.
- **Daily ETF price history**: extend the existing low-priority daily refresh task (pattern of the bond refresh) to append one official-close `Price` row per ETFPLUS ETF per day, giving stored history independent of Yahoo.

Non-goals: no justETF integration, no new provider dependencies or API keys, no changes to FX/portfolio math (EUR→AUD pivot already exists), no Asset metadata enrichment (TER/domicile).

## Capabilities

### New Capabilities
- `etf-market-data`: prices European ETFs held by ISIN from Borsa Italiana ETFPlus with Yahoo-ticker-driven history, venue-aware ISIN→ticker resolution, and daily official-close history rows.

### Modified Capabilities
<!-- None: portfolio-valuation and currency specs keep their requirements; this change
     adds provider coverage orthogonal to valuation and FX requirements. -->

## Impact

- `backend/services/market_data_service.py` — ETF segment on the Borsa spot path, venue-aware `resolve_isin_to_ticker`, ticker threading through history/chart methods.
- `backend/services/portfolio_engine.py` — pass ticker/asset_class meta through history/chart callers alongside `get_batch_prices`.
- `backend/workers/` (daily refresh task) — extend to ETFPLUS ETFs.
- `backend/scripts/` — new one-off backfill script + Makefile target (pattern exists with `repair-assets`).
- Existing imports (`isp_trade_import`, `isp_portfolio_import`) already store resolved tickers at import time; they inherit the better resolver with no changes.
- No frontend changes; no new environment variables or external dependencies.

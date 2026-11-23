# Design

## Context

See proposal.md (Why) for the motivation. Current state that shapes the approach:

- `MarketDataService` already scrapes Borsa Italiana MOT by ISIN for BOND assets: `_borsa_italiana_page(isin, segment)`, `_parse_borsa_last_price` (the `summary-value … -formatPrice` regex), a segment cache, and a daily-refresh task appending Price rows. Verified live: the same regex parses the **ETFPlus** scheda page `/borsa/etf/scheda/LU1900066033.html?lang=en` → `81.39`.
- ETF spot lives in `_get_equity_price`, which already accepts a `ticker` (stored on `Asset.polygon_ticker`, passed via `symbol_meta` from `portfolio_engine`). The history methods (`get_historical_prices`, `get_chart_ohlcv`, `get_price_at_date`) do **not** accept a ticker — raw ISIN goes to Yahoo/Polygon and fails.
- `resolve_isin_to_ticker` (used by the Intesa imports at import time) returns the **first** Yahoo search hit, venue- and currency-blind. Live probes: `LU1900066033` → `CHIP.SW` (Swiss listing, Yahoo metadata labels it USD, ~27% off the EUR price); the correct Italian listing `CHIP.MI` (EUR, MIL, 253 closes/1y) and `IMEU.MI` both exist on Yahoo.

## Goals / Non-Goals

**Goals:**
- Fresh EUR spot + daily history for ISIN-keyed ETFPLUS ETFs, using machinery that already works.
- Make stored tickers trustworthy (right venue, right currency) before any backfill uses them.
- Keep the history path as capable as the spot path for these assets.

**Non-Goals:**
- No new provider, no provider-abstraction rewrite. justETF rejected (see proposal).
- No renaming `Asset.polygon_ticker` (it stores Yahoo tickers despite its name — renaming adds churn without behavior gain).
- No FX or portfolio-engine changes (EUR quotes ride the existing AUD pivot).

## Decisions

**1. ETFPlus as an ETF segment of the existing Borsa path, not a new provider class.**
Alternative considered: a justETF client module. Borsa wins for this scope: ISIN-keyed (no ticker needed), EUR-native, same parsers, same cache/retry, already in production bond-tested. Trigger to revisit: an imported fund with no Borsa listing.

**2. Spot chain order: Borsa scheda → Yahoo via resolved ticker → (stock fallbacks as today).**
The Borsa attempt is gated on `asset_class == "ETF"` + ISIN symbol (mirror of the existing BOND gate). ETF prices skip `_borsa_price_per_eur` (÷100 is nominal-percent, bond-only) — `_normalize_bond_price` already guards on `asset_class == "BOND"`, so no change needed there.

**3. Resolution: scheda-page ticker first, currency-validated Yahoo search second.**
The scheda page embeds the alfanumerico code (`CHIP` provably present in LU1900066033's page) → store `{CODE}.MI`. Page-ticker validation is best-effort: Yahoo chart-meta validation runs when reachable, but under Yahoo rate limiting (429s seen live from the container) the page ticker is stored anyway — the scheda page *is* the Milan listing in EUR; only a concrete metadata mismatch blocks it. Search-path candidates are strictly validated: pick the first whose venue suffix matches the asset currency (Milan preferred) and whose Yahoo chart-meta currency agrees; never persist a mismatched candidate. Resolution runs at import time and in the backfill only — not per spot request.

**4. History path gets the same meta the spot path has.**
Thread an optional `{asset_class, ticker}` meta argument through `get_historical_prices`, `get_chart_ohlcv` and `get_price_at_date` (same shape as `get_batch_prices`'s `symbol_meta`). Callers in `portfolio_engine`/`analytics` pass `Asset.polygon_ticker`. Cache keys stay keyed by asset symbol.

**5. Backfill as a dry-run-by-default repair script** (`backend/scripts/`, `make` target, `APPLY=1` to commit — the `repair-assets` pattern). It must run *after* the resolver fix; sequencing covered in Migration.

**6. Extend the existing bond daily-refresh task to ETFs** rather than adding a second task: select ETF/ISIN assets, fetch official close, append one EUR Price row per asset per day.

## Risks / Trade-offs

- [Borsa HTML layout changes] → parsers already isolated + spot falls back to the Yahoo `.MI` ticker, which this change guarantees exists for these assets; daily rows are independent history.
- [Scheda official-close selector for ETFs differs from the MOT bond page] → the refresh task keeps working for bonds regardless; ETF close parsing is a tasks-level spike with a last-trade fallback.
- [Fund priced on multiple EUR venues (MIL vs XETRA) can differ by a few bps] → same fund NAV, valuation impact negligible; the asset currency stays EUR either way.
- [Yahoo search endpoint drift] → only exercised at import/backfill time; stored ticker persists; Borsa-by-ISIN pricing never depends on it.

## Migration Plan

1. Ship market-data changes (spot path, resolver, history threading, refresh extension).
2. Run repair script in dry-run, inspect the two expected rows (`LU1900066033` → `CHIP.MI`, `IE00B1YZSC51` → `IMEU.MI`), then `APPLY=1`.
3. Celery beat picks up the extended refresh on the next cycle; no config changes.
Rollback: revert reverts the chain to today's behavior; stored tickers are inert if the new code is absent (the old spot path never read them for ISIN symbols).

## Open Questions

- ~~Exact selector for official close on the ETF scheda EN page~~ — resolved: the EN scheda page has no "Official Close" block; it carries a "Closing Price" row (verified equal to the last-trade value on live pages). The daily refresh parses `Closing Price` with last-trade as fallback; the separate Official List page is discarded (it served undated stale data, e.g. 92.07 vs live 81.39).
- Whether the repair script should also verify stored tickers of already-resolved ETF assets or only NULL rows (default: NULL rows only).

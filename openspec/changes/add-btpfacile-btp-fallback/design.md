# Design

## Context

Bond pricing lives in `backend/services/market_data_service.py`. The current chain for a BOND/ISIN symbol is: `_borsa_italiana_spot()` tries every MOT path segment (`_borsa_italiana_page` returns `None` on any non-200 — 404, 429, 5xx — or exception), then `_get_equity_price()` falls back to Polygon → Yahoo; the portfolio engine finally falls back to the newest stored `Price` row (`portfolio_engine.py` ~line 597). The daily refresh (`workers/tasks/market_data_tasks.py::_refresh_bond_prices`) uses `borsa_italiana_official_close()` and writes `Price` rows with `source="BORSA_ITALIANA"`. See proposal.md for why a fallback is needed.

btpfacile.it exposes per-ISIN pages at `https://btpfacile.it/it/btp/{ISIN}` carrying the live quote as % of nominal ("prezzo di 76,77") and an "ultima quotazione del 02/10/2026 17:29" timestamp, plus a list page (`/it/btp-rendimenti-netti-in-tempo-reale`) with an ISIN → "Ultimo" quote table. Quotes use the same % -of-nominal convention as MOT, so the existing ÷100 normalization applies unchanged.

## Goals / Non-Goals

**Goals:**
- Insert btpfacile.it between Borsa Italiana and Yahoo/Polygon in the BOND chain, for spot prices and the daily close refresh.
- Keep behavior identical when Borsa Italiana works (btpfacile is never contacted).
- Tolerate any btpfacile failure silently (404 for non-BTP ISINs included).

**Non-Goals:**
- No btpfacile support for BOT/CCT/CTZ (no pages there; they 404 and fall through).
- No historical OHLCV from btpfacile (charts stay on Yahoo/Polygon).
- No frontend, API, or DB schema changes (`Price.source` is free-form `String(30)`; uniqueness is per `(asset_id, price_date, price_type, source)`).

## Decisions

1. **Per-ISIN page as the fetch target, not the list page.** One small request per bond instead of downloading/parsing a huge multi-hundred-row table per lookup. The list page remains a possible secondary parse strategy if per-ISIN markup proves unstable. Consequence: the exact HTML markers for the quote and the "ultima quotazione" timestamp must be captured from a live page during implementation and pinned as test fixtures (same approach as the existing BORSA_HTML fixtures).

2. **Fallback triggers on any Borsa failure, not only 429.** `_borsa_italiana_page` already collapses 404/429/5xx/exception into `None`, so "all segments returned None" is the single trigger condition. Distinguishing error classes would add complexity without changing behavior: btpfacile is cheap and tried once per miss.

3. **Reuse `_market_isin` alias resolution before the btpfacile lookup.** btpfacile lists market ISINs; dual-ISIN retail BTPs (placement ISIN in custody) must be mapped exactly like the Borsa path. The returned price stays attributed to the placement-ISIN asset.

4. **Reuse `_borsa_price_per_eur` (÷100) for normalization.** Same % -of-nominal convention; keeps `quantity(nominal) × price = market value` consistent across BORSA_ITALIANA, BTPFACILE, Yahoo, and stored rows.

5. **New methods rather than overloading the `_borsa_italiana_*` names.** `_btpfacile_page(isin)`, `_btpfacile_spot(isin)`, `_btpfacile_close(isin)` mirror the Borsa methods (same `_http` client, same UA header, `None` on any failure). Wiring: in `get_price`'s BOND branch and in `_get_equity_price`'s BOND branch, try `_borsa_italiana_spot` → `_btpfacile_spot` → Yahoo/Polygon. This also removes the current double Borsa fetch on the failure path (`get_price` calls `_borsa_italiana_spot`, then `_get_equity_price` calls it again) by having each call site run the chain once.

6. **Daily refresh: fall back inside the close path.** `_refresh_bond_prices` calls `borsa_italiana_official_close`; on `None` it tries `_btpfacile_close`, which returns (price, quote-timestamp) parsed from the per-ISIN page, and stores the row with `source="BTPFACILE"`. Date = parsed "ultima quotazione" timestamp when plausible (reuse the same ~2-year plausibility window idea as `_parse_borsa_close_date`), else the run date (midnight UTC, like the ETF branch). The existing per-source dedup check means re-runs don't duplicate.

7. **No negative caching.** Borsa failures aren't negatively cached today; keep symmetric behavior. The 60s Redis spot cache in `get_price` already prevents hammering within a minute once any price is found.

## Risks / Trade-offs

- [btpfacile markup changes / page structure differs from search snippets] → pin captured HTML as fixtures in tests; parse with anchored regexes and treat unparseable as `None` (falls through to Yahoo).
- [btpfacile rate-limits us too] → single request per ISIN per spot call, 60s Redis cache upstream; failure degrades to the pre-existing chain, never worse than today.
- [Quote timestamp missing or implausible] → fall back to run date for the Price row, mirroring the ETF branch behavior.
- [Stale btpfacile quote during Borsa outage] → acceptable: it is a fallback, and the stored-Price-row fallback still exists one level deeper.

## Migration Plan

No data migration. Deploy is a code-only change; rollback = revert the commit. Existing `BORSA_ITALIANA` Price rows are untouched; `BTPFACILE` rows only appear when Borsa fails during the daily refresh.

## Open Questions

- Exact HTML anchors on the btpfacile per-ISIN page (quote + timestamp) — to be captured live during implementation and pinned as fixtures.
- Whether btpfacile lists any dual-ISIN placement ISINs directly — if so the alias map still applies first, which is the safe order regardless.

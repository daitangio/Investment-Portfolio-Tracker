# Design

## Context

The Borsa Italiana provider (`backend/services/market_data_service.py`) already prices BOND assets by ISIN against the MOT scheda pages (`borsaitaliana.it/borsa/obbligazioni/mot/{type}/scheda/{ISIN}-MOTX.html`) with last-trade/official-close parsers and a %→per-EUR normalization, and the daily worker task `refresh_bond_prices` (`backend/workers/tasks/market_data_tasks.py`) appends official-close `Price` rows. Dual-ISIN retail bonds (placement ISIN in custody vs market ISIN quoted on MOT) and the YY/MM/DD close-date cell were verified live on 2026-11-23:

- Custody → market pairs (definitive ISINs announced by MEF at placement close, quoted on MOT):
  - `IT0005713539 → IT0005713547` BTP Italia Sì 23GN31 (scheda "Btp Italia Si' Jun31 Eur", last 100.30 vs HB 100.30)
  - `IT0005634792 → IT0005634800` BTP Più 25FB33 (scheda "Btp Piu' Sc Fb33 Eur", last 95.56 vs HB 95.49)
  - `IT0005696320 → IT0005696338` BTP Valore 10MZ32 (scheda "Btp Valore Sc Mar32 Eur", last 96.24 vs HB 96.15)
- The placement ISINs have **no** scheda page (soft-404 "Cerca Strumento" on every segment) and no Yahoo/Polygon quote; Euronext Live (`live.euronext.com`) serves bond quotes through an encrypted JS ajax (`{"ct": ...}`) and lists only 1 of the 3 placement ISINs — an Euronext provider was investigated and rejected.
- Close-date cells print YY/MM/DD (`26/11/20` = 2026-11-20 appears alongside the long form `20/11/2026` elsewhere on the same page); the current `_parse_borsa_official_close` regex reads it as DD/MM/YY → 2020-11-26.

## Goals / Non-Goals

**Goals:**
- Fresh MOT quotes for the three dual-ISIN holdings with the existing scheda pipeline and parsers.
- Correctly dated daily close rows so dedup and bond history work.
- Minimal surface: no DB schema change, no API change, placement ISIN stays the asset key everywhere.

**Non-Goals:**
- Reverse-engineering live.euronext.com's encrypted quote endpoint (rejected: fragile, 2/3 placement ISINs absent there).
- Changing Yahoo/Polygon fallbacks, `_BOND_SEGMENTS`, or the asset/transaction schema.
- Runtime auto-discovery of placement→market pairs — the map is never refreshed inside the price path. Out-of-band extraction from MEF documents IS in scope (helper script, Decision 6).
- Backfilling historical prices for the dual-ISIN bonds (snapshots continue to provide valuation fallback).

## Decisions

1. **Alias resolution inside the Borsa provider, not in callers.**
   Add `_BOND_ISIN_ALIASES = {placement: market}` plus a `_market_isin(symbol)` classmethod on `MarketDataService`; resolve at the top of `_borsa_italiana_spot` and `borsa_italiana_official_close`. The worker task, routers, `portfolio_engine` and the Intesa import are untouched — `asset.symbol` stays the placement ISIN, Redis cache keys and `Price.asset_id` stay keyed to it. Alternative (alias in `get_price`/worker) rejected: two call sites to keep in sync and the worker's segment cache would still key incorrectly.
2. **Small constant map keyed by the placement ISIN.**
   Retail series issued from Feb 2025 onward are few (one per placement window: BTP Più, BTP Valore, BTP Italia Sì); a dict constant beats a DB table or *runtime* MEF scraping for the "less is more" mantra. Unknown mappings simply keep today's behavior (stored-price fallback). New pairs get one dict line + ISP.md note (suggested by the out-of-band helper, Decision 6).
3. **Close-date parse: YY/MM/DD first, validated, DD/MM/YY fallback.**
   In `_parse_borsa_official_close`, read `(\d{2})/(\d{2})/(\d{2,4})` and try year=`2000+yy`, month=`mm`, day=`dd` with plausibility checks (valid calendar date, 2000 ≤ year ≤ 2100, within ~2 years of now); if implausible, retry as DD/MM/YY / DD/MM/YYYY; if still implausible, return date `None` (callers already default the refresh row to `now`). This keeps long-form cells on other MOT pages unaffected — the rule applies to the close-date cell only.
4. **One-time repair of mis-dated rows instead of migration.**
   All `BORSA_ITALIANA` Price rows with `price_date < 2026-01-01` are parse artifacts (the MOT code shipped Nov 2026); delete them via a single SQL statement against the dev DB rather than a repair script — no legit rows can predate the feature.
5. **Tests use captured fixtures, not live fetches.**
   Extend `backend/tests/test_borsa_italiana.py`: alias routing (patched `_borsa_italiana_page` asserting the market ISIN URL and custody-keyed result), scene fixtures for `26/11/20` → 2026-11-20, the DD/MM/YYYY fallback, refresh-task dedup on corrected dates. Existing fake-DB/unittest style, no network in tests.
6. **MEF documents are the authoritative source for new pairs — via an out-of-band helper, not runtime.**
   The Treasury pairs each "codice speciale" with its "codice regolare" only in documents (monthly *Scadenze titoli suddivise per anno* PDF footnotes, per-emission Information Memoranda, placement pages) — no API/CSV/JSON feed, monthly lag, Akamai bot protection (automated fetchers get Access Denied). A manual, dry-run script (`repair_bond_isin_aliases.py`) resolves the newest Scadenze edition from the dt.mef.gov.it index page, extracts pairs anchored on the official footnote wording ("Il codice ISIN 'speciale' IT… verrà sostituito dal codice ISIN 'regolare' IT…"), verifies each candidate market ISIN has a live MOT scheda page that parses, and prints suggested `_BOND_ISIN_ALIASES` lines for human review. `--url` / `--pdf <path>` overrides accept a manually downloaded edition when Akamai or the environment blocks the download. Alternative (runtime sync from MEF) rejected: network dependency in the price path, up to a month behind new placements, and multi-code issues (BTP Valore "Premio Finale Extra" con/senza) need human judgment a regex can't provide.

## Risks / Trade-offs

- [New retail placements aren't priced until someone adds the pair] → Document the pattern in ISP.md (MEF announces the definitive ISIN at placement close; run the helper for MEF-derived suggestions); unmapped bonds degrade to the current stored-price fallback, never to a wrong price.
- [Akamai blocks the helper's PDF download (dt.mef.gov.it refuses non-browser fetchers)] → `--url` / `--pdf` overrides for a manually downloaded edition; ISP.md documents the manual path.
- [Scadenze footnote wording drifts across editions] → on regex miss the helper prints the raw footnote context instead of guessing; unmapped bonds degrade to stored-price fallback.
- [Market ISIN quote diverges a few cents from the placement book price seen in home banking] → Verified deltas on live data: +0.00 / +0.07 / +0.09 — the same magnitude the user already accepts for MOT-quoted bonds. Both ISINs reference the same bond with identical cashflows.
- [Borsa page layout changes break parsers] → Same exposure as the existing MOT/ETFPlus parsers; tests pin the regexes with fixtures so drift is caught early.
- [Rate limiting (429) from borsaitaliana.it under bursts] → Existing provider already handles non-200 as "page unavailable" and falls back to stored prices; refresh task is once daily per bond. No new exposure.

## Migration Plan

1. Ship code change + tests; restart backend/celery so `_borsa_italiana_spot`/`borsa_italiana_official_close` pick up the alias map.
2. Run the one-time SQL cleanup (`DELETE FROM prices WHERE source='BORSA_ITALIANA' AND price_date < DATE '2026-01-01'`).
3. Trigger `refresh_bond_prices` once (or wait for the beat schedule) so correctly dated rows appear for all six bonds; verify the dashboard quotes against the latest home banking sheet.
4. Rollback: revert the commit; stored-price fallback continues to function. The deleted rows are re-creatable by the daily task (with the old mis-dated semantics), so no data is permanently lost.

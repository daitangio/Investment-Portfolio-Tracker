# Tasks

## 1. ISIN alias routing in the Borsa Italiana provider

- [x] 1.1 Add `_BOND_ISIN_ALIASES` constant (placement → market: IT0005713539→IT0005713547, IT0005634792→IT0005634800, IT0005696320→IT0005696338) and `_market_isin()` classmethod to `MarketDataService` in `backend/services/market_data_service.py`. Verify: unit test asserting unmapped ISINs pass through unchanged.
- [x] 1.2 Resolve the alias at the top of `_borsa_italiana_spot` and `borsa_italiana_official_close` (segment cache and page fetches use the market ISIN; returned values still normalized and keyed to the caller's symbol). Verify: patched `_borsa_italiana_page` tests asserting the scheda URL contains the market ISIN and the returned price matches `live_quote/100`.
- [x] 1.3 Add tests to `backend/tests/test_borsa_italiana.py` for all three pairs (spot + official close) and the non-aliased passthrough (e.g. IT0005622128). Verify: `cd backend && ../.venv/bin/python -m pytest tests/test_borsa_italiana.py -q` green.

## 2. Official Close Date parse fix (YY/MM/DD)

- [x] 2.1 Rework the date parsing inside `_parse_borsa_official_close` for the close-date cell: try YY/MM/DD (year=2000+yy, plausible calendar date, 2000–2100, within ~2 years of now), fall back to DD/MM/YY(YY), else return `None` date. Verify: unit tests with scheda fixtures showing `26/11/20` → `2026-11-20` (not 2020-11-26) and the DD/MM/YYYY fallback path.
- [x] 2.2 Confirm `refresh_bond_prices` (`backend/workers/tasks/market_data_tasks.py`) still dedupes correctly with real dates (no code change expected; add/extend a worker test with a fixture date so a second run for the same close does not append a duplicate row). Verify: `../.venv/bin/python -m pytest tests -q` green.

## 3. Data repair and live verification

- [x] 3.1 Run the one-time cleanup against the dev DB: `DELETE FROM prices WHERE source='BORSA_ITALIANA' AND price_date < DATE '2026-01-01';` (all such rows are mis-dated parse artifacts; MOT pricing shipped Nov 2026). Verify: SQL count query returns 0 after delete.
- [x] 3.2 Restart backend + celery worker/beat (`make restart`), trigger `refresh_bond_prices` (or wait for the beat schedule), and confirm fresh dated BORSA_ITALIANA Price rows for all six bond assets, including the three placement ISINs. Verify: DB query shows rows dated today for IT0005713539/IT0005634792/IT0005696320.
- [x] 3.3 Spot-check live quotes against the newest home banking sheet (`docs/test-privato/patrimonio-mamma*.xlsx`): the three dual-ISIN bonds within ~0.1 of the sheet's Prezzo Mercato, the other bonds unchanged within cents. Verify: `GET /api/v1/market/prices/IT0005713539` style spot fetch or portfolio summary on the dashboard.

## 4. Documentation

- [x] 4.1 Add a short "Placement vs market ISIN" note to `docs/ISP.md` (since Feb 2025 MEF retail placements carry two ISINs; how to find the definitive ISIN from the MEF placement-close notice; how to add a pair to `_BOND_ISIN_ALIASES`, manually or via `make repair-bond-isin-aliases` suggestions). Verify: doc renders and mentions all three existing pairs.
- [x] 4.2 Append the session entry to `LOG.md` (what was implemented, what is missing, model name/version). Verify: entry present and conforms to the existing format.

## 5. MEF alias helper (out-of-band)

- [x] 5.1 Create `backend/scripts/repair_bond_isin_aliases.py`: resolve the newest *Scadenze titoli suddivise per anno* edition from the dt.mef.gov.it index page (browser UA; `--url` / `--pdf <path>` overrides for a manually downloaded edition — the site is Akamai-protected and refuses automated fetchers), extract placement→market pairs with pypdf (already a dependency, `requirements.txt`) anchored on the official footnote wording ("codice ISIN 'speciale' IT… verrà sostituito dal codice ISIN 'regolare' IT…"), verify each candidate market ISIN has a live MOT scheda page that parses (HTTP 200 + ISIN in page + price), and print suggested `_BOND_ISIN_ALIASES` lines with the scheda quotes. Dry-run only — never writes code; on footnote-format drift print the raw footnote context instead of matching. Verify: run against the current edition and see the three known pairs (IT0005634792→IT0005634800, IT0005696320→IT0005696338, IT0005713539→IT0005713547) plus any newer placements.
- [x] 5.2 Add a `repair-bond-isin-aliases` target to the root `Makefile` following the `repair-assets` convention. Verify: `make repair-bond-isin-aliases` prints suggestions and exits 0.

## Workflow follow-up

- Archive the change with `/openspec-archive-change` after the user validates quotes on the dashboard.
- Commit with `git commit` (repo convention via `make push MSG=...`), co-authored per Vibe convention.

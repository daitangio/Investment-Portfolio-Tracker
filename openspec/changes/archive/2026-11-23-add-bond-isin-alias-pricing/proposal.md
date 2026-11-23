# Proposal

## Why

Retail BTP series issued from Feb 2025 onwards (BTP Più, BTP Valore, BTP Italia Sì) carry **two ISINs**: the placement ISIN that banks keep in custody (what the app imports from home banking) and a *definitive market ISIN* announced by MEF at placement close, which is the only ISIN quoted on Borsa Italiana MOT. As a result `get_price` finds no quote page for the custody ISIN (IT0005713539, IT0005634792, IT0005696320), the provider chain returns nothing (Yahoo/Polygon do not quote them either), and valuation falls back to the week-old `INTESA_SNAPSHOT` Price row — the drift seen against the daily home banking sheet (e.g. 101.40 vs 100.30 on 2026-11-23). Pre-2025 bonds (IT0005622128, IT0005495731, IT0005735201) quote under their custody ISIN and only show cents of delta.

Investigation also showed the scheda "Official Close Date" is printed `26/11/20` = **YY/MM/DD** (2026-11-20, Friday's close) but is parsed as DD/MM/YY → 2020-11-26, so the daily refresh task appends Price rows dated ~6–7 years in the past (DB currently holds BORSA_ITALIANA rows dated 2019-11-26) and the dedup check never collides.

## What Changes

- Add a custody→market ISIN alias map for dual-ISIN Italian retail bonds to the Borsa Italiana provider (known today: `IT0005713539→IT0005713547` BTP Italia Sì Jun31, `IT0005634792→IT0005634800` BTP Più Feb33, `IT0005696320→IT0005696338` BTP Valore Mar32).
- Route Borsa Italiana MOT quote fetches (live spot and daily official close) through the alias: resolve custody ISIN → market ISIN at the provider boundary; assets, transactions, cache keys and Price rows stay keyed on the custody ISIN.
- Fix the official-close date parser to read the scheda date cell as YY/MM/DD (validated, falling back to DD/MM/YY if implausible), so daily refresh rows get real dates and the one-per-day dedup works.
- One-time cleanup of the mis-dated BORSA_ITALIANA Price rows (currently dated 2019/2020) so bond history and stored-price fallback are not polluted.
- Update the Intesa import docs (ISIN pairs note) so future retail placements can get their alias added.
- Add an out-of-band MEF helper (`backend/scripts/repair_bond_isin_aliases.py`, `make repair-bond-isin-aliases`) that extracts placement→market pairs from the Treasury's monthly *Scadenze titoli suddivise per anno* PDF (official footnote wording "codice ISIN 'speciale' … verrà sostituito dal codice ISIN 'regolare' …"), verifies each candidate against a live MOT scheda page, and prints suggested `_BOND_ISIN_ALIASES` lines. The static map stays the runtime source of truth; the script is dry-run and never edits code.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `bond-market-data`: adds routing of dual-ISIN (custody→market) bonds through the market ISIN for MOT quotes, and corrects the close-date parsing requirement for daily refresh rows.

## Impact

- `backend/services/market_data_service.py` — alias map + resolution in `_borsa_italiana_spot`/`borsa_italiana_official_close`; `_parse_borsa_official_close` date semantics.
- `backend/tests/test_borsa_italiana.py` — alias routing tests + date-parse tests (fixtures from live pages: `26/11/20` → 2026-11-20).
- One-off repair of existing `prices` rows (delete/ignore mis-dated BORSA_ITALIANA rows) — SQL or small script, run once against the dev DB.
- `backend/scripts/repair_bond_isin_aliases.py` + `Makefile` target — new, manual/dry-run helper (see above).
- `docs/ISP.md` — note about placement vs market ISINs.
- No API/frontend changes: prices surface through the existing endpoints; valuation fallback and normalization behavior unchanged.

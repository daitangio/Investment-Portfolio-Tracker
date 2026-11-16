# Design

## Context

The app already has two import paths: broker trade imports (`services/transaction_import.py` → `POST /api/v1/transactions/import`, broker auto-detection via column signatures, dedup via `import_hash`) and bank statement imports (`services/bank_import_service.py` → `/api/bank-import/upload|confirm`, preview + confirm UI on `/dashboard/import`). Portfolio state is **reconstructed by replaying `transactions`** in `portfolio_engine._reconstruct_state`; `TRANSFER_IN` creates a FIFO lot at `price_per_unit`, `DEPOSIT` is pure cash. `Asset` already has `isin` and `asset_class` (incl. `BOND`), `Transaction` has `source`/`import_hash`/`raw_data`, `Price` stores dated quotes, and `FXService` converts EUR→AUD via RBA `FXREUR`. The Intesa `patrimonio.xlsx` is a holdings snapshot: all cells are Italian-locale text, sections repeat headers and end in "Totale ..." rows, and a bottom "Liquidità" section holds cash. See proposal.md for motivation and the delta specs for requirements.

## Goals / Non-Goals

**Goals:** parse the Intesa snapshot into Assets + TRANSFER_IN/DEPOSIT transactions with EUR→AUD enrichment; replace-on-confirm snapshot semantics; price BOND assets from Borsa Italiana by ISIN with stored-Price fallback; a dedicated frontend panel.

**Non-Goals:** no changes to the trade-import or bank-import paths; no schema migration; no real purchase dates (the file has none — the user-picked as-of date is used and lots will read as short-term for CGT until a year passes); no intraday bond data; no support for Intesa formats other than the patrimonio holdings export.

## Decisions

1. **Dedicated parser + router instead of extending `BROKER_SIGNATURES`.** The existing profiles are trade-event shaped (type + trade date per row); the snapshot is a state with repeated headers, totals rows and a cash section. A separate `services/isp_portfolio_import.py` + `routers/isp_import.py` keeps both paths simple. The router mirrors bank-import's upload→preview→confirm contract but returns holdings-shaped rows.
2. **Snapshot = TRANSFER_IN + DEPOSIT, keyed by ISIN.** `get_or_create_asset` is keyed on (symbol, currency), so symbol = ISIN (fits String(20)) and `isin` is also set; name from Descrizione; `asset_class` = BOND vs ETF decided per row by the file's own arithmetic (`qty × price / 100 ≈ fiscal value` → bond). Bond prices are normalized from % of nominal to EUR-per-EUR (`price/100`) so `quantity × price_per_unit = Controvalore` holds in the FIFO engine. Cash ("Saldo totale") becomes one DEPOSIT.
3. **Replace semantics on confirm.** All new rows get `source="INTESA_SNAPSHOT"`; confirm deletes existing rows with that source for the account inside the same transaction before inserting, so a newer snapshot replaces the old instead of stacking lots. `import_hash` (ISIN|qty|cost|as_of) remains as a per-row dedup safety net.
4. **As-of date from the UI.** The file's "Data-Ora" column is quote time only, so `transacted_at` = user-picked date (default today). FX enrichment uses that date's RBA EUR→AUD rate.
5. **Bond pricing via Borsa Italiana MOT scheda page.** For `asset_class == "BOND"`, `MarketDataService.get_price` tries `_borsa_italiana_spot(isin, type)` before Yahoo: `GET borsaitaliana.it/borsa/obbligazioni/mot/{type}/scheda/{ISIN}-MOTX.html?lang=en` with a browser UA, regex the server-rendered last-trade (fallback official close) — verified against IT0005622128 returning ~99.54. MOT quotes are **% of nominal, so prices are divided by 100** to match the EUR-per-EUR convention used by import-time `Price` rows and cost basis (quantity stays nominal EUR; `qty × price = market value`). {type} is derived from the asset name (BTP→btp, BOT→bot, CCT→ccteu, BTP Italia→btp-italia, BTP Valore→btp-valore, ...). Redis caching + tenacity retry like other providers; on total failure return the newest `Price` row. At import, each holding's own Prezzo Mercato is written as a `Price` row (EUR, as-of date) so valuation never depends on scraping. A daily low-priority Celery task appends official closes for BOND assets to `Price` for history/charts. ETF ISINs are resolved once to a Yahoo ticker via Yahoo symbol search (works with our UA) and stored on the asset so the existing Polygon→Yahoo chain prices them.
6. **Frontend: separate panel.** A new component on `/dashboard/import` (not the bank-statement table): file picker, as-of date input (default today), account select, holdings preview (ISIN, description, qty, cost basis, market value, AUD), row checkboxes, confirm button.

## Risks / Trade-offs

- [Borsa Italiana page structure changes or rate-limits scraping] → UA header, tenacity retries, Redis cache, and the stored `Price` fallback guarantee the portfolio still values; bond history simply pauses.
- [Wrong {type} path segment → 404] → try a small list of candidate segments derived from the name, then fall back to stored Price.
- [Snapshot lots appear <365 days old, so the ATO CGT discount won't apply] → surface a note in the confirm UI; real acquisition dates can be backfilled later by editing transactions.
- [Italian number parsing edge cases (negative "-148,91", percents "-1,47%", accounting negatives)] → one shared `parse_it_number` helper with unit tests against every cell of the sample file.
- [Replace semantics delete data] → scoped strictly to `source="INTESA_SNAPSHOT"` rows of the chosen account, inside the confirm transaction; trade/bank imports are untouched.

## Migration Plan

No migration needed: all required columns (`Asset.isin`, `asset_class`, `Transaction.source`, `import_hash`, `Price`) already exist and `String(3)` currency fields already hold "EUR". Deploy = restart backend + frontend. Rollback = remove the router/panel; imported snapshot rows can be deleted by `source="INTESA_SNAPSHOT"`.

## Open Questions

- Whether to also accept Intesa's CSV variant of the same report (same columns) — can be added later without changing these specs by extending the parser's row normalizer.
- Exact MOT {type} segment for less common bond families (e.g. CCTeu) — resolved empirically at implementation time and covered by the candidate-list fallback.

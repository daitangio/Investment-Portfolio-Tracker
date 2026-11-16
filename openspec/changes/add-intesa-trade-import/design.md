# Design

## Context

The existing Intesa importer (`backend/services/isp_portfolio_import.py`, `backend/routers/isp_import.py`) handles only the `patrimonio.xlsx` holdings snapshot, creating `TRANSFER_IN` lots tagged `source="INTESA_SNAPSHOT"`. Intesa also issues per-trade "CONFERMA OPERAZIONI IN TITOLI" PDF confirmations (samples in `docs/intesa-sample/sample-transactions/`). Each PDF page contains one trade block delimited by an "Ordine :" line; multi-page PDFs contain multiple trades. The PDFs have proper text streams extractable with `pypdf`.

## Goals / Non-Goals

**Goals:**
- Parse one Intesa trade-confirmation PDF at a time, extracting every trade block (1 trade per page)
- Map each trade to a `BUY` or `SELL` `Transaction` tagged `source="INTESA_TRADE"`, independent of snapshot rows
- Preview → confirm flow mirroring the existing snapshot importer, with EUR→AUD FX enrichment at each trade's execution date
- Separate frontend panel on `/dashboard/import`

**Non-Goals:**
- Multi-file upload (one PDF per upload, as decided)
- Modifying the snapshot importer or its `INTESA_SNAPSHOT` semantics
- OCR / image-based PDFs (the Intesa PDFs have text streams; no OCR needed)
- New database migrations (all fields already exist on `Transaction`)

## Decisions

### D1: Use `pypdf` for PDF text extraction
**Choice:** Add `pypdf` to `backend/requirements.txt` and use `PdfReader.extract_text()` per page.
**Rationale:** The Intesa PDFs have proper FlateDecode text streams (verified against the 3 samples). `pypdf` is pure-Python, lightweight, and maintained. Raw zlib extraction (zero-dep) was considered but is fragile against PDF variations (font encoding, TJ kerning arrays). Alternatives: `pdfplumber` (heavier, table-focused), `pymupdf` (native binary). `pypdf` is the simplest that works.

### D2: Split multi-page PDFs into per-page trade blocks
**Choice:** Extract text page-by-page with `pypdf`, then split the concatenated text on "Ordine :" occurrences. Each block from one "Ordine :" to the next (or end of page) is one trade.
**Rationale:** Each page has exactly one "Ordine :" header (verified in the 2-page sample). Page-level extraction keeps the page boundary clean; the "Ordine :" split handles the case where a single page could contain a continuation. The order number (e.g. `INTE1020026863576693`) is unique per trade and serves as the dedup key.

### D3: Bond vs ETF price normalization (same as snapshot importer)
**Choice:** Detect bond trades via the "Sede di Esecuzione" containing "MOT"/"HMTF"/" TIT.STATO", or the description matching BOND_PREFIX_SEGMENTS (reuse from `isp_portfolio_import`). Bond PREZZO is divided by 100; ETF PREZZO is per-unit as-is.
**Rationale:** Consistent with the existing snapshot importer's bond normalization (`quantity x price_per_unit = market value`). The "Sede di Esecuzione" field (`IT MOT TIT.STATO CLEA`, `IT HMTF VORVEL BONDS`) is a reliable bond indicator in the PDF.

### D4: Fold all fee-like lines into `fees`
**Choice:** Sum COMMISSIONI BANCA + SPESE CONFERMA OPERAZIONI IN TITOLI + COSTI DI ESECUZIONE + RATEO LORDO + IMPOSTA SUL RATEO LORDO (with printed signs) into `Transaction.fees`, marked with a `# folded fees here` code comment. Use `TOTALE` as `net_amount`.
**Rationale:** The portfolio engine's `_apply_buy` computes cost basis as `(qty * price + fees) / qty`, and `_apply_sell` subtracts fees from proceeds — folding everything into fees keeps the engine's math correct without model changes. Rateo lordo (accrued interest) and imposta sul rateo are bond-specific but their net effect on the trade is captured in TOTALE; folding avoids a new transaction type. The `# folded fees here` comment makes the folding explicit for future maintainers.

### D5: import_hash from order number
**Choice:** `import_hash = sha256("INTESA_TRADE|{ordine_number}")` (scoped per account like the snapshot's `scoped_hash`).
**Rationale:** The order number is unique per execution and stable across re-exports. Using it as the hash makes re-imports idempotent (skip duplicates) without depending on mutable fields like price.

### D6: New endpoints on the existing `isp_import` router
**Choice:** Add `POST /api/v1/isp-import/trades/upload` and `POST /api/v1/isp-import/trades/confirm` to `backend/routers/isp_import.py`, with the parsing logic in a new `backend/services/isp_trade_import.py`.
**Rationale:** Keeps all Intesa import logic under one router prefix and reuses auth/db dependencies. The service module is separate from `isp_portfolio_import.py` to keep the snapshot logic untouched (less-is-more).

### D7: Separate frontend panel
**Choice:** New `frontend/src/app/dashboard/import/IspTradePanel.tsx`, rendered alongside `IspImportPanel` in `page.tsx`.
**Rationale:** The snapshot panel is holdings-shaped (ISIN/qty/cost/market value); the trade panel is transaction-shaped (date/type/qty/price/fees/net). Separate panels keep each simple.

### D8: FX enrichment per trade at execution date
**Choice:** Call `FXService.get_aud_rate("EUR", execution_datetime)` per unique date in the preview; reuse `enrich_transaction_with_aud` for the AUD fields.
**Rationale:** Each trade has its own execution date; the ATO CGT engine needs `fx_rate_to_aud` at the transaction date. Batch by date to avoid redundant FX calls.

## Risks / Trade-offs

- **[Risk]** PDF text extraction order may vary across Intesa PDF versions → **Mitigation:** Parse by regex on known labels ("Ordine :", "PREZZO", "TOTALE", etc.) rather than fixed line positions; test against all 3 sample PDFs.
- **[Risk]** Bond "Sede di Esecuzione" may use different market codes in future → **Mitigation:** Fall back to description-based bond detection (BOND_PREFIX_SEGMENTS) if sede doesn't match.
- **[Risk]** `pypdf` extraction may include kerning artifacts in TJ arrays → **Mitigation:** `pypdf`'s `extract_text()` handles TJ arrays correctly (unlike raw regex on the content stream); the 3 samples extract cleanly.
- **[Trade-off]** Folding rateo/imposta into fees loses the distinction for tax reporting → **Mitigation:** Store the raw parsed line items in `Transaction.raw_data` for auditability.

## Migration Plan

No database migration needed. Deployment: add `pypdf` to requirements, rebuild backend image, new endpoints are additive. Rollback: remove the two new endpoints and the frontend panel; no data is mutated destructively (trades are tagged `INTESA_TRADE` and only deleted on explicit re-confirm of the same order IDs).

## Open Questions

None — all design decisions were confirmed with the user (pypdf dependency, folded fees with comment, separate panel, `INTESA_TRADE` tag, one PDF per upload).

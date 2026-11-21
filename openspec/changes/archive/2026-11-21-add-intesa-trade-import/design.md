# Design

## Context

The existing Intesa importer (`backend/services/isp_portfolio_import.py`, `backend/routers/isp_import.py`) handles only the `patrimonio.xlsx` holdings snapshot, creating `TRANSFER_IN` lots tagged `source="INTESA_SNAPSHOT"`. Intesa also issues per-trade "CONFERMA OPERAZIONI IN TITOLI" PDF confirmations (samples in `docs/intesa-sample/sample-transactions/`). Each PDF page contains one trade block delimited by an "Ordine :" line; multi-page PDFs contain multiple trades. The PDFs have proper text streams extractable with `pypdf`.

The `/dashboard/transactions` page already has an "Add Portfolio" flow: a `BROKERS[]` grid where each broker has instructions, currency, and a `BrokerUploadPanel` that auto-creates an account and POSTs to `/api/v1/transactions/import` with a `broker_hint`. The backend `TransactionImporter` handles CSV/XLSX/JSON.

## Goals / Non-Goals

**Goals:**
- Parse one Intesa trade-confirmation PDF at a time, extracting every trade block (1 trade per page)
- Map each trade to a `BUY` or `SELL` `Transaction` tagged `source="INTESA_TRADE"`, independent of snapshot rows
- Integrate into the existing broker "Add Portfolio" flow on `/dashboard/transactions` — Intesa as a broker card, PDF dropzone, auto-created EUR account
- Direct import via `POST /transactions/import` (no separate preview panel)

**Non-Goals:**
- Multi-file upload (one PDF per upload)
- Modifying the snapshot importer or its `INTESA_SNAPSHOT` semantics (snapshot panel stays on `/dashboard/import`)
- OCR / image-based PDFs (the Intesa PDFs have text streams)
- New database migrations (all fields already exist on `Transaction`)
- A standalone preview/confirm UI for trades (the broker flow imports directly; dedup makes re-imports safe)

## Decisions

### D1: Use `pypdf` for PDF text extraction
**Choice:** Add `pypdf` to `backend/requirements.txt` and use `PdfReader.extract_text()` per page.
**Rationale:** The Intesa PDFs have proper FlateDecode text streams (verified against the 3 samples). `pypdf` is pure-Python, lightweight, and maintained. Raw zlib extraction (zero-dep) was considered but is fragile against PDF variations. Alternatives: `pdfplumber` (heavier), `pymupdf` (native binary). `pypdf` is the simplest that works.

### D2: Split multi-page PDFs into per-page trade blocks
**Choice:** Extract text page-by-page with `pypdf`, then split on "Ordine :" occurrences. Each block is one trade.
**Rationale:** Each page has exactly one "Ordine :" header (verified in the 2-page sample). The order number (e.g. `INTE1020026863576693`) is unique per trade and serves as the dedup key.

### D3: Bond vs ETF price normalization (same as snapshot importer)
**Choice:** Detect bond trades via the "Sede di Esecuzione" containing "MOT"/"HMTF"/" TIT.STATO", or the description matching BOND_PREFIX_SEGMENTS (reuse from `isp_portfolio_import`). Bond PREZZO is divided by 100; ETF PREZZO is per-unit as-is.
**Rationale:** Consistent with the existing snapshot importer's bond normalization (`quantity x price_per_unit = market value`).

### D4: Fold all fee-like lines into `fees`
**Choice:** Sum COMMISSIONI BANCA + SPESE + COSTI DI ESECUZIONE + RATEO LORDO + IMPOSTA SUL RATEO (with printed signs) into `Transaction.fees`, marked with a `# folded fees here` code comment. Use `TOTALE` as `net_amount`. For SELL the sign is flipped so `qty*price - fees == TOTALE` (engine invariant).
**Rationale:** The portfolio engine's `_apply_buy` computes cost basis as `(qty * price + fees) / qty`, and `_apply_sell` subtracts fees from proceeds — folding keeps the math correct without model changes. The `# folded fees here` comment makes the folding explicit.

### D5: import_hash from order number
**Choice:** `import_hash = sha256("INTESA_TRADE|{ordine_number}")` (scoped per account like the snapshot's `scoped_hash`).
**Rationale:** The order number is unique per execution and stable across re-exports. Idempotent re-imports.

### D6: Dispatch on PDF inside `POST /transactions/import`
**Choice:** In `backend/routers/transactions.py`, check the file extension before constructing `TransactionImporter`: if `ext == "pdf"` and `broker_hint == "intesa_sanpaolo"`, call `isp_trade_import.parse_pdf` + `confirm_trades`, and wrap the result in the existing `ImportResultResponse` (imported=saved, duplicates=skipped, broker_detected="Intesa Sanpaolo"). The standalone `/isp-import/trades/*` endpoints are removed.
**Rationale:** One import endpoint for all brokers keeps the frontend simple — `BrokerUploadPanel` already posts there. The parser/confirm logic stays in `isp_trade_import.py`; only the HTTP entry point moves.

### D7: Intesa as a BROKERS entry, not a standalone panel
**Choice:** Add `{ id: "intesa_sanpaolo", label: "Intesa Sanpaolo", country: "IT", currency: "EUR", fileTypes: "PDF", instructions: [...] }` to `BROKERS[]` in `transactions/page.tsx`, and add `application/pdf: [".pdf"]` to the dropzone accept map. Delete `IspTradePanel.tsx` and its render in `import/page.tsx`.
**Rationale:** The broker grid already handles account auto-creation, instructions, and the import toast. A separate panel would duplicate that. The snapshot panel (`IspImportPanel`) stays on `/dashboard/import` because snapshots are a different workflow.

### D8: FX enrichment per trade at execution date
**Choice:** Call `FXService.get_aud_rate("EUR", execution_datetime)` per unique date; reuse `enrich_transaction_with_aud` for the AUD fields.
**Rationale:** Each trade has its own execution date; the ATO CGT engine needs `fx_rate_to_aud` at the transaction date. Batch by date to avoid redundant FX calls.

### D9: Direct import, no preview step
**Choice:** The broker flow imports directly (no per-row preview/confirm table). Dedup via `import_hash` makes re-imports idempotent; the user sees results in the transaction table and the toast.
**Rationale:** Consistent with every other broker in the grid. The preview was only needed when we had a manual account picker; with auto-created accounts and idempotent dedup it's unnecessary. Trade-off accepted: no pre-import review grid for PDF trades.

## Risks / Trade-offs

- **[Risk]** PDF text extraction order may vary across Intesa PDF versions → **Mitigation:** Parse by regex on known labels ("Ordine :", "PREZZO", "TOTALE", etc.) rather than fixed line positions; test against all 3 sample PDFs.
- **[Risk]** Bond "Sede di Esecuzione" may use different market codes in future → **Mitigation:** Fall back to description-based bond detection (BOND_PREFIX_SEGMENTS) if sede doesn't match.
- **[Risk]** `pypdf` extraction may include kerning artifacts → **Mitigation:** `pypdf`'s `extract_text()` handles TJ arrays correctly; the 3 samples extract cleanly.
- **[Trade-off]** Folding rateo/imposta into fees loses the distinction for tax reporting → **Mitigation:** Store the raw parsed line items in `Transaction.raw_data` for auditability.
- **[Trade-off]** No preview means a malformed PDF imports partially → **Mitigation:** Parse all trades first; if parsing raises, return 422 and persist nothing. Dedup prevents double-import on retry.

## Migration Plan

No database migration needed. The code currently has the standalone `/isp-import/trades/*` endpoints and `IspTradePanel.tsx` (initial implementation); this revision moves them: delete the panel, add the broker entry, extend `/transactions/import`. Already-imported `INTESA_TRADE` rows are unaffected (same source tag, same import_hash scheme). Rollback: revert the frontend broker entry and restore the standalone endpoints.

## Open Questions

None — all decisions confirmed with the user (pypdf, folded fees with comment, broker-grid integration instead of standalone panel, `INTESA_TRADE` tag, one PDF per upload, direct import without preview).

# Spec Delta

## Purpose

Lets users import individual trade confirmations (BUY/SELL with ISIN, quantity, price, fees, execution date) from institution PDF documents into the portfolio engine, so FIFO cost basis, realized P&L, and ATO CGT calculations include those trades. Starts with Intesa Sanpaolo "CONFERMA OPERAZIONI IN TITOLI" PDFs.

## ADDED Requirements

### Requirement: Parse Intesa trade-confirmation PDFs
The system SHALL accept a single Intesa Sanpaolo "CONFERMA OPERAZIONI IN TITOLI" PDF (one trade per page; multi-page PDFs contain multiple trades) and extract each trade block delimited by an "Ordine :" line.

#### Scenario: ETF buy on single-page PDF
- **WHEN** a PDF containing one ACQUISTO of 25 units of ISIN IE00B1YZSC51 at EUR 39.64 is uploaded
- **THEN** the preview contains one trade with type BUY, ISIN IE00B1YZSC51, quantity 25, price_per_unit 39.64, currency EUR

#### Scenario: Multi-page PDF with two trades
- **WHEN** a two-page PDF containing one ACQUISTO (ETF) and one VENDITA (BTP) is uploaded
- **THEN** the preview contains exactly two trades, one BUY and one SELL, each parsed from its own page

#### Scenario: Non-Intesa PDF rejected
- **WHEN** a PDF without the "CONFERMA OPERAZIONI IN TITOLI" marker is uploaded
- **THEN** the upload endpoint returns HTTP 422 with a descriptive error

### Requirement: Map PDF fields to Transaction fields
The system SHALL map each parsed trade to a Transaction row: ACQUISTO maps to BUY, VENDITA maps to SELL, the ISIN from "Codice e descrizione Titolo" resolves to an Asset, "Eseguito per" (or "Valore nominale") is the quantity, "PREZZO" unit price is price_per_unit, "Data e ora di esecuzione" is transacted_at, "Data di regolamento" is settled_at, and "TOTALE" is net_amount.

#### Scenario: BUY maps to BUY transaction
- **WHEN** an ACQUISTO trade is confirmed
- **THEN** a Transaction with transaction_type="BUY", source="INTESA_TRADE", institution="intesa_sanpaolo" is persisted

#### Scenario: SELL maps to SELL transaction
- **WHEN** a VENDITA trade is confirmed
- **THEN** a Transaction with transaction_type="SELL" is persisted with quantity and price_per_unit set so the FIFO engine consumes lots

### Requirement: Normalize bond prices from % of nominal
The system SHALL divide bond price quotes (which are % of nominal, e.g. 100.000000 or 97.951000) by 100 so that quantity (nominal EUR) x price_per_unit = gross proceeds, consistent with the snapshot importer and the FIFO engine.

#### Scenario: BTP buy at 100% of nominal
- **WHEN** a BTP ACQUISTO with PREZZO 100.000000 and Valore nominale 3.000,000 EUR is parsed
- **THEN** price_per_unit is 1.0 and quantity is 3000

#### Scenario: BTP sell at 97.951% of nominal
- **WHEN** a BTP VENDITA with PREZZO 97.951000 and Valore nominale 5.000,000 EUR is parsed
- **THEN** price_per_unit is 0.97951 and quantity is 5000

#### Scenario: ETF price is per-unit, not normalized
- **WHEN** an ETF ACQUISTO with PREZZO 39.640000 is parsed
- **THEN** price_per_unit is 39.64 (no division by 100)

### Requirement: Fold all fee-like line items into fees
The system SHALL sum COMMISSIONI BANCA, SPESE CONFERMA OPERAZIONI IN TITOLI, COSTI DI ESECUZIONE, RATEO LORDO, and IMPOSTA SUL RATEO LORDO (with their printed signs) into the Transaction fees field, and use TOTALE as net_amount.

#### Scenario: ETF buy with multiple fee lines
- **WHEN** an ACQUISTO with COMMISSIONI BANCA 3.50, SPESE 0.50, COSTI DI ESECUZIONE 2.50, TOTALE 997.50 is parsed
- **THEN** fees = 6.50 and net_amount = 997.50

#### Scenario: Bond sell with rateo and imposta folded in
- **WHEN** a VENDITA with RATEO LORDO +52.02, IMPOSTA SUL RATEO -6.50, COMMISSIONI BANCA -10.28, SPESE -0.50, COSTI -3.00, TOTALE 4.929,29 is parsed
- **THEN** fees = 52.02 - 6.50 - 10.28 - 0.50 - 3.00 = 31.74 and net_amount = 4929.29

### Requirement: Deduplicate trades by order number
The system SHALL compute each trade's import_hash from the "Ordine" number (e.g. INTE1020026863576693) so that re-uploading the same PDF does not create duplicate Transaction rows.

#### Scenario: Re-import same PDF skips duplicates
- **WHEN** the same PDF is uploaded and confirmed twice
- **THEN** the second confirm reports all trades as skipped_duplicates and inserts zero new rows

#### Scenario: Same order in different PDFs deduplicates
- **WHEN** two different PDFs both contain order INTE1020026863576693
- **THEN** only one Transaction with that import_hash exists after both are confirmed

### Requirement: FX-enrich trades to AUD at execution date
The system SHALL fetch the EUR→AUD rate at each trade's execution date via FXService and populate fx_rate_to_aud, net_amount_aud, and price_per_unit_aud on each Transaction.

#### Scenario: Preview shows AUD equivalents
- **WHEN** a PDF is uploaded for preview
- **THEN** each preview trade includes fx_rate_to_aud, net_amount_aud, and price_per_unit_aud computed from the EUR→AUD rate on the trade's execution date

### Requirement: Trades tagged INTESA_TRADE are independent of snapshot
The system SHALL tag imported trades with source="INTESA_TRADE" so they are not deleted when a patrimonio snapshot is re-confirmed (which replaces only source="INTESA_SNAPSHOT" rows).

#### Scenario: Snapshot re-confirm does not delete trades
- **WHEN** trades are imported with source="INTESA_TRADE" and then a patrimonio.xlsx snapshot is confirmed for the same account
- **THEN** the INTESA_TRADE rows remain and only INTESA_SNAPSHOT rows are replaced

### Requirement: Preview/confirm API for trade PDFs
The system SHALL expose POST /api/v1/isp-import/trades/upload (accepts one PDF, returns a preview of all parsed trades with AUD enrichment and duplicate flags) and POST /api/v1/isp-import/trades/confirm (persists the user-approved trades as Transaction rows).

#### Scenario: Upload returns preview without persisting
- **WHEN** a valid PDF is POSTed to /trades/upload
- **THEN** the response lists all trades with their parsed fields, AUD equivalents, and duplicate flags, and no Transaction rows are written

#### Scenario: Confirm persists only approved trades
- **WHEN** the user deselects one trade and confirms
- **THEN** only the selected trades are inserted as Transaction rows; the deselected one is not persisted

### Requirement: Frontend panel for Intesa trade PDFs
The system SHALL provide a separate panel on /dashboard/import for uploading one Intesa trade-confirmation PDF at a time, showing a selectable preview table (date, ISIN, description, BUY/SELL, quantity, price, fees, net EUR, net AUD) and a confirm button.

#### Scenario: User imports a PDF from the import page
- **WHEN** the user selects a PDF in the Intesa trades panel and clicks confirm
- **THEN** the parsed trades appear in the transactions list and the panel shows a success message with the saved count

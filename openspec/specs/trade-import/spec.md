# trade-import Specification

## Purpose

Lets users import individual trade confirmations (BUY/SELL with ISIN, quantity, price, fees, execution date) from institution PDF documents into the portfolio engine, so FIFO cost basis, realized P&L, and ATO CGT calculations include those trades. Starts with Intesa Sanpaolo "CONFERMA OPERAZIONI IN TITOLI" PDFs, integrated into the broker "Add Portfolio" flow on /dashboard/transactions.

## Requirements

### Requirement: Parse Intesa trade-confirmation PDFs
The system SHALL accept a single Intesa Sanpaolo "CONFERMA OPERAZIONI IN TITOLI" PDF (one trade per page; multi-page PDFs contain multiple trades) and extract each trade block delimited by an "Ordine :" line.

#### Scenario: ETF buy on single-page PDF
- **WHEN** a PDF containing one ACQUISTO of 25 units of ISIN IE00B1YZSC51 at EUR 39.64 is uploaded
- **THEN** the import result reports 1 imported transaction with type BUY, ISIN IE00B1YZSC51, quantity 25, price_per_unit 39.64, currency EUR

#### Scenario: Multi-page PDF with two trades
- **WHEN** a two-page PDF containing one ACQUISTO (ETF) and one VENDITA (BTP) is uploaded
- **THEN** the import result reports 2 imported transactions, one BUY and one SELL, each parsed from its own page

#### Scenario: Non-Intesa PDF rejected
- **WHEN** a PDF without the "CONFERMA OPERAZIONI IN TITOLI" marker is uploaded
- **THEN** the import endpoint returns HTTP 422 with a descriptive error

### Requirement: Map PDF fields to Transaction fields
The system SHALL map each parsed trade to a Transaction row: ACQUISTO maps to BUY, VENDITA maps to SELL, the ISIN from "Codice e descrizione Titolo" resolves to an Asset, "Eseguito per" (or "Valore nominale") is the quantity, "PREZZO" unit price is price_per_unit, "Data e ora di esecuzione" is transacted_at, "Data di regolamento" is settled_at, and "TOTALE" is net_amount.

#### Scenario: BUY maps to BUY transaction
- **WHEN** an ACQUISTO trade is imported
- **THEN** a Transaction with transaction_type="BUY", source="INTESA_TRADE", institution="intesa_sanpaolo" is persisted

#### Scenario: SELL maps to SELL transaction
- **WHEN** a VENDITA trade is imported
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
- **THEN** the folded fee sum is 31.74 and net_amount = 4929.29

### Requirement: Deduplicate trades by order number
The system SHALL compute each trade's import_hash from the "Ordine" number (e.g. INTE1020026863576693) so that re-uploading the same PDF does not create duplicate Transaction rows.

#### Scenario: Re-import same PDF skips duplicates
- **WHEN** the same PDF is imported twice into the same account
- **THEN** the second import reports all trades as duplicates and inserts zero new rows

#### Scenario: Same order in different PDFs deduplicates
- **WHEN** two different PDFs both contain order INTE1020026863576693
- **THEN** only one Transaction with that import_hash exists after both are imported

### Requirement: FX-enrich trades to AUD at execution date
The system SHALL fetch the EUR→AUD rate at each trade's execution date via FXService and populate fx_rate_to_aud, net_amount_aud, and price_per_unit_aud on each Transaction.

#### Scenario: Imported trades carry AUD equivalents
- **WHEN** a PDF is imported
- **THEN** each persisted Transaction includes fx_rate_to_aud, net_amount_aud, and price_per_unit_aud computed from the EUR→AUD rate on the trade's execution date

### Requirement: Trades tagged INTESA_TRADE are independent of snapshot
The system SHALL tag imported trades with source="INTESA_TRADE" so they are not deleted when a patrimonio snapshot is re-confirmed (which replaces only source="INTESA_SNAPSHOT" rows).

#### Scenario: Snapshot re-confirm does not delete trades
- **WHEN** trades are imported with source="INTESA_TRADE" and then a patrimonio.xlsx snapshot is confirmed for the same account
- **THEN** the INTESA_TRADE rows remain and only INTESA_SNAPSHOT rows are replaced

### Requirement: Single import endpoint for trade PDFs via broker flow
The system SHALL accept Intesa trade-confirmation PDFs through the existing broker import endpoint `POST /api/v1/transactions/import` with a `.pdf` file and `broker_hint="intesa_sanpaolo"`. The endpoint SHALL parse and persist all trades in one call (no separate preview/confirm step — dedup via import_hash makes re-imports idempotent) and return the standard `ImportResultResponse` with `imported`, `duplicates`, and `broker_detected="Intesa Sanpaolo"`.

#### Scenario: Upload PDF via broker endpoint imports directly
- **WHEN** a valid Intesa PDF is POSTed to /api/v1/transactions/import with broker_hint="intesa_sanpaolo"
- **THEN** all trades are persisted as Transaction rows and the response reports imported=N, duplicates=M, broker_detected="Intesa Sanpaolo"

#### Scenario: Non-PDF rejected with clear error
- **WHEN** a non-Intesa PDF is uploaded with broker_hint="intesa_sanpaolo"
- **THEN** the endpoint returns HTTP 422

### Requirement: Intesa Sanpaolo broker card in Add Portfolio
The system SHALL list "Intesa Sanpaolo" (country IT, currency EUR, file type PDF) in the broker grid of the "Add Portfolio" panel on `/dashboard/transactions`. Selecting it SHALL show export instructions and a dropzone accepting `.pdf` files.

#### Scenario: User selects Intesa from Add Portfolio
- **WHEN** the user clicks "Add Portfolio" on /dashboard/transactions and selects "Intesa Sanpaolo"
- **THEN** the panel shows PDF export instructions and a dropzone that accepts .pdf files

### Requirement: Account auto-created with EUR base currency
When no existing Intesa Sanpaolo account is found, the broker panel SHALL auto-create one with `institution_name="Intesa Sanpaolo"`, `account_type="BROKERAGE"`, `currency="EUR"` before importing.

#### Scenario: First import creates EUR account
- **WHEN** a user uploads an Intesa PDF and no account with institution "Intesa Sanpaolo" exists
- **THEN** a new BROKERAGE account with currency EUR is created and the trades are imported into it

#### Scenario: Existing Intesa account is reused
- **WHEN** a user uploads an Intesa PDF and an account with institution "Intesa Sanpaolo" already exists
- **THEN** the trades are imported into the existing account without creating a duplicate

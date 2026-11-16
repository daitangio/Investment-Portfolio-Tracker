# Spec Delta

## Purpose

Lets users import portfolio holdings snapshots (current positions plus cash) exported by external institutions, starting with Intesa Sanpaolo's "patrimonio" Excel file, so those positions appear in the portfolio with correct cost basis and FX conversion.

## ADDED Requirements

### Requirement: Intesa Sanpaolo patrimoine file detection
The system SHALL detect an Intesa Sanpaolo patrimoine.xlsx upload by its structure (repeated "Descrizione"/"ISIN"/"Quantità" header rows and a "Controvalore" column) and parse it without requiring a broker hint.

#### Scenario: Sample file is detected
- **WHEN** the file `docs/intesa-sample/patrimonio.xlsx` is uploaded
- **THEN** the importer identifies it as Intesa Sanpaolo and returns a preview instead of an error

#### Scenario: Non-Intesa file is rejected
- **WHEN** an unrelated Excel file is uploaded to the Intesa endpoint
- **THEN** the system responds with a 422 error explaining the expected structure

### Requirement: Italian-locale cell parsing
The system SHALL parse Italian-locale text cells: "." as thousands separator, "," as decimal separator, and trailing " €" / " %" suffixes, in every numeric column.

#### Scenario: Bond row values parse
- **WHEN** a row contains Quantità "10.000", Prezzo medio fiscale "101,039081 €" and Controvalore "9.955,00"
- **THEN** the parsed values are 10000, 101.039081 and 9955.00 as decimals

### Requirement: Multi-section layout handling
The system SHALL walk the sheet section by section, skipping title rows, repeated header rows, blank rows and "Totale ..." section totals, and SHALL treat the "Liquidità"/"Saldo" rows at the bottom as the cash position.

#### Scenario: Sample file sections
- **WHEN** parsing the sample file
- **THEN** exactly 8 holdings are extracted (6 BTP bonds + 2 ETFs) and one cash amount of 10595.12 EUR

### Requirement: Bond versus per-unit price semantics
The system SHALL distinguish Italian government bonds (quantity = nominal EUR, price quoted as % of nominal) from ETFs (quantity = units, price = EUR per unit), using the row's own figures: if quantity × price / 100 equals the fiscal carrying value the row is a bond, otherwise per-unit.

#### Scenario: Bond price normalized to EUR per EUR
- **WHEN** a BTP row has quantity 10000 and fiscal price 101.039081 (% of nominal)
- **THEN** the stored price_per_unit is 1.01039081 so that quantity × price_per_unit = 10103.9081 EUR

#### Scenario: ETF price kept per unit
- **WHEN** an ETF row has quantity 295 and fiscal price 39.274983 EUR
- **THEN** the stored price_per_unit is 39.274983

### Requirement: Asset creation keyed by ISIN
The system SHALL create or reuse one Asset per ISIN with symbol = ISIN, isin = ISIN, name = Descrizione, currency = "EUR", asset_class = "BOND" for government bonds and "ETF" otherwise, and exchange set to the Italian/Euronext market.

#### Scenario: Re-import reuses assets
- **WHEN** the same ISIN appears in two imports
- **THEN** no duplicate Asset row is created

### Requirement: Snapshot becomes opening-balance transactions
The system SHALL represent each holding as one TRANSFER_IN transaction with quantity and price_per_unit = average fiscal price, currency EUR, and the user-selected as-of date as transacted_at, and the cash section as one DEPOSIT; all rows carry source = "INTESA_SNAPSHOT" and an import_hash for dedup.

#### Scenario: Sample import produces expected rows
- **WHEN** the sample file is confirmed with as-of date D
- **THEN** 8 TRANSFER_IN transactions plus 1 DEPOSIT are persisted, all dated D, all in EUR with source "INTESA_SNAPSHOT"

### Requirement: Snapshot replace semantics
The system SHALL, on confirm, delete all existing transactions with source = "INTESA_SNAPSHOT" for the target account before inserting the new snapshot, so re-importing a newer patrimoine file never double-counts positions.

#### Scenario: Second import replaces the first
- **WHEN** a snapshot is confirmed for an account that already has INTESA_SNAPSHOT rows
- **THEN** the old snapshot rows are removed and only the new snapshot remains

### Requirement: EUR to AUD enrichment
The system SHALL enrich every imported row with fx_rate_to_aud (RBA FXREUR at the as-of date), net_amount_aud and price_per_unit_aud, via the existing FXService AUD pivot.

#### Scenario: FX fields populated
- **WHEN** an imported TRANSFER_IN is persisted
- **THEN** fx_rate_to_aud, net_amount_aud and price_per_unit_aud are non-null and consistent (net_amount × fx_rate_to_aud = net_amount_aud)

### Requirement: Preview and confirm endpoints
The system SHALL expose POST /api/v1/isp-import/upload (parse + FX-enrich + preview, no persistence) and POST /api/v1/isp-import/confirm (validate account, replace old snapshot, persist selected rows) returning saved/skipped counts.

#### Scenario: Upload returns preview
- **WHEN** a valid file is posted to /api/v1/isp-import/upload with an as_of date
- **THEN** the response lists all holdings with ISIN, quantity, cost basis, market value, currency and import_hash, and persists nothing

#### Scenario: Confirm persists and dedups
- **WHEN** /api/v1/isp-import/confirm is called twice with the same import_hashes
- **THEN** the first call saves the rows and the second skips them as duplicates

### Requirement: Frontend import panel
The system SHALL provide a dedicated panel on the dashboard import page with a file picker, as-of date picker (default today), destination account selector, and a holdings preview table (ISIN, description, quantity, cost basis, market value, AUD value) with per-row selection and a confirm button.

#### Scenario: Panel flow
- **WHEN** the user uploads a patrimoine file in the Intesa panel, picks a date and an account, and confirms
- **THEN** the holdings are saved to that account dated as picked and the UI shows the saved count

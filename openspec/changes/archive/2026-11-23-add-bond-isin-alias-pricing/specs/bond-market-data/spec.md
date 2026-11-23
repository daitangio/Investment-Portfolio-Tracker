# Spec Delta

## ADDED Requirements

### Requirement: Dual-ISIN retail bonds priced through their market ISIN
The system SHALL resolve custodied placement ISINs of dual-ISIN Italian retail bonds to their quoted market ISIN before fetching Borsa Italiana MOT quotes (live spot and daily official close). Assets, transactions, portfolio keys and Price rows SHALL remain keyed on the placement ISIN held in custody; only the quote lookup is routed through the market ISIN. Bonds not present in the alias map SHALL be quoted by their own ISIN unchanged.

#### Scenario: BTP Italia Sì valued at the live market quote
- **WHEN** a spot price is requested for placement ISIN IT0005713539 (market ISIN IT0005713547, MOT last quote 100.30)
- **THEN** the quote is fetched from the market ISIN's scheda page and the returned price is 1.003 (EUR per EUR of nominal)

#### Scenario: BTP Più valued at the live market quote
- **WHEN** a spot price is requested for placement ISIN IT0005634792 (market ISIN IT0005634800, MOT last quote 95.56)
- **THEN** the returned price is 0.9556, and the stored/fallback Price row still belongs to the IT0005634792 asset

#### Scenario: Daily refresh stores rows for the placement ISIN
- **WHEN** the daily bond price refresh runs for placement ISIN IT0005696320 (market ISIN IT0005696338, official close 96.07884)
- **THEN** a normalized Price row (0.9607884, source BORSA_ITALIANA) is appended for the IT0005696320 asset

#### Scenario: Non-aliased bonds are unaffected
- **WHEN** a spot price is requested for IT0005622128, which is not in the alias map
- **THEN** the scheda page is fetched for IT0005622128 itself, as before

### Requirement: Official close date parsed from the scheda close-date cell
The system SHALL parse the "Official Close Date" printed on Borsa Italiana MOT scheda pages as YY/MM/DD (e.g. `26/11/20` = 2026-11-20), validating the result is a plausible recent close date; if the YY/MM/DD reading is not plausible the system SHALL fall back to DD/MM/YY, and if the cell cannot be parsed the close date SHALL be treated as unknown. Daily refresh rows SHALL use the parsed date so one row exists per close date.

#### Scenario: Short-form close date reads as YY/MM/DD
- **WHEN** the scheda close-date cell shows `26/11/20` (Friday 20 Nov 2026) with close 99.56285
- **THEN** the parsed close date is 2026-11-20 — not 2020-11-26

#### Scenario: Implausible YY/MM/DD reading falls back to DD/MM/YY
- **WHEN** the close-date cell reads `26/11/2026` (4-digit year, so a YY/MM/DD reading of year 2611 is impossible)
- **THEN** the date is parsed as DD/MM/YYYY 2026-11-26 if plausible, otherwise treated as unknown

#### Scenario: Daily refresh deduplicates on the correct date
- **WHEN** the daily refresh runs twice for the same close date
- **THEN** only one BORSA_ITALIANA Price row exists for that asset and date

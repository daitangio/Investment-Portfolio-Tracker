# Spec Delta

## ADDED Requirements

### Requirement: btpfacile.it fallback for BOND spot prices when Borsa Italiana fails
The system SHALL try btpfacile.it (`btpfacile.it/it/btp/{ISIN}`) as a price source for BOND assets when every Borsa Italiana MOT segment lookup has failed (HTTP error, 429 too-many-requests, timeout, or unparseable page), before falling back to Yahoo/Polygon. The quote parsed from the btpfacile page is a % of nominal and SHALL be divided by 100 exactly like a MOT quote, returning EUR per EUR of nominal.

#### Scenario: Borsa Italiana 429 falls back to btpfacile
- **WHEN** a spot price is requested for BOND asset IT0005622128, all borsaitaliana.it MOT segment requests return HTTP 429, and btpfacile.it shows a quote of 99,58 for that ISIN
- **THEN** the returned price is 0.9958 (EUR per EUR of nominal)

#### Scenario: Borsa Italiana 404/unparseable also falls back
- **WHEN** a spot price is requested for a BOND ISIN whose MOT scheda pages are unreachable or unparseable and btpfacile.it has the ISIN
- **THEN** the btpfacile quote (÷100) is returned instead of falling straight to Yahoo

#### Scenario: btpfacile 404 falls through to Yahoo/Polygon
- **WHEN** a spot price is requested for a non-BTP bond (e.g. a BOT/CCT ISIN with no btpfacile page, HTTP 404) and Borsa Italiana also failed
- **THEN** the btpfacile step returns no price and the existing Yahoo/Polygon fallback chain runs unchanged

#### Scenario: Borsa Italiana success never touches btpfacile
- **WHEN** a spot price is requested for a BOND ISIN and Borsa Italiana returns a valid last-trade price
- **THEN** the btpfacile.it site is not requested and the Borsa price is returned

### Requirement: Dual-ISIN alias resolution applies to btpfacile lookups
The system SHALL resolve placement ISINs to their market ISIN via the same alias map used for Borsa Italiana before querying btpfacile.it, and the returned price SHALL be attributed to the original (placement) ISIN asset.

#### Scenario: Placement ISIN priced through btpfacile via market ISIN
- **WHEN** a spot price is requested for placement ISIN IT0005713539, Borsa Italiana fails, and btpfacile.it quotes market ISIN IT0005713547 at 100,30
- **THEN** the price fetched from the IT0005713547 page is returned as 1.003 for the IT0005713539 asset

### Requirement: btpfacile.it fallback for the daily official-close refresh
The system SHALL use btpfacile.it as a fallback source for the daily BOND price refresh when Borsa Italiana official closes are unavailable, parsing the quote and the "ultima quotazione" timestamp from the per-ISIN page, and SHALL store the result as a Price row with source `BTPFACILE` (normalized ÷100, dated by the parsed quote timestamp when plausible, else the run date). One row per asset per date per source SHALL exist.

#### Scenario: Daily refresh stores a BTPFACILE row when Borsa is down
- **WHEN** the daily bond refresh runs for a BOND asset, Borsa Italiana is unreachable, and btpfacile.it shows quote 99,58 with ultima quotazione 2026-11-26 17:35 for that ISIN
- **THEN** a Price row (0.9958, source BTPFACILE, price_type CLOSE, dated 2026-11-26) is appended for the asset, and no duplicate BTPFACILE row is added if the task runs again for the same date

#### Scenario: BTPFACILE and BORSA_ITALIANA rows coexist
- **WHEN** a Price row already exists for an asset and date with source BORSA_ITALIANA and the refresh later succeeds via btpfacile for the same date
- **THEN** both rows may exist (the unique constraint is per source) and the newest stored row remains the total-failure fallback

### Requirement: btpfacile.it failures are tolerated like other providers
The system SHALL treat any btpfacile.it error (non-200 status, timeout, connection error, unparseable HTML, missing price) as "no price from this provider" and continue down the fallback chain (Yahoo/Polygon, then stored Price row) without raising.

#### Scenario: btpfacile unreachable still values the holding
- **WHEN** both borsaitaliana.it and btpfacile.it are unreachable for a BOND asset but a stored Price row exists
- **THEN** get_price returns no live price and the portfolio view falls back to the stored Price row as before, without erroring

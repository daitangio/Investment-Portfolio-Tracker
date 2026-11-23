# etf-market-data Specification

## Purpose

Prices European ETFs held by ISIN via Borsa Italiana's ISIN-keyed ETFPlus pages, with venue-aware ISIN-to-ticker resolution and Yahoo-ticker-driven history, so EUR holdings integrate correctly with the FX and portfolio engines.

## Requirements

### Requirement: ETF spot price by ISIN from Borsa Italiana ETFPlus
When a spot price is requested for an ETF asset whose symbol is an ISIN, the system SHALL first try the Borsa Italiana ETFPlus scheda page keyed by that ISIN, and only fall back to ticker-based providers when that page yields no price. ETF prices SHALL be used as-is in EUR — the percent-of-nominal (÷100) normalization SHALL NOT be applied to ETF assets.

#### Scenario: ETFPlus ISIN priced in EUR without normalization
- **WHEN** a spot price is requested for ETF asset LU1900066033 whose ETFPlus last-trade quote is 81.39
- **THEN** the returned price is 81.39 EUR, not 0.8139 and not the Swiss-listing quote

#### Scenario: Borsa page unavailable falls back to the resolved ticker
- **WHEN** borsaitaliana.it is unreachable and the asset has a stored ticker (e.g. CHIP.MI)
- **THEN** the system falls back to the ticker-based provider chain and still returns the EUR price rather than failing

#### Scenario: Non-ISIN ETFs are unaffected
- **WHEN** a spot price is requested for an ETF asset keyed by a plain ticker (e.g. an ASX or US ETF)
- **THEN** the Borsa Italiana path is skipped entirely and pricing behaves exactly as before this change

### Requirement: Venue-aware ISIN-to-ticker resolution
When resolving an ISIN-keyed ETF to a provider ticker, the system SHALL prefer the Italian-market listing quoted in the asset's currency, and SHALL NOT persist a ticker whose provider-reported currency disagrees with the asset's currency. A repair run SHALL backfill existing ETF/ISIN assets that have no stored ticker using this rule.

#### Scenario: Italian listing preferred over first search hit
- **WHEN** ISIN LU1900066033 resolves to the Yahoo ticker and both a Swiss (CHIP.SW) and an Italian (CHIP.MI) listing exist
- **THEN** the stored ticker is the Italian listing CHIP.MI

#### Scenario: Currency mismatch is rejected
- **WHEN** the only candidate ticker's provider metadata reports a currency different from the asset currency
- **THEN** that ticker is not stored and no live ticker is persisted (the asset keeps falling back to Borsa ISIN pricing)

#### Scenario: Existing broken rows are repaired
- **WHEN** the backfill repair runs and ETF assets with ISIN symbols have no stored ticker (e.g. LU1900066033, IE00B1YZSC51)
- **THEN** their stored tickers are populated with the venue-aware resolution result

### Requirement: Historical prices for ISIN-keyed ETFs
The system SHALL fetch historical prices, chart candles, and prices at a specific past date for ISIN-keyed ETF assets using their resolved ticker, in the asset's currency, exactly as spot pricing already does.

#### Scenario: Chart history uses the resolved ticker
- **WHEN** daily chart history is requested for ETF asset LU1900066033 with stored ticker CHIP.MI
- **THEN** the history comes from CHIP.MI in EUR (e.g. ~253 daily closes per year), not from the raw ISIN

#### Scenario: Price at a past date works
- **WHEN** a portfolio or analytics calculation requests the closing price of LU1900066033 on a past trading day
- **THEN** a price is returned via the resolved ticker instead of an empty result

#### Scenario: Unresolvable ETF degrades gracefully
- **WHEN** an ISIN-keyed ETF has no stored ticker and no Borsa ETFPlus page exists
- **THEN** history requests return empty and the portfolio still values the holding from stored Price rows without error

### Requirement: Daily ETF official-close history rows
The system SHALL refresh ISIN-keyed ETF assets once per day at low priority, appending one Price row per asset per day from the Borsa Italiana official close in EUR, without modifying previously stored rows.

#### Scenario: Task appends daily history
- **WHEN** the daily refresh task runs for ETF asset LU1900066033 with a live official close
- **THEN** a new EUR Price row is appended for that date and previous rows are untouched

#### Scenario: Provider down leaves history intact
- **WHEN** the daily refresh runs while borsaitaliana.it is unreachable
- **THEN** existing Price rows are unchanged and no partial row is written

### Requirement: Regression — ETFPlus holdings valued live
The system SHALL value the ETFPLUS ETF holdings LU1900066033 and IE00B1YZSC51 with a fresh EUR spot price from Borsa Italiana (falling back to the resolved Yahoo ticker), converted to the reporting currency through the FX service, so prices no longer stall at the import-time snapshot.

#### Scenario: Portfolio shows a live ETF price
- **WHEN** the portfolio summary is computed after this change with the backfill applied
- **THEN** LU1900066033 shows a live EUR spot price (e.g. ~81.39) instead of the stale stored Price row, and market value converts to the reporting currency via the FX service

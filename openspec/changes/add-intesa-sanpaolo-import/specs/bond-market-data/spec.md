# Spec Delta

## Purpose

Lets the market data layer price fixed-income assets — specifically Italian government bonds held via Intesa Sanpaolo — by ISIN using Borsa Italiana MOT pages, with stored-price fallback, and resolve non-ASX ETF ISINs to Yahoo tickers.

## ADDED Requirements

### Requirement: Borsa Italiana spot price for BOND assets
The system SHALL fetch the spot price of a BOND asset from Borsa Italiana's per-ISIN MOT scheda page (`borsaitaliana.it/borsa/obbligazioni/mot/{type}/scheda/{ISIN}-MOTX.html`), where {type} is derived from the asset name (BTP, BOT, CCT, ...), parsing the server-rendered last-trade price and falling back to the official close.

#### Scenario: Sample BTP priced
- **WHEN** a spot price is requested for BOND asset IT0005622128
- **THEN** the returned price is approximately 99.5 (EUR, % of nominal), matching the MOT page

#### Scenario: Unknown bond type falls back
- **WHEN** the derived {type} path returns 404 or no price
- **THEN** the system falls through to the next provider and ultimately the stored Price row

### Requirement: MOT prices normalized to EUR per EUR of nominal
The system SHALL divide Borsa Italiana MOT quotes (which are % of nominal, e.g. 99.529) by 100, so that quantity (nominal EUR) × price = market value in EUR, consistent with import-time Price rows and cost basis.

#### Scenario: BTP market value is correct
- **WHEN** the spot price for IT0005622128 (last trade 99.529) is fetched while holding 10.000 EUR nominal
- **THEN** the price is 0.99529 and the computed market value is ≈ 9.952,90 EUR — not 995.290

### Requirement: Price caching and failure tolerance
The system SHALL cache Borsa Italiana responses in Redis like other providers, retry transient failures, and on total failure return the newest stored Price row for the asset rather than null when one exists.

#### Scenario: Site down still values the holding
- **WHEN** borsaitaliana.it is unreachable but a Price row exists for the ISIN
- **THEN** get_price returns the stored price and its date instead of failing the portfolio view

### Requirement: Snapshot market price stored as Price row
The system SHALL write each holding's Prezzo Mercato from the patrimoine file into the Price table (asset_id, EUR, as-of date) at import time, so the portfolio is valued even when live pricing is unavailable.

#### Scenario: Import stores prices
- **WHEN** the sample file is imported
- **THEN** 8 Price rows exist (one per holding) in EUR dated at the as-of date

### Requirement: Daily bond price refresh
The system SHALL provide a low-priority background task that refreshes BOND asset prices once a day from Borsa Italiana official closes and appends Price rows for history and charts.

#### Scenario: Task appends history
- **WHEN** the daily refresh task runs for a BOND asset with a live price
- **THEN** a new Price row is appended for that date and previous rows are untouched

### Requirement: ETF ISIN resolution to a Yahoo ticker
The system SHALL resolve a non-ASX ETF ISIN to a Yahoo Finance ticker once (via Yahoo's symbol search) at import time and store it on the Asset, so the existing Polygon → Yahoo chain can price the ETF.

#### Scenario: ETF priced after import
- **WHEN** an imported ETF asset (e.g. IE00B1YZSC51) is priced
- **THEN** the resolved ticker is used and a EUR price is returned instead of null

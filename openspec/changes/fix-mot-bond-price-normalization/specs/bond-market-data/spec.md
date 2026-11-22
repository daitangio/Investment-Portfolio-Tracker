# Spec Delta

## Purpose

Lets the market data layer price fixed-income assets — specifically Italian government bonds held via Intesa Sanpaolo — by ISIN using Borsa Italiana MOT pages and fallback providers (Yahoo, Polygon), with consistent %→per-EUR-of-nominal normalization across ALL sources, a quoted-price field for display, stored-price fallback, and daily refresh.

## ADDED Requirements

### Requirement: Consistent normalization across all price sources for BOND assets
The system SHALL return bond prices in EUR-per-EUR-of-nominal (raw MOT % quote ÷ 100) from EVERY price source: Borsa Italiana spot, Borsa Italiana official close, Yahoo Finance fallback, and Polygon fallback. When a fallback provider returns a raw price ≥ 10 for a BOND/ISIN symbol (indicating a % of nominal quote rather than a per-EUR price), the system SHALL divide it by 100.

#### Scenario: Borsa Italiana spot returns normalized price
- **WHEN** a spot price is requested for BOND asset IT0005735201 whose MOT last-trade quote is 101.70
- **THEN** the returned price is 1.017 (EUR per EUR of nominal)

#### Scenario: Yahoo fallback also returns normalized price
- **WHEN** Borsa Italiana is unreachable and the spot price for BOND asset IT0005735201 falls back to Yahoo Finance, which returns 101.70
- **THEN** the returned price is 1.017 (divided by 100), NOT 101.70

#### Scenario: Market value is correct regardless of source
- **WHEN** a holding of 3000 EUR nominal of IT0005735201 is valued at the normalized price 1.017
- **THEN** the market value is 3051 EUR (3000 × 1.017), not 305100

### Requirement: BOND prices displayed as % of nominal in the UI
The system SHALL display the bond price as the raw market quote (% of nominal, e.g. 101.70) in the frontend, derived from the normalized `last_price` (EUR per EUR of nominal) by multiplying by 100 when `asset_class == "BOND"`. The API only exposes `last_price`; the ×100 display conversion happens in the frontend.

#### Scenario: Bond price shown as 101.70 not 1.02
- **WHEN** the portfolio summary includes BOND asset IT0005735201 with normalized last_price 1.017
- **THEN** the UI Price column shows 101.70 (1.017 × 100) for that row

#### Scenario: Non-bond holdings show last_price directly
- **WHEN** the portfolio summary includes a non-BOND asset (e.g. ETF) with last_price 39.64
- **THEN** the UI Price column shows 39.64 (no ×100)

### Requirement: Historical prices and charts normalized for BOND assets
The system SHALL apply the same ÷100 normalization to historical OHLCV prices fetched from Yahoo/Polygon for BOND/ISIN symbols, so period return calculations and charts use consistent per-EUR prices.

#### Scenario: Period return uses normalized prices
- **WHEN** the period price return is computed for BOND asset IT0005735201 using Yahoo historical data where raw closes are ~101.70
- **THEN** the return is computed from normalized closes (~1.017), giving the correct percentage (e.g. +1.70%), not a 100× distorted value

### Requirement: Regression — IT0005735201 valued correctly
The system SHALL value IT0005735201 (3000 EUR nominal, cost basis 100% = 3000 EUR) at a MOT quote of 101.70 as: last_price 1.017 (displayed as 101.70 in the UI), market_value 3051 EUR, unrealized_gain_pct ≈ +1.70%.

#### Scenario: Full holding snapshot for IT0005735201
- **WHEN** the portfolio summary is computed for a holding of 3000 EUR nominal of IT0005735201 at MOT quote 101.70 with cost basis 3000 EUR
- **THEN** last_price ≈ 1.017 (UI shows 101.70), market_value ≈ 3051 EUR, unrealized_gain ≈ +51 EUR, unrealized_gain_pct ≈ +1.70%

### Requirement: Borsa Italiana spot price for BOND assets
The system SHALL fetch the spot price of a BOND asset from Borsa Italiana's per-ISIN MOT scheda page (`borsaitaliana.it/borsa/obbligazioni/mot/{type}/scheda/{ISIN}-MOTX.html`), where {type} is derived from the asset name (BTP, BOT, CCT, ...), parsing the server-rendered last-trade price and falling back to the official close.

#### Scenario: Sample BTP priced
- **WHEN** a spot price is requested for BOND asset IT0005622128
- **THEN** the returned price is approximately 0.995 (EUR per EUR of nominal, from MOT quote 99.529 ÷ 100)

### Requirement: MOT prices normalized to EUR per EUR of nominal
The system SHALL divide Borsa Italiana MOT quotes (which are % of nominal, e.g. 99.529) by 100, so that quantity (nominal EUR) × price = market value in EUR, consistent with import-time Price rows and cost basis.

#### Scenario: BTP market value is correct
- **WHEN** the spot price for IT0005622128 (last trade 99.529) is fetched while holding 10.000 EUR nominal
- **THEN** the price is 0.99529 and the computed market value is ≈ 9.952,90 EUR — not 995.290

### Requirement: Price caching and failure tolerance
The system SHALL cache price responses in Redis like other providers, retry transient failures, and on total failure return the newest stored Price row for the asset rather than null when one exists.

#### Scenario: Site down still values the holding
- **WHEN** borsaitaliana.it is unreachable but a Price row exists for the ISIN
- **THEN** get_price returns the stored price and its date instead of failing the portfolio view

### Requirement: Snapshot market price stored as Price row
The system SHALL write each holding's Prezzo Mercato from the patrimonio file into the Price table (asset_id, EUR, as-of date) at import time, so the portfolio is valued even when live pricing is unavailable.

#### Scenario: Import stores prices
- **WHEN** the sample file is imported
- **THEN** Price rows exist (one per holding) in EUR dated at the as-of date, with bond prices already normalized (÷100)

### Requirement: Daily bond price refresh
The system SHALL provide a low-priority background task that refreshes BOND asset prices once a day from Borsa Italiana official closes and appends normalized Price rows for history and charts.

#### Scenario: Task appends history
- **WHEN** the daily refresh task runs for a BOND asset with a live price
- **THEN** a new Price row is appended for that date (normalized ÷100) and previous rows are untouched

# Spec Delta

## ADDED Requirements

### Requirement: Quoted "N.A." cells never yield a price
The system SHALL parse a labeled quote field (ETFPlus "Closing Price", bond "Official Close") only from the table cell that belongs to its own row. A cell whose content is not a number — including "N.A." shown while the market is open — SHALL yield no price, never a value scanned from another cell, and the daily refresh SHALL then append no Price row for that asset.

#### Scenario: Mid-session ETF scheda yields no closing price
- **WHEN** the ETF scheda page for IE00B1YZSC51 shows last trade 39.27 and "Closing Price" = "N.A." during market hours
- **THEN** the closing-price parse returns None (not 19.00), and the daily refresh appends no row for that asset

#### Scenario: Post-close ETF scheda still quotes the real closing price
- **WHEN** the ETF scheda page for IE00B1YZSC51 shows "Closing Price" = 38.91 after the session close
- **THEN** the parsed closing price is 38.91 EUR per share

#### Scenario: Bond official close stays cell-bounded
- **WHEN** a bond scheda page renders the "Official Close" value cell as "N.A." or empty
- **THEN** the official close parse returns None instead of a numeric value from a later cell

#### Scenario: Valuation fallback never sees garbage closes
- **WHEN** an ETF has no live price and its newest stored Price row predates a refresh run that hit an N.A. scheda
- **THEN** stored-price fallback uses the older correct row, because the N.A. run appended nothing

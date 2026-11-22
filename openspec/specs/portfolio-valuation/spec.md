# Portfolio Valuation Specification

## Purpose

Defines how the portfolio engine values holdings and computes cost basis, market value, and unrealized P/L in the user's display currency, while keeping AUD as the ATO reporting base with historical FX rates.

## Requirements

### Requirement: Cost basis displayed in lot currency when it matches display currency
The system SHALL compute cost basis in the display currency directly from the lot's original currency when the two match (e.g. EUR asset displayed in EUR), without routing through the AUD pivot. This prevents FX-rate drift between the historical acquisition rate and the current rate from distorting the displayed cost basis.

#### Scenario: EUR bond cost basis shown in EUR
- **WHEN** a holding of 3000 EUR nominal of IT0005735201 was bought at 100% (cost 3000 EUR, no fees) and the display currency is EUR
- **THEN** the displayed total_cost_basis is exactly 3000.00 EUR, not 3000 × fx_hist / fx_current (e.g. 2907.60)

#### Scenario: AUD display still uses historical FX for ATO compliance
- **WHEN** the same EUR holding is displayed in AUD
- **THEN** the cost basis in AUD uses the historical EUR→AUD rate at the acquisition date (e.g. 3000 × 1.65 = 4950 AUD), as required for ATO tax reporting

### Requirement: Unrealized gain consistent between holding and portfolio totals
The system SHALL compute per-holding unrealized gain as `market_value_display − cost_basis_display` (both in display currency), so holding-level gains always sum to the portfolio-level total_unrealized_gain in the same currency.

#### Scenario: Holding gain matches total gain
- **WHEN** a portfolio has a single holding with market_value 3051 EUR and cost_basis 3000 EUR displayed in EUR
- **THEN** the holding's unrealized_gain is +51 EUR and total_unrealized_gain is also +51 EUR

### Requirement: Market value uses current FX for both legs
The system SHALL compute market value by converting the current price from the asset's quote currency to AUD at the current rate, then to the display currency at the current rate, so the round-trip cancels and market value equals quantity × price in the asset's currency when display matches.

#### Scenario: Market value unaffected by FX drift
- **WHEN** a holding of 3000 EUR nominal is priced at 1.017 EUR per EUR nominal and displayed in EUR
- **THEN** market_value is 3051 EUR regardless of the EUR→AUD exchange rate

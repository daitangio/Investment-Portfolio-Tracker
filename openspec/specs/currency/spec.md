# Currency Support Specification

## Purpose

This specification defines the requirements for multi-currency support in the InvestIQ portfolio tracker, with full EUR (Euro) support alongside AUD and USD. The system enables users to view and manage portfolios in their preferred display currency with proper localization, formatting, and conversion.

## Requirements

### Requirement: Display Currency Type Support
The system SHALL support EUR as a valid display currency type throughout the frontend.

#### Scenario: Type definition includes EUR
- **WHEN** the frontend type system is evaluated
- **THEN** `DisplayCurrency` type includes "AUD" | "USD" | "EUR"

#### Scenario: Type used consistently
- **WHEN** currency types are used in components
- **THEN** all components use the `DisplayCurrency` union type

### Requirement: Currency Selection UI
The system SHALL provide a user interface for selecting display currency.

#### Scenario: Dropdown selector available
- **WHEN** user accesses the currency selection in TopBar
- **THEN** a dropdown menu displays all three currencies: AUD, USD, EUR

#### Scenario: Currency selection updates display
- **WHEN** user selects EUR from the dropdown
- **THEN** all portfolio values immediately update to display in EUR

#### Scenario: Selection persists
- **WHEN** user selects EUR and reloads the page
- **THEN** the selection persists in localStorage

### Requirement: EUR Currency Formatting
The system SHALL format EUR amounts using it-IT locale conventions.

#### Scenario: EUR amounts format correctly
- **WHEN** formatting a EUR amount of 1234.56
- **THEN** the output is "€1.234,56" (period as thousand separator, comma as decimal)

#### Scenario: AUD and USD formatting unchanged
- **WHEN** formatting AUD or USD amounts
- **THEN** existing formatting conventions are preserved

### Requirement: EUR Symbol Display
The system SHALL display the € symbol for EUR-denominated holdings.

#### Scenario: EUR holdings show € prefix
- **WHEN** displaying a EUR-denominated holding
- **THEN** the currency label shows "€" prefix

#### Scenario: Other currencies unchanged
- **WHEN** displaying AUD or USD holdings
- **THEN** existing currency symbols (A$, US$) are preserved

### Requirement: Backend FX Service EUR Support
The system SHALL support EUR currency conversions through the FXService.

#### Scenario: EUR to AUD conversion
- **WHEN** requesting FX rate from EUR to AUD
- **THEN** FXService returns valid rate (via Yahoo Finance EURAUD=X or RBA FXREUR)

#### Scenario: AUD to EUR conversion
- **WHEN** requesting FX rate from AUD to EUR
- **THEN** FXService returns valid rate

#### Scenario: EUR to USD cross-rate
- **WHEN** requesting FX rate from EUR to USD
- **THEN** FXService returns valid cross-rate (EUR→AUD→USD via pivot)

### Requirement: Portfolio Engine EUR Conversion
The system SHALL convert portfolio values to EUR display currency correctly.

#### Scenario: Portfolio converts to EUR
- **WHEN** requesting portfolio with display_currency="EUR"
- **THEN** PortfolioEngine converts all values via AUD pivot (Any→AUD→EUR)

#### Scenario: EUR portfolio values accurate
- **WHEN** viewing EUR-denominated portfolio
- **THEN** values match expected EUR amounts with correct formatting

### Requirement: API Endpoint Currency Parameter Support
The system SHALL accept EUR as a valid currency parameter in all relevant API endpoints.

#### Scenario: Portfolio endpoints accept EUR
- **WHEN** calling `/api/v1/portfolio/summary` with currency=EUR
- **THEN** endpoint returns portfolio values in EUR

#### Scenario: Analytics endpoints accept EUR
- **WHEN** calling `/api/v1/analytics` with currency=EUR
- **THEN** endpoint returns analytics in EUR

#### Scenario: Query descriptions updated
- **WHEN** viewing API documentation
- **THEN** currency parameter descriptions show "(AUD|USD|EUR)"

### Requirement: EUR Test Coverage
The system SHALL include comprehensive test coverage for EUR currency support.

#### Scenario: EUR FX rates tested
- **WHEN** running _FakeFXService tests
- **THEN** EUR conversion rates are consistent (EUR→AUD * AUD→EUR = 1)

#### Scenario: EUR portfolio conversion tested
- **WHEN** running portfolio currency tests
- **THEN** EUR display currency conversion passes

#### Scenario: EUR portfolio values verified
- **WHEN** testing EUR portfolio display
- **THEN** cross-check validates: AUD value * (AUD→EUR rate) = EUR value

## Constraints

1. **No Breaking Changes**: Existing AUD/USD functionality must remain intact
2. **AUD Pivot**: All conversions continue to use AUD as the intermediate pivot currency
3. **Backend First**: FXService already supports EUR; frontend is the primary change target
4. **Locale Consistency**: Use it-IT for EUR to match regional conventions
5. **No Database Migration**: Existing String(3) currency fields already support "EUR"
6. **No localStorage Migration**: Existing display_currency values ("AUD", "USD") remain valid

## Acceptance Criteria

### Frontend
- [x] `DisplayCurrency` type includes "EUR"
- [x] Dropdown selector allows choosing EUR
- [x] EUR selection persists in localStorage
- [x] EUR amounts format as "€1.234,56" (it-IT locale)
- [x] EUR holdings display with "€" prefix

### Backend
- [x] FXService can fetch EUR/AUD and EUR/USD rates
- [x] Portfolio engine converts to EUR correctly
- [x] All API endpoints accept EUR as display_currency parameter
- [x] Tests cover EUR conversion scenarios

### Integration
- [x] User can switch to EUR and see correctly formatted portfolio values
- [x] No errors when displaying EUR-denominated assets
- [x] Toggle between AUD, USD, EUR works without page reload

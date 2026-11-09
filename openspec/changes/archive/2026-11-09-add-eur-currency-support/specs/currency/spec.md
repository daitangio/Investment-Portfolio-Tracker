# Currency Support Specification — EUR Addition

## Overview

This specification defines the requirements for adding EUR (Euro) as a supported currency in the InvestIQ portfolio tracker.

## Requirements

### Frontend Requirements

#### Currency Type
- The `DisplayCurrency` type MUST include "EUR" as a valid value
- Type definition location: `frontend/src/lib/context/CurrencyContext.tsx`
- Type: `type DisplayCurrency = "AUD" | "USD" | "EUR"`

#### Currency Selection
- Users MUST be able to select EUR as their display currency
- The currency selector MUST be a dropdown menu (not a toggle) when 3+ currencies are available
- Dropdown location: `frontend/src/components/layout/TopBar.tsx`
- Dropdown options: AUD, USD, EUR (in that order)

#### Currency Formatting
- EUR amounts MUST be formatted using the `it-IT` locale
- Formatting function: `formatCurrency()` in `frontend/src/lib/utils/formatters.ts`
- Expected output: "€1.234,56" (period as thousand separator, comma as decimal)
- The `formatCurrency()` function MUST accept "EUR" as a valid currency parameter

#### Currency Symbol Display
- EUR holdings MUST display with the "€" symbol prefix
- Location: `frontend/src/components/portfolio/HoldingsTable.tsx`
- Mapping: `origCcy === "EUR"` → "€" prefix

### Backend Requirements

#### FX Service
- EUR MUST be supported for FX rate lookups via Yahoo Finance
- Pair: EURAUD=X (1 EUR = X AUD)
- EUR MUST be supported for FX rate lookups via RBA fallback
- RBA series ID: FXREUR (already present in RBA_SERIES_ID)

#### Portfolio Engine
- Portfolio values MUST convert correctly to EUR display currency
- Conversion path: Any currency → AUD → EUR (via cross-rate)
- Method: `PortfolioEngine._hydrate_with_prices()` with `display_currency="EUR"`

#### API Endpoints
- All endpoints accepting `currency` or `display_currency` query parameters MUST accept "EUR"
- Affected routers:
  - `backend/routers/portfolio.py`
  - `backend/routers/analytics.py`
- Query parameter descriptions MUST be updated from "(AUD|USD)" to "(AUD|USD|EUR)" or generic text

### Data Requirements

#### Database Schema
- No schema changes required
- Existing `String(3)` currency fields already support "EUR"

#### LocalStorage
- Existing `display_currency` values ("AUD", "USD") MUST remain valid
- No migration required
- New users can store "EUR" as display_currency

### Test Requirements

#### Backend Tests
- Test EUR FX rate fetching via FXService
- Test EUR portfolio conversion in portfolio_engine
- Test EUR display in analytics_engine
- Update `_FakeFXService` in `test_portfolio_currency.py` to handle EUR conversions

#### Frontend Tests
- Test EUR selection in currency dropdown
- Test EUR formatting output
- Test EUR symbol display in holdings table

## Constraints

1. **No Breaking Changes**: Existing AUD/USD functionality must remain intact
2. **AUD Pivot**: All conversions continue to use AUD as the intermediate pivot currency
3. **Backend First**: FXService already supports EUR; frontend is the primary change target
4. **Locale Consistency**: Use it-IT for EUR to match regional conventions

## Acceptance Criteria

### Frontend
- [ ] `DisplayCurrency` type includes "EUR"
- [ ] Dropdown selector allows choosing EUR
- [ ] EUR selection persists in localStorage
- [ ] EUR amounts format as "€1.234,56" (it-IT locale)
- [ ] EUR holdings display with "€" prefix

### Backend
- [ ] FXService can fetch EUR/AUD and EUR/USD rates
- [ ] Portfolio engine converts to EUR correctly
- [ ] All API endpoints accept EUR as display_currency parameter
- [ ] Tests cover EUR conversion scenarios

### Integration
- [ ] User can switch to EUR and see correctly formatted portfolio values
- [ ] No errors when displaying EUR-denominated assets
- [ ] Toggle between AUD, USD, EUR works without page reload

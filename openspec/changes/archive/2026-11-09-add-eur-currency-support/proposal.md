# Proposal: Add EUR Currency Support

## Summary

Remove the binary AUD/USD currency assumption and add EUR (Euro) as a fully supported display and transaction currency alongside AUD and USD.

## Motivation

The application currently has hardcoded assumptions that only AUD and USD are valid currencies. This is evident in:
- Frontend type definition: `type DisplayCurrency = "AUD" | "USD"`
- UI components that toggle only between AUD and USD
- Currency formatting that assumes only two locales (en-AU, en-US)

However, the backend is already multi-currency capable:
- FXService supports EUR via RBA series ID `FXREUR` and Yahoo Finance
- All currency fields in models are generic `String(3)` 
- Portfolio engine uses generic currency codes for conversions

Adding EUR support enables European investors using the platform (particularly Australians with European holdings) to view their portfolios in EUR.

## Goals

- [ ] Users can select EUR as their display currency
- [ ] All portfolio values convert correctly to EUR via the AUD pivot
- [ ] EUR amounts format with Italian locale (it-IT) conventions
- [ ] Currency selection uses a dropdown instead of toggle (scalable to 3+ currencies)
- [ ] No breaking changes to existing AUD/USD functionality
- [ ] No database migration required

## Non-Goals

- Adding other currencies (GBP, JPY, CAD, etc.) — this change focuses on EUR only
- Changing default currency from AUD
- Modifying the AUD-centric FX conversion architecture
- Supporting EUR as a transaction currency in database models (already supported via String(3))

## Success Criteria

1. Frontend type `DisplayCurrency` includes "EUR"
2. Users can select EUR from currency dropdown in TopBar
3. EUR-denominated portfolios display with € symbol and it-IT formatting
4. FX conversions for EUR work correctly (EUR→AUD and cross-rate calculations)
5. Existing AUD/USD users experience no disruption
6. Backend tests cover EUR conversion scenarios

## Assumptions

- EUR FX rates are available via Yahoo Finance (EURAUD=X, EURUSD=X) and RBA (FXREUR)
- it-IT locale is acceptable for EUR formatting (€1.234,56)
- No migration needed for existing localStorage display_currency values
- Backend FXService already handles EUR correctly (verified: RBA_SERIES_ID includes EUR)

## Dependencies

- Backend: FXService, portfolio_engine, analytics_engine (already EUR-capable)
- Frontend: CurrencyContext, formatters, TopBar, HoldingsTable

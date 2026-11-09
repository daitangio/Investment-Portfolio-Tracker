# Design: Add EUR Currency Support

## Architecture Overview

The backend is already multi-currency capable. The primary changes are in the frontend type system and UI components.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        CURRENCY FLOW (Current)                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  User selects: AUD ──────► DisplayCurrency type (AUD|USD)             │
│                                  │                                      │
│  User selects: USD ──────► Toggle switches between two options          │
│                                  │                                      │
│  Format: AUD ───────────► en-AU locale ──────► "$1,234.56"            │
│  Format: USD ───────────► en-US locale ──────► "$1,234.56"            │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                      CURRENCY FLOW (After EUR)                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  User selects: AUD/USD/EUR ──► DisplayCurrency type (AUD|USD|EUR)      │
│                                  │                                      │
│  User selects via: ───────────► Dropdown menu with 3 options            │
│                                  │                                      │
│  Format: AUD ───────────► en-AU locale ──────► "$1,234.56"            │
│  Format: USD ───────────► en-US locale ──────► "$1,234.56"            │
│  Format: EUR ───────────► it-IT locale ──────► "€1.234,56"            │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## Component Changes

### 1. CurrencyContext.tsx

**Current:**
```typescript
type DisplayCurrency = "AUD" | "USD";

const toggleCurrency = useCallback(() => {
  setCurrency(displayCurrency === "AUD" ? "USD" : "AUD");
}, [displayCurrency, setCurrency]);
```

**After:**
```typescript
type DisplayCurrency = "AUD" | "USD" | "EUR";

// toggleCurrency removed or repurposed
const setCurrency = useCallback((c: DisplayCurrency) => {
  setDisplayCurrency(c);
  localStorage.setItem("display_currency", c);
}, []);
```

**Rationale:** 
- Type extended to include EUR
- Toggle logic replaced with direct `setCurrency` since dropdown doesn't need toggle
- No localStorage migration needed (existing values still valid)

### 2. TopBar.tsx

**Current:**
```tsx
const { displayCurrency, toggleCurrency } = useCurrency();
// Button with onClick={toggleCurrency}
title={`Display in ${displayCurrency === "AUD" ? "USD" : "AUD"}`}
```

**After:**
```tsx
const { displayCurrency, setCurrency } = useCurrency();
const currencies: DisplayCurrency[] = ["AUD", "USD", "EUR"];

// Dropdown component
<select 
  value={displayCurrency}
  onChange={(e) => setCurrency(e.target.value as DisplayCurrency)}
>
  {currencies.map(ccy => (
    <option key={ccy} value={ccy}>{ccy}</option>
  ))}
</select>
```

**Rationale:**
- Dropdown is more scalable than toggle for 3+ currencies
- Allows direct selection of any currency
- Maintains same persistence mechanism (localStorage)

### 3. formatters.ts

**Current:**
```typescript
export function formatCurrency(
  value: number,
  compact = false,
  currency = "AUD",
): string {
  const locale = currency === "AUD" ? "en-AU" : "en-US";
  // ...
}
```

**After:**
```typescript
export function formatCurrency(
  value: number,
  compact = false,
  currency = "AUD",
): string {
  const localeMap: Record<string, string> = {
    "AUD": "en-AU",
    "USD": "en-US",
    "EUR": "it-IT",
  };
  const locale = localeMap[currency] || "en-AU";
  // ...
}
```

**Rationale:**
- Extensible locale mapping
- it-IT provides authentic EUR formatting (€1.234,56)
- Fallback to en-AU for unknown currencies (shouldn't happen with type system)

### 4. HoldingsTable.tsx

**Current:**
```typescript
const ccyLabel = origCcy === "USD" ? "US$" : origCcy === "AUD" ? "A$" : `${origCcy} `;
```

**After:**
```typescript
const ccyLabel = 
  origCcy === "USD" ? "US$" : 
  origCcy === "AUD" ? "A$" :
  origCcy === "EUR" ? "€" :
  `${origCcy} `;
```

**Rationale:**
- Add EUR symbol prefix
- Maintains existing pattern for other currencies

### 5. Backend Router Descriptions

**Current:**
```python
currency: Optional[str] = Query(None, description="Display currency (AUD|USD)")
```

**After:**
```python
currency: Optional[str] = Query(None, description="Display currency (AUD|USD|EUR)")
```

**Files affected:**
- `backend/routers/portfolio.py` (multiple endpoints)
- `backend/routers/analytics.py` (multiple endpoints)

### 6. Test Updates

**File:** `backend/tests/test_portfolio_currency.py`

**Current:** `_FakeFXService` only handles USD/AUD conversions

**After:** Extend to handle EUR:
```python
async def get_rate_on_date(self, from_currency, to_currency="AUD", on_date=None):
    from_c = self._normalize_currency(from_currency)
    to_c = self._normalize_currency(to_currency)
    if from_c == to_c:
        return Decimal("1.0")
    if from_c == "USD" and to_c == "AUD":
        return Decimal("1.7")
    if from_c == "AUD" and to_c == "USD":
        return Decimal("0.5882352941")
    if from_c == "EUR" and to_c == "AUD":
        return Decimal("1.60")  # Example rate
    if from_c == "AUD" and to_c == "EUR":
        return Decimal("0.625")  # 1/1.60
    raise AssertionError(f"Unexpected FX lookup {from_currency}/{to_currency}")
```

Add new test case:
```python
async def test_eur_display_currency_conversion(self):
    # Verify EUR conversion works end-to-end
    pass
```

## Data Flow

### EUR Portfolio Display

```
User Request (display_currency="EUR")
         │
         ▼
┌─────────────────────────────────────┐
│  Portfolio Engine                    │
│  _hydrate_with_prices(display_ccy)   │
└────────────────┬────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────┐
│  For each holding:                   │
│  - Get price in asset currency       │
│  - Convert to AUD (via fx_rate)     │
│  - Convert AUD to EUR (via fx_rate)  │
│  - Format with it-IT locale          │
└─────────────────────────────────────┘
         │
         ▼
   €1.234,56 (formatted EUR value)
```

### FX Rate Lookup for EUR

```
EUR → AUD Conversion:
  Primary: Yahoo Finance EURAUD=X
  Fallback: RBA FXREUR series
  Cross-rate: EUR→USD + USD→AUD (if direct not available)

EUR → EUR Conversion:
  Return 1.0 (same currency)
```

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| EUR locale | it-IT | Authentic EUR formatting, period/comma separators |
| Currency selector | Dropdown | More scalable than toggle for 3+ currencies |
| localStorage migration | None | Existing "AUD"/"USD" values remain valid |
| EUR symbol | € prefix | Matches European conventions |
| Type extension | Union type | Simple, type-safe, minimal change |

## Non-Decisions

| Item | Status | Notes |
|------|--------|-------|
| Other currencies (GBP, JPY) | Out of scope | This change focuses on EUR only |
| Default currency change | Out of scope | AUD remains default |
| AUD pivot architecture | Out of scope | Existing architecture works for EUR |

## Risk Assessment

### Low Risk ✅
- Backend already supports EUR (FXService, portfolio_engine)
- Database schema already supports EUR (String(3))
- Type system change is additive (no breaking changes)

### Medium Risk ⚠️
- Dropdown UX change in TopBar (different interaction pattern)
- it-IT locale formatting (user expectation of number formats)

### Mitigation
- Keep toggle behavior available if users prefer (optional)
- Document EUR formatting in UI help text
- Test with actual EUR-denominated assets

## Rollback Plan

If issues arise:
1. Revert frontend type to `"AUD" | "USD"`
2. Revert dropdown to toggle
3. Remove EUR from locale mapping
4. Revert router descriptions

No database migration = trivial rollback

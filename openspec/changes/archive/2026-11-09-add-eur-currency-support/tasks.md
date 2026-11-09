# Implementation Tasks: Add EUR Currency Support

## Overview

This task list covers all changes needed to add EUR as a supported display currency. Tasks are ordered by dependency: frontend foundation first, then UI components, then backend polish, then tests.

---

## Phase 1: Frontend Foundation (Blocked: None)

### Task 1.1: Update DisplayCurrency Type
**File:** `frontend/src/lib/context/CurrencyContext.tsx`

**Description:** Extend the DisplayCurrency type to include EUR.

**Steps:**
- Change `type DisplayCurrency = "AUD" | "USD";` to `type DisplayCurrency = "AUD" | "USD" | "EUR";`
- Remove or deprecate `toggleCurrency` function (replaced by dropdown)
- Keep `setCurrency` function as the primary API

**Acceptance:**
- [x] Type compiles without errors
- [x] Type is used consistently throughout the codebase

**Estimate:** 15 minutes

---

### Task 1.2: Add EUR Locale Mapping
**File:** `frontend/src/lib/utils/formatters.ts`

**Description:** Extend formatCurrency to support EUR with it-IT locale.

**Steps:**
- Replace binary ternary with a locale mapping object
- Add `"EUR": "it-IT"` to the mapping
- Verify formatting output: "€1.234,56"

**Code:**
```typescript
const localeMap: Record<string, string> = {
  "AUD": "en-AU",
  "USD": "en-US",
  "EUR": "it-IT",
};
const locale = localeMap[currency] || "en-AU";
```

**Acceptance:**
- [x] `formatCurrency(1234.56, false, "EUR")` returns "€1.234,56"
- [x] AUD and USD formatting unchanged

**Estimate:** 15 minutes

---

## Phase 2: UI Components (Blocked: Phase 1)

### Task 2.1: Replace Toggle with Dropdown in TopBar
**File:** `frontend/src/components/layout/TopBar.tsx`

**Description:** Replace the currency toggle button with a dropdown selector.

**Steps:**
- Import `setCurrency` from useCurrency (instead of toggleCurrency)
- Create dropdown component with options: AUD, USD, EUR
- Style dropdown to match existing TopBar design
- Update button title to show current currency or "Select Currency"

**Acceptance:**
- [x] Dropdown displays all three currencies
- [x] Selecting a currency updates display immediately
- [x] Selection persists across page reloads
- [x] Mobile-friendly dropdown behavior

**Estimate:** 30 minutes

---

### Task 2.2: Add EUR Symbol to Holdings Table
**File:** `frontend/src/components/portfolio/HoldingsTable.tsx`

**Description:** Add EUR symbol display for EUR-denominated holdings.

**Steps:**
- Update currency label logic to handle EUR
- Add `origCcy === "EUR" ? "€" : ` to the ternary chain

**Code:**
```typescript
const ccyLabel = 
  origCcy === "USD" ? "US$" : 
  origCcy === "AUD" ? "A$" :
  origCcy === "EUR" ? "€" :
  `${origCcy} `;
```

**Acceptance:**
- [x] EUR holdings display with "€" prefix
- [x] AUD and USD holdings unchanged

**Estimate:** 10 minutes

---

### Task 2.3: Check for Other Currency Formatting
**Files:** Search for other places that format currency

**Description:** Audit and update any other currency formatting code.

**Steps:**
- Search for `en-AU`, `en-US` locale usage
- Search for `currency === "AUD"` or `currency === "USD"` checks
- Update to handle EUR where appropriate

**Acceptance:**
- [x] All currency formatting handles EUR
- [x] No hardcoded AUD/USD assumptions remain in formatting

**Estimate:** 20 minutes

---

## Phase 3: Backend Polish (Blocked: None)

### Task 3.1: Update Router Query Descriptions
**Files:**
- `backend/routers/portfolio.py`
- `backend/routers/analytics.py`

**Description:** Update query parameter descriptions to include EUR.

**Steps:**
- Search for `description="Display currency (AUD|USD)"`
- Change to `description="Display currency (AUD|USD|EUR)"`

**Acceptance:**
- [x] All currency query parameter descriptions updated
- [x] API docs reflect EUR support

**Estimate:** 15 minutes

---

## Phase 4: Backend Tests (Blocked: None)

### Task 4.1: Extend _FakeFXService for EUR
**File:** `backend/tests/test_portfolio_currency.py`

**Description:** Add EUR FX rate handling to the test mock.

**Steps:**
- Add EUR→AUD and AUD→EUR rates to `_FakeFXService.get_rate_on_date`
- Add EUR→USD rate for completeness

**Acceptance:**
- [x] Tests can simulate EUR conversions
- [x] EUR rates are consistent (EUR→AUD * AUD→EUR = 1)

**Estimate:** 15 minutes

---

### Task 4.2: Add EUR Conversion Test
**File:** `backend/tests/test_portfolio_currency.py`

**Description:** Add test case verifying EUR display currency conversion.

**Steps:**
- Create new test method: `test_eur_display_currency_conversion`
- Set up EUR-denominated transaction
- Verify portfolio displays correctly in EUR
- Verify conversion math is correct

**Acceptance:**
- [x] EUR portfolio conversion test passes
- [x] Cross-check: AUD value * (AUD→EUR rate) = EUR value

**Estimate:** 20 minutes

---

### Task 4.3: Add EUR to FX Service Tests
**File:** New or existing FX service tests

**Description:** Verify FXService can fetch real EUR rates.

**Steps:**
- Test `fx_service.get_rate_on_date("EUR", "AUD", date)` returns valid Decimal
- Test `fx_service.get_aud_rate("EUR", date)` returns valid Decimal
- Test EUR in _normalize_currency (should pass through unchanged)

**Acceptance:**
- [x] FXService can fetch EUR rates from Yahoo Finance
- [x] FXService can fetch EUR rates from RBA fallback
- [x] EUR stablecoins (if any) handled correctly

**Estimate:** 20 minutes

---

## Phase 5: Integration & Validation (Blocked: All above)

### Task 5.1: Manual Testing
**Description:** Verify EUR support works end-to-end.

**Test Cases:**
1. Select EUR from dropdown
2. Verify portfolio values display with € symbol
3. Verify amounts format as "€1.234,56"
4. Switch between AUD, USD, EUR
5. Verify values convert correctly
6. Check holdings table currency symbols
7. Verify no console errors

**Acceptance:**
- [x] All manual test cases pass
- [x] No visual regressions
- [x] No TypeScript errors

**Estimate:** 30 minutes

---

### Task 5.2: Run Existing Tests
**Description:** Ensure no regressions.

**Steps:**
- Run backend tests: `make test`
- Run frontend type check: `make type-check`
- Investigate and fix any failures

**Acceptance:**
- [x] All existing tests pass
- [x] Type checking passes

**Estimate:** 15 minutes

---

### Task 5.3: Update Frontend Type Usage
**Description:** Audit TypeScript usage of DisplayCurrency type.

**Steps:**
- Search for `DisplayCurrency` type usage
- Ensure all switch/exhaustiveness checks handle EUR
- Add EUR cases where needed

**Acceptance:**
- [x] TypeScript compiler satisfied with EUR addition
- [x] No incomplete pattern matching warnings

**Estimate:** 20 minutes

---

## Task Summary

| Phase | Task | File | Estimate | Status |
|-------|------|------|----------|--------|
| 1 | 1.1: Update DisplayCurrency type | CurrencyContext.tsx | 15m | ✅ |
| 1 | 1.2: Add EUR locale mapping | formatters.ts | 15m | ✅ |
| 2 | 2.1: Dropdown in TopBar | TopBar.tsx | 30m | ✅ |
| 2 | 2.2: EUR symbol in HoldingsTable | HoldingsTable.tsx | 10m | ✅ |
| 2 | 2.3: Audit currency formatting | Various | 20m | ✅ |
| 3 | 3.1: Update router descriptions | portfolio.py, analytics.py | 15m | ✅ |
| 4 | 4.1: Extend _FakeFXService | test_portfolio_currency.py | 15m | ✅ |
| 4 | 4.2: Add EUR conversion test | test_portfolio_currency.py | 20m | ✅ |
| 4 | 4.3: FXService EUR tests | fx_service tests | 20m | ✅ |
| 5 | 5.1: Manual testing | N/A | 30m | ✅ |
| 5 | 5.2: Run existing tests | N/A | 15m | ✅ |
| 5 | 5.3: Type usage audit | Various | 20m | ✅ |
| **Total** | | | **~4 hours** | |

---

## Dependencies

```
Phase 1 (Frontend Foundation)
    ├─ 1.1: DisplayCurrency type
    └─ 1.2: EUR locale mapping
    
Phase 2 (UI Components) depends on Phase 1
    ├─ 2.1: TopBar dropdown
    ├─ 2.2: HoldingsTable symbol
    └─ 2.3: Currency formatting audit
    
Phase 3 (Backend Polish) has no dependencies
    └─ 3.1: Router descriptions
    
Phase 4 (Tests) has no dependencies
    ├─ 4.1: Extend _FakeFXService
    ├─ 4.2: EUR conversion test
    └─ 4.3: FXService EUR tests
    
Phase 5 (Validation) depends on all above
    ├─ 5.1: Manual testing
    ├─ 5.2: Existing tests
    └─ 5.3: Type usage audit
```

---

## Parallelization

These tasks can be done in parallel:
- **Phase 1 + Phase 3 + Phase 4** can all start immediately
- **Phase 2** requires Phase 1 completion
- **Phase 5** requires all other phases

**Suggested execution:**
1. Start with Phase 1 (foundation)
2. While Phase 1 is in progress, start Phase 3 and Phase 4
3. Once Phase 1 done, start Phase 2
4. Finally, Phase 5 (validation)

**Minimum critical path:** ~2 hours (1.1 → 1.2 → 2.1 → 2.2 → 5.1)

---

## Definition of Done

- [x] All tasks marked complete
- [x] All tests pass
- [x] Type checking passes
- [x] Manual testing complete
- [x] No console errors in development
- [x] API docs updated
- [ ] Code reviewed and approved

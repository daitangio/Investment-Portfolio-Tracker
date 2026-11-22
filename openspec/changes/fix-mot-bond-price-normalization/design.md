# Design

## Context

Bond assets (BTP/BOT/etc.) are keyed by ISIN and priced from Borsa Italiana MOT, which quotes prices as % of nominal (e.g. 101.70). The system normalizes these by ÷100 so that `quantity (nominal EUR) × price = market value EUR`. Currently only the Borsa scraping path applies this normalization; Yahoo/Polygon fallback paths for ISIN symbols return raw prices (e.g. 101.70), causing 100× errors when Borsa is down. The UI also displays the normalized price (1.02) rather than the market-convention quote (101.70). See proposal.md for the full bug report (IT0005735201 showing P/L +143 at price 1.02 instead of value 3051 at quote 101.70).

## Goals / Non-Goals

**Goals:**
- All price sources for BOND/ISIN symbols return EUR-per-EUR-of-nominal (÷100 from % quote)
- Frontend displays `last_price × 100` for BOND rows (raw % quote) while the API keeps only the normalized `last_price`
- Historical prices and charts for bond ISINs are also normalized
- Regression test locks in correct values for IT0005735201

**Non-Goals:**
- Changing the Price table schema or stored values (existing rows are already normalized)
- Changing the ISP import normalization (already correct: ÷100)
- Supporting non-Italian bond markets
- Changing the portfolio engine's FIFO/cost-basis math

## Decisions

### Decision 1: Where to apply the ÷100 normalization for fallback providers
**Chosen:** Apply normalization at the point where prices are returned for BOND/ISIN symbols, in `MarketDataService`. Specifically, add a helper `_normalize_bond_price(price, asset_class, symbol)` that divides by 100 when `asset_class == "BOND"` or the symbol matches the ISIN regex AND the raw price ≥ 10 (heuristic: MOT % quotes are always ≥ 10 for Italian govt bonds; per-EUR prices would be < 10). Apply this in `_get_equity_price`, `_get_batch_equity_prices`, `_get_equity_history`, `_yahoo_chart_history`, and `_yahoo_spot` when the symbol is an ISIN/BOND.

**Alternative considered:** Normalize only in the portfolio engine when computing market_value for BOND assets. Rejected because historical prices, charts, and period returns also consume these prices and would need the same logic scattered across multiple call sites.

**Alternative considered:** Always divide ISIN prices by 100 unconditionally. Rejected because some ISINs (ETFs like IE00B1YZSC51) are NOT bonds and Yahoo returns a normal per-unit price (e.g. 39.64) — dividing by 100 would break them. The `asset_class == "BOND"` guard (passed via `symbol_meta`) is the reliable discriminator; the ≥10 heuristic is a safety net for when asset_class is unknown.

### Decision 2: How to display bond prices in the frontend
**Chosen:** Frontend multiplies `last_price × 100` for BOND rows in the holdings table. No new API field — `asset_class` already tells the UI when to apply the ×100.

**Alternative considered:** Backend sends a separate `quoted_price` field. Rejected to keep the API minimal — the frontend can derive it from `last_price` and `asset_class` in one line.

### Decision 3: Normalizing historical/chart prices for bonds
**Chosen:** Apply the same `_normalize_bond_price` helper inside `_yahoo_chart_history` and `_get_equity_history` when the symbol is a BOND ISIN. This keeps period returns and charts consistent with spot prices.

**Alternative considered:** Leave historical prices raw and normalize only in the period-return calculation. Rejected because charts would also show raw prices, creating visual inconsistency.

## Risks / Trade-offs

- **[Risk] Heuristic (price ≥ 10) misclassifies a non-bond ISIN as a bond** → Mitigation: only apply the heuristic when `asset_class` is explicitly "BOND" or unknown AND symbol matches ISIN regex; when asset_class is known and not BOND, never divide.
- **[Risk] Existing cached prices in Redis from before the fix are raw (not normalized)** → Mitigation: cache keys include the symbol; the 60s TTL means stale raw prices expire quickly. For historical cache (6h TTL), acceptable short-term inconsistency.
- **[Risk] Borsa Italiana page structure changes, breaking the regex parser** → Mitigation: existing fallback chain (official close → Yahoo → stored Price) handles this; the fix doesn't change the parser.

## Migration Plan

No database migration needed. Existing Price rows are already normalized. Deploy backend + frontend together; stale Redis cache entries expire within 60s (spot) / 6h (history). Rollback: revert the code change; no data cleanup required.

## Open Questions

- None. The approach is fully determined by the existing architecture (asset_class tagging already flows through `symbol_meta` to all price-fetching paths).

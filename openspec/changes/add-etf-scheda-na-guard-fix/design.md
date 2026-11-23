# Design

## Context

`MarketDataService` parses Borsa Italiana scheda pages with regexes over server-rendered HTML (`backend/services/market_data_service.py`): `_parse_borsa_closing_price` (ETFPlus "Closing Price"), `_parse_borsa_official_close` (bond "Official Close" + date), `_parse_borsa_last_price` (summary-value block; already naturally bounded, it anchors directly on `summary-value`). The ETF "Closing Price" row reads "N.A." while the market is open and shows the official close after the session — confirmed live on 2026-11-23 (mid-session markup: `<strong>Closing Price</strong> … <span class="t-text -right">N.A.</span>`). Current regexes use `re.S` + unbounded `.*?`, so a non-numeric cell makes them scan forward to an arbitrary later numeric cell (19.00 / 134.00 garbage rows were written by `refresh_bond_prices` and deleted). See proposal.md — Why, for motivation (beat schedule can fire during market hours).

## Goals / Non-Goals

**Goals:**
- Quote parses return a number only when it is in the labeled cell itself; "N.A." or absent → `None`.
- Daily refresh safely skips assets whose close cells are N.A. (no rows, no corruption) — reuse of the existing "no price → skip" path, no worker changes.
- Existing populated-cell behavior unchanged (post-close parsing identical).

**Non-Goals:**
- Scheduling changes (moving the beat to after 17:30 CET) — the guard makes timing irrelevant; keep the floating 86400s schedule as is.
- Any change to the summary "last price" block (`_parse_borsa_last_price`), which anchors on the `summary-value` div and is not affected by the N.A. behavior.
- Bond scheda rewrite beyond the price-cell bound; the date cell is already bounded by the `add-bond-isin-alias-pricing` YY/MM/DD rework.

## Decisions

1. **Bound the value match to the label's own value cell.**
   Observed markup puts the value in the *next* cell: `<strong>Closing Price</strong> … </span></td> <td> <span class="t-text -right">VALUE or N.A.</span>`. Regex shape: `Closing Price</strong>.{0,120}?t-text -right">\s*([\d]+(?:[.,][\d]+)?)\s*</span>` (re.S); the digit group is mandatory, so an "N.A." or empty cell cannot match and returns None — and the ~120-char window cannot walk past the cell to a later row (inter-tag distance observed ≤ ~40 chars). Same shape for the bond "Official Close" price cell, leaving its (already correct) close-date cell as is. Alternative considered: an HTML-table parser dependency (BeautifulSoup) — rejected: new dependency for one cell; repo keeps "less is more".
2. **Worker needs no change**: `refresh_bond_prices` already does `if not close: continue`; a None close cell simply skips that asset for the run.
3. **Tests used captured live markup** (mid-session N.A. variant + populated post-close variant, committed as fixtures) plus a negative test asserting the parse returns None when the N.A. cell is followed by other numeric cells — the exact garbage regressions observed in the wild — and a worker-level regression pinning the "no row appended" behavior.

## Risks / Trade-offs

- [Borsa changes markup so the value cell moves] → parse degrades to None → refresh skips that day (a better failure than garbage rows); fixtures detect drift at test time.
- [Window too tight rejects legitimate values] → the 120-char window is ~3× the observed inter-tag distance; fixtures pin the live markup.

## Migration Plan

Code + tests only; deploy with the next restart; no data migration (the two garbage rows were deleted). Rollback = revert commit; behavior returns to pre-guard (no worse than before).

## Open Questions

(none)

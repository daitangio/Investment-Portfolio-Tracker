# Tasks

## 1. N.A.-bounded quote-cell parsing

- [ ] 1.1 Rework `_parse_borsa_closing_price` in `backend/services/market_data_service.py`: the value must match inside the first `t-text -right` span after `Closing Price</strong>` within a ~120-char window (mandatory digit group), so "N.A." or empty cells return None instead of scanning forward. Verify: unit tests with the captured mid-session fixture (N.A. + later numeric cells → None) and the populated fixture (38.91 → 38.91).
- [ ] 1.2 Apply the same bounded-cell rule to the "Official Close" value cell in `_parse_borsa_official_close` (date cell unchanged — already handled by add-bond-isin-alias-pricing). Verify: unit test with a bond fixture whose Official Close cell is "N.A." followed by other numeric rows → close is None.

## 2. Worker-level guard

- [ ] 2.1 Add a regression test (extend the worker test style): when the scheda fixture shows N.A. for the close, `refresh_bond_prices` appends no row for that asset and the existing populated assets still get theirs. No worker code change expected. Verify: `cd backend && ../.venv/bin/python -m pytest tests -q` green.

## 3. Live verification and docs

- [ ] 3.1 Run one refresh during market hours (or the next beat fire) and confirm no new BORSA_ITALIANA rows are written for the two ETF schedas showing N.A., while bond close rows behave as before (dated rows, dedupe on second run). Verify: DB query on prices by source/date.
- [ ] 3.2 Append the session entry to `LOG.md` (what was implemented, what is missing, model name/version). Verify: entry present and conforms to the existing format.

## Workflow follow-up

- Archive `add-etfplus-etf-pricing` before this change (both are ADDED deltas on `etf-market-data`; that order keeps the main-spec merge natural).
- Archive this change with `/openspec-archive-change` after the user validates a mid-session refresh run.

"""Task 3.1 live verification: run the daily refresh twice during market hours.

Run from backend/ with DATABASE_URL pointing at the compose Postgres (15432):
  cd backend && DATABASE_URL=postgresql+asyncpg://... ../.venv/bin/python \
    ../openspec/changes/add-etf-scheda-na-guard-fix/fixtures/run_refresh_verify.py
Expected (market open, schedas quoting Closing Price N.A. for ETFs):
  run1: etfs == 0 and no new ETF rows; bond closes deduped against 2026-11-20
  run2: added == 0 (idempotent)
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "backend"))

from workers.tasks.market_data_tasks import _refresh_bond_prices


async def main() -> None:
    run1 = await _refresh_bond_prices()
    run2 = await _refresh_bond_prices()
    print("run1:", json.dumps(run1))
    print("run2:", json.dumps(run2))


if __name__ == "__main__":
    asyncio.run(main())

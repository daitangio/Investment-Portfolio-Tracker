"""
Backfill stored provider tickers for ETF assets keyed by ISIN.

ETF holdings imported by ISIN (e.g. LU1900066033 Amundi MSCI Semiconductors on
Borsa Italiana ETFPlus) cannot be priced from the raw ISIN: import-time
resolution may have failed or picked a wrong-venue listing, leaving
polygon_ticker NULL (no live price, no chart history).

For each ETF asset with an ISIN symbol and no stored ticker the script resolves
ISIN -> Yahoo ticker (Borsa Italiana Alphanumeric Code first, currency-validated
Yahoo search fallback) and stores it. Run after the venue-aware resolver is
deployed — the old resolver stored wrong-venue listings (e.g. CHIP.SW for
LU1900066033, a Swiss quote ~27% off the EUR price).

Dry run by default; review the list before applying.
Run: docker compose exec backend python scripts/repair_etf_tickers.py [--apply]
"""
import argparse
import asyncio
import sys

sys.path.insert(0, "/app")

from sqlalchemy import select

from database import AsyncSessionLocal
from services.market_data_service import MarketDataService
from shared.models import Asset


async def repair(apply: bool) -> None:
    svc = MarketDataService()
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Asset)
                .where(
                    Asset.asset_class == "ETF",
                    Asset.is_active == True,  # noqa: E712
                    Asset.polygon_ticker.is_(None),
                )
                .order_by(Asset.symbol)
            )
            candidates = [a for a in result.scalars() if MarketDataService._is_isin((a.symbol or "").upper())]
            if not candidates:
                print("No ETF assets missing a stored ticker.")
                return

            updates: list[tuple[Asset, str]] = []
            for asset in candidates:
                currency = (asset.currency or "EUR").upper()
                ticker = await svc.resolve_isin_to_ticker(asset.symbol, currency)
                if ticker:
                    updates.append((asset, ticker))
                print(f"{asset.symbol:14} ({(asset.currency or '?'):3}) -> {ticker or 'UNRESOLVED (left unchanged)'}")

            if apply:
                for asset, ticker in updates:
                    asset.polygon_ticker = ticker
                await db.commit()
                print(f"\nApplied: {len(updates)}/{len(candidates)} tickers stored. Cached summaries refresh within ~5 min.")
            else:
                await db.rollback()
                print(f"\nDry run: {len(updates)}/{len(candidates)} tickers resolved. Re-run with --apply to commit.")
    finally:
        await svc.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="commit the changes (default: dry run)")
    args = parser.parse_args()
    asyncio.run(repair(args.apply))

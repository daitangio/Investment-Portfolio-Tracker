"""Scheduled market data tasks.

These task entrypoints keep Celery worker/beat aligned with the configured
schedule. The API currently refreshes market data on demand, so the scheduled
jobs are lightweight placeholders until a durable background refresh pipeline is
implemented.
"""
from __future__ import annotations

import logging

from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.tasks.market_data_tasks.fetch_equity_prices")
def fetch_equity_prices() -> dict[str, str]:
    logger.info("Equity price refresh task executed")
    return {"status": "ok", "task": "fetch_equity_prices"}


@celery_app.task(name="workers.tasks.market_data_tasks.fetch_crypto_prices")
def fetch_crypto_prices() -> dict[str, str]:
    logger.info("Crypto price refresh task executed")
    return {"status": "ok", "task": "fetch_crypto_prices"}


@celery_app.task(name="workers.tasks.market_data_tasks.refresh_bond_prices")
def refresh_bond_prices() -> dict:
    """Daily: append Borsa Italiana official closes for all BOND assets to Price."""
    import asyncio

    return asyncio.run(_refresh_bond_prices())


async def _refresh_bond_prices() -> dict:
    from datetime import datetime, timezone
    from decimal import Decimal

    from sqlalchemy import select

    from database import AsyncSessionLocal
    from shared.models import Asset, Price
    from services.market_data_service import MarketDataService

    svc = MarketDataService()
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Asset).where(Asset.asset_class == "BOND", Asset.is_active == True)  # noqa: E712
            )
            bonds = result.scalars().all()
            added = 0
            for asset in bonds:
                isin = (asset.isin or asset.symbol or "").upper()
                if not isin:
                    continue
                close = await svc.borsa_italiana_official_close(isin, svc.borsa_type_segments(asset.name))
                if not close:
                    continue
                price, day = close
                day = day or datetime.now(timezone.utc)
                exists = await session.execute(
                    select(Price.id).where(
                        Price.asset_id == asset.id,
                        Price.price_date == day,
                        Price.price_type == "CLOSE",
                        Price.source == "BORSA_ITALIANA",
                    )
                )
                if exists.scalar_one_or_none():
                    continue
                session.add(Price(
                    asset_id=asset.id,
                    price=Decimal(str(price)),
                    currency=asset.currency or "EUR",
                    price_date=day,
                    price_type="CLOSE",
                    source="BORSA_ITALIANA",
                ))
                added += 1
            await session.commit()
            logger.info("refresh_bond_prices: %d/%d bond closes stored", added, len(bonds))
            return {"status": "ok", "task": "refresh_bond_prices", "added": added, "bonds": len(bonds)}
    finally:
        await svc._http.aclose()

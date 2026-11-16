"""Asset lookup shared by CSV import, manual entry and broker sync."""
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import Asset


async def get_or_create_asset(
    db: AsyncSession,
    symbol: str,
    currency: str,
    asset_class: str = "EQUITY",
    **fields: Any,
) -> Asset:
    """
    Listed securities are identified by (symbol, currency): ASX CBA (AUD) and a
    US-listed CBA (USD) are different instruments, and the asset currency decides
    which exchange is priced (.AX for AUD). Crypto is one asset per symbol and is
    always quoted in USD.
    """
    is_crypto = asset_class == "CRYPTO"
    query = select(Asset).where(Asset.symbol == symbol)
    if is_crypto:
        # Prefer the crypto row if a same-symbol equity also exists
        query = query.order_by(Asset.asset_class != "CRYPTO", Asset.created_at)
    else:
        query = query.where(Asset.currency == currency.upper(), Asset.asset_class != "CRYPTO").order_by(Asset.created_at)

    asset = (await db.execute(query.limit(1))).scalar_one_or_none()
    if asset is None:
        asset = Asset(
            symbol=symbol,
            name=fields.pop("name", None) or symbol,
            asset_class=asset_class,
            currency="USD" if is_crypto else currency.upper(),
            **{k: v for k, v in fields.items() if v is not None},
        )
        db.add(asset)
        await db.flush()
    return asset


async def get_or_create_asset_by_isin(
    db: AsyncSession,
    isin: str,
    name: str,
    asset_class: str,
    currency: str = "EUR",
    exchange: Optional[str] = None,
) -> Asset:
    """
    Instruments imported from Intesa Sanpaolo are identified by ISIN: the ISIN
    becomes the symbol (it fits String(20)) and is also stored in Asset.isin.
    """
    isin = isin.upper().strip()
    query = (
        select(Asset)
        .where((Asset.isin == isin) | (Asset.symbol == isin))
        .order_by(Asset.created_at)
    )
    asset = (await db.execute(query.limit(1))).scalar_one_or_none()
    if asset is None:
        asset = Asset(
            symbol=isin,
            name=name or isin,
            asset_class=asset_class,
            currency=currency.upper(),
            isin=isin,
            exchange=exchange,
        )
        db.add(asset)
        await db.flush()
    return asset

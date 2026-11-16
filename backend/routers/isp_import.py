"""
Intesa Sanpaolo patrimonio (holdings snapshot) import router.

POST /api/v1/isp-import/upload  — upload a patrimonio.xlsx, get a preview of
                                  holdings + cash with EUR→AUD enrichment.
POST /api/v1/isp-import/confirm — replace the account's previous snapshot rows
                                  with the confirmed ones.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from shared.auth import get_current_user
from shared.models import Transaction, User
from services.isp_portfolio_import import (
    SOURCE,
    confirm_snapshot,
    preview_snapshot,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["isp-import"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class IspHoldingResponse(BaseModel):
    import_hash: str
    isin: str
    description: str
    asset_class: str
    quantity: float
    price_per_unit: Optional[float]
    market_price_per_unit: Optional[float]
    market_value: float
    currency: str
    fx_rate_to_aud: Optional[float]
    price_per_unit_aud: Optional[float]
    market_value_aud: Optional[float]
    duplicate: bool = False


class IspPreviewResponse(BaseModel):
    deposit_account: Optional[str]
    grand_total_eur: Optional[float]
    total_rows: int
    duplicates: int
    fx_rate_to_aud: Optional[float]
    cash_eur: float
    cash_aud: Optional[float]
    cash_hash: str
    holdings: list[IspHoldingResponse]


class IspConfirmRequest(BaseModel):
    account_id: str
    as_of: str                       # ISO date, the snapshot's as-of date
    import_hashes: list[str]         # approved holding hashes (+ cash_hash)
    cash_hash: str
    cash_eur: float
    cash_aud: Optional[float]
    fx_rate_to_aud: Optional[float]
    holdings: list[IspHoldingResponse]


class IspConfirmResponse(BaseModel):
    saved: int
    skipped_duplicates: int
    deleted_stale: int


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_as_of(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid as_of date: {value!r} (expected YYYY-MM-DD)")


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/upload", response_model=IspPreviewResponse)
async def upload_patrimonio(
    file: UploadFile = File(...),
    as_of: Optional[str] = Form(None),
    account_id: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Parse + FX-enrich a patrimonio.xlsx without persisting anything."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 10 MB)")

    as_of_dt = _parse_as_of(as_of)

    existing_hashes: set[str] = set()
    if account_id:
        result = await db.execute(
            select(Transaction.import_hash).where(
                Transaction.account_id == account_id,
                Transaction.source == SOURCE,
                Transaction.import_hash.isnot(None),
            )
        )
        existing_hashes = {h for h in result.scalars().all() if h}

    try:
        preview = await preview_snapshot(
            content, as_of_dt, existing_hashes=existing_hashes, account_id=account_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("ISP import failed")
        raise HTTPException(status_code=500, detail=f"Import error: {exc}")

    return IspPreviewResponse(
        deposit_account=preview.deposit_account,
        grand_total_eur=float(preview.grand_total_eur) if preview.grand_total_eur is not None else None,
        total_rows=preview.total_rows,
        duplicates=preview.duplicates,
        fx_rate_to_aud=float(preview.fx_rate_to_aud) if preview.fx_rate_to_aud is not None else None,
        cash_eur=float(preview.cash_eur),
        cash_aud=float(preview.cash_aud) if preview.cash_aud is not None else None,
        cash_hash=preview.cash_hash,
        holdings=[
            IspHoldingResponse(
                import_hash=h.import_hash,
                isin=h.isin,
                description=h.description,
                asset_class=h.asset_class,
                quantity=float(h.quantity),
                price_per_unit=float(h.price_per_unit) if h.price_per_unit is not None else None,
                market_price_per_unit=float(h.market_price_per_unit) if h.market_price_per_unit is not None else None,
                market_value=float(h.market_value),
                currency=h.currency,
                fx_rate_to_aud=float(h.fx_rate_to_aud) if h.fx_rate_to_aud is not None else None,
                price_per_unit_aud=float(h.price_per_unit_aud) if h.price_per_unit_aud is not None else None,
                market_value_aud=float(h.market_value_aud) if h.market_value_aud is not None else None,
                duplicate=h.duplicate,
            )
            for h in preview.holdings
        ],
    )


@router.post("/confirm", response_model=IspConfirmResponse)
async def confirm_patrimonio(
    body: IspConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Persist the confirmed snapshot, replacing the account's previous one."""
    from decimal import Decimal
    from services.isp_portfolio_import import IspPreview, IspPreviewHolding

    as_of_dt = _parse_as_of(body.as_of)
    approved = set(body.import_hashes)

    preview = IspPreview(
        holdings=[
            IspPreviewHolding(
                import_hash=h.import_hash,
                isin=h.isin,
                description=h.description,
                asset_class=h.asset_class,
                quantity=Decimal(str(h.quantity)),
                price_per_unit=Decimal(str(h.price_per_unit)) if h.price_per_unit is not None else None,
                market_price_per_unit=Decimal(str(h.market_price_per_unit)) if h.market_price_per_unit is not None else None,
                market_value=Decimal(str(h.market_value)),
                currency=h.currency,
                fx_rate_to_aud=Decimal(str(h.fx_rate_to_aud)) if h.fx_rate_to_aud is not None else None,
                price_per_unit_aud=Decimal(str(h.price_per_unit_aud)) if h.price_per_unit_aud is not None else None,
                market_value_aud=Decimal(str(h.market_value_aud)) if h.market_value_aud is not None else None,
                duplicate=h.duplicate,
            )
            for h in body.holdings
        ],
        cash_eur=Decimal(str(body.cash_eur)),
        cash_hash=body.cash_hash,
        cash_aud=Decimal(str(body.cash_aud)) if body.cash_aud is not None else None,
        fx_rate_to_aud=Decimal(str(body.fx_rate_to_aud)) if body.fx_rate_to_aud is not None else None,
        deposit_account=None,
        grand_total_eur=None,
        total_rows=0,
    )

    from services.market_data_service import MarketDataService

    market_data = MarketDataService()
    try:
        result = await confirm_snapshot(
            db, current_user.id, body.account_id, preview, as_of_dt, approved, market_data=market_data
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Account not found")
    finally:
        await market_data._http.aclose()

    return IspConfirmResponse(**result)


# ─── Trade confirmation (PDF) endpoints ──────────────────────────────────────

class IspTradeResponse(BaseModel):
    import_hash: str
    ordine: str
    isin: str
    description: str
    transaction_type: str
    asset_class: str
    quantity: float
    price_per_unit: Optional[float]
    fees: float
    net_amount: float
    currency: str
    executed_at: Optional[str]
    settled_at: Optional[str]
    fx_rate_to_aud: Optional[float]
    net_amount_aud: Optional[float]
    price_per_unit_aud: Optional[float]
    duplicate: bool = False


class IspTradePreviewResponse(BaseModel):
    total_trades: int
    duplicates: int
    trades: list[IspTradeResponse]


class IspTradeConfirmRequest(BaseModel):
    account_id: str
    import_hashes: list[str]
    trades: list[IspTradeResponse]


class IspTradeConfirmResponse(BaseModel):
    saved: int
    skipped_duplicates: int


@router.post("/trades/upload", response_model=IspTradePreviewResponse)
async def upload_trades(
    file: UploadFile = File(...),
    account_id: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Parse + FX-enrich one Intesa trade-confirmation PDF without persisting."""
    from services.isp_trade_import import SOURCE as TRADE_SOURCE, preview_trades

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 10 MB)")

    existing_hashes: set[str] = set()
    if account_id:
        result = await db.execute(
            select(Transaction.import_hash).where(
                Transaction.account_id == account_id,
                Transaction.source == TRADE_SOURCE,
                Transaction.import_hash.isnot(None),
            )
        )
        existing_hashes = {h for h in result.scalars().all() if h}

    try:
        preview = await preview_trades(content, existing_hashes=existing_hashes, account_id=account_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("ISP trade import failed")
        raise HTTPException(status_code=500, detail=f"Import error: {exc}")

    return IspTradePreviewResponse(
        total_trades=preview.total_trades,
        duplicates=preview.duplicates,
        trades=[
            IspTradeResponse(
                import_hash=t.import_hash,
                ordine=t.ordine,
                isin=t.isin,
                description=t.description,
                transaction_type=t.transaction_type,
                asset_class=t.asset_class,
                quantity=float(t.quantity),
                price_per_unit=float(t.price_per_unit) if t.price_per_unit is not None else None,
                fees=float(t.fees),
                net_amount=float(t.net_amount),
                currency=t.currency,
                executed_at=t.executed_at.isoformat() if t.executed_at else None,
                settled_at=t.settled_at.isoformat() if t.settled_at else None,
                fx_rate_to_aud=float(t.fx_rate_to_aud) if t.fx_rate_to_aud is not None else None,
                net_amount_aud=float(t.net_amount_aud) if t.net_amount_aud is not None else None,
                price_per_unit_aud=float(t.price_per_unit_aud) if t.price_per_unit_aud is not None else None,
                duplicate=t.duplicate,
            )
            for t in preview.trades
        ],
    )


@router.post("/trades/confirm", response_model=IspTradeConfirmResponse)
async def confirm_trades_endpoint(
    body: IspTradeConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Persist the approved trade-confirmation rows as BUY/SELL transactions."""
    from decimal import Decimal
    from services.isp_trade_import import IspTradePreviewItem, confirm_trades

    approved = set(body.import_hashes)
    items = [
        IspTradePreviewItem(
            import_hash=t.import_hash,
            ordine=t.ordine,
            isin=t.isin,
            description=t.description,
            transaction_type=t.transaction_type,
            asset_class=t.asset_class,
            quantity=Decimal(str(t.quantity)),
            price_per_unit=Decimal(str(t.price_per_unit)) if t.price_per_unit is not None else None,
            fees=Decimal(str(t.fees)),
            net_amount=Decimal(str(t.net_amount)),
            currency=t.currency,
            executed_at=datetime.fromisoformat(t.executed_at) if t.executed_at else None,
            settled_at=datetime.fromisoformat(t.settled_at) if t.settled_at else None,
            fx_rate_to_aud=Decimal(str(t.fx_rate_to_aud)) if t.fx_rate_to_aud is not None else None,
            net_amount_aud=Decimal(str(t.net_amount_aud)) if t.net_amount_aud is not None else None,
            price_per_unit_aud=Decimal(str(t.price_per_unit_aud)) if t.price_per_unit_aud is not None else None,
            duplicate=t.duplicate,
        )
        for t in body.trades
    ]

    from services.market_data_service import MarketDataService

    market_data = MarketDataService()
    try:
        result = await confirm_trades(
            db, current_user.id, body.account_id, items, approved, market_data=market_data
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Account not found")
    finally:
        await market_data._http.aclose()

    return IspTradeConfirmResponse(**result)

"""
Intesa Sanpaolo "CONFERMA OPERAZIONI IN TITOLI" (trade confirmation) PDF importer.

Parses one PDF at a time — each page carries one trade block delimited by an
"Ordine :" line — and turns each into a BUY (ACQUISTO) or SELL (VENDITA)
Transaction candidate tagged source="INTESA_TRADE".

Field mapping (from docs/intesa-sample/sample-transactions/*.pdf):
  Ordine number        -> import_hash dedup key
  Codice/ISIN          -> asset
  ACQUISTO / VENDITA   -> BUY / SELL
  Eseguito per         -> quantity (nominal EUR for bonds, units for ETFs)
  PREZZO               -> price_per_unit (bonds: % of nominal, /100)
  COMMISSIONI/SPESE/COSTI/RATEO/IMPOSTA -> fees (folded, see below)
  TOTALE               -> net_amount
  Data e ora esecuzione-> transacted_at
  Data di regolamento  -> settled_at
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.assets import get_or_create_asset_by_isin
from shared.models import Account, Transaction
from services.fx_service import FXService
from services.isp_portfolio_import import (
    BOND_PREFIX_SEGMENTS,
    INSTITUTION,
    _bond_segment,
    parse_it_number,
    scoped_hash,
)

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
SOURCE = "INTESA_TRADE"

ISIN_RE = re.compile(r"[A-Z]{2}[A-Z0-9]{9}\d")
ORDINE_RE = re.compile(r"\b(INTE\d+)\s+\d{2}/\d{2}/\d{4}\s+ESEGUITO")
DATETIME_RE = re.compile(r"(\d{2}/\d{2}/\d{4})\s+(\d{2})\s+(\d{2})\s+(\d{2})")
DATE_RE = re.compile(r"(\d{2}/\d{2}/\d{4})")

# Fee-like line labels whose EUR total is folded into fees
FEE_LABELS = [
    "COMMISSIONI BANCA",
    "SPESE CONFERMA OPERAZIONI IN TITOLI",
    "COSTI DI ESECUZIONE",
    "RATEO LORDO",
    "IMPOSTA SUL RATEO LORDO",
]


# ─── Normalized output ───────────────────────────────────────────────────────

@dataclass
class IspTrade:
    ordine: str
    isin: str
    description: str
    transaction_type: str           # BUY | SELL
    quantity: Decimal
    price_per_unit: Optional[Decimal]   # normalized (bond: /100)
    fees: Decimal                   # folded fee sum (engine-sign-adjusted)
    net_amount: Decimal             # TOTALE
    currency: str = "EUR"
    asset_class: str = "ETF"        # BOND | ETF
    sede: Optional[str] = None
    executed_at: Optional[datetime] = None
    settled_at: Optional[datetime] = None
    raw_fee_lines: list = field(default_factory=list)
    import_hash: str = ""


@dataclass
class IspTradePreviewItem:
    import_hash: str
    ordine: str
    isin: str
    description: str
    transaction_type: str
    asset_class: str
    quantity: Decimal
    price_per_unit: Optional[Decimal]
    fees: Decimal
    net_amount: Decimal
    currency: str = "EUR"
    executed_at: Optional[datetime] = None
    settled_at: Optional[datetime] = None
    fx_rate_to_aud: Optional[Decimal] = None
    net_amount_aud: Optional[Decimal] = None
    price_per_unit_aud: Optional[Decimal] = None
    duplicate: bool = False


@dataclass
class IspTradePreview:
    trades: list[IspTradePreviewItem]
    total_trades: int
    duplicates: int = 0
    deposit_account: Optional[str] = None


# ─── PDF extraction ──────────────────────────────────────────────────────────

def extract_pdf_pages(content: bytes) -> list[str]:
    """Extract text per page with pypdf. Raises ValueError if not a PDF."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as exc:
        raise ValueError(f"Not a readable PDF: {exc}")
    return [(page.extract_text() or "") for page in reader.pages]


def looks_like_trade_confirmation(pages: list[str]) -> bool:
    return any("CONFERMA OPERAZIONI IN TITOLI" in p for p in pages)


def split_trade_blocks(pages: list[str]) -> list[str]:
    """Split page text on 'Ordine :' — each chunk after the marker is one trade."""
    blocks: list[str] = []
    for page in pages:
        parts = re.split(r"Ordine\s*:", page)
        for part in parts[1:]:  # skip preamble before first Ordine
            blocks.append(part)
    return blocks


def parse_pdf(content: bytes) -> list[IspTrade]:
    """Parse an Intesa trade-confirmation PDF into a list of trades."""
    pages = extract_pdf_pages(content)
    if not looks_like_trade_confirmation(pages):
        raise ValueError("Not an Intesa trade confirmation PDF (missing 'CONFERMA OPERAZIONI IN TITOLI')")
    trades = [parse_trade_block(b) for b in split_trade_blocks(pages)]
    return [t for t in trades if t is not None]


def _line_after(text: str, marker: str) -> Optional[str]:
    """Return the first non-empty line after the line containing marker."""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if marker in ln:
            for j in range(i + 1, len(lines)):
                if lines[j].strip():
                    return lines[j].strip()
            return None
    return None


def _all_numbers(line: str) -> list[Decimal]:
    """Extract all Italian-locale numbers from a line (handles trailing '-')."""
    # find tokens that look like numbers (digits with . , and optional trailing -)
    tokens = re.findall(r"\(?\d[\d.,]*\)?-?", line)
    nums = []
    for t in tokens:
        v = parse_it_number(t)
        if v is not None:
            nums.append(v)
    return nums


def parse_trade_block(block: str) -> Optional[IspTrade]:
    """Parse one trade block (text after 'Ordine :') into an IspTrade."""
    # Order number
    m = ORDINE_RE.search(block)
    if not m:
        return None
    ordine = m.group(1)

    # ISIN + description: line after "Codice e descrizione Titolo:"
    isin = ""
    description = ""
    cod_line = _line_after(block, "Codice e descrizione Titolo")
    if cod_line:
        im = ISIN_RE.search(cod_line)
        if im:
            isin = im.group(0)
            description = cod_line[im.end():].strip()

    # Transaction type
    op_line = _line_after(block, "Descrizione operazione")
    raw_type = ""
    if op_line:
        raw_type = op_line.upper()
    if "ACQUISTO" in raw_type:
        txn_type = "BUY"
    elif "VENDITA" in raw_type:
        txn_type = "SELL"
    else:
        txn_type = "BUY"  # default

    # Quantity: "Eseguito per :" line (executed qty is authoritative)
    qty_line = _line_after(block, "Eseguito per")
    quantity = ZERO
    if qty_line:
        nums = _all_numbers(qty_line)
        if nums:
            quantity = abs(nums[0])

    # Execution datetime
    exec_line = _line_after(block, "Data e ora di esecuzione")
    executed_at = None
    if exec_line:
        dm = DATETIME_RE.search(exec_line)
        if dm:
            d, h, mi, s = dm.groups()
            executed_at = datetime.strptime(f"{d} {h}:{mi}:{s}", "%d/%m/%Y %H:%M:%S")

    # Sede
    sede_line = _line_after(block, "Sede di Esecuzione")
    sede = sede_line

    # Settlement date: same line as "Data di regolamento :" or next
    settled_at = None
    for ln in block.splitlines():
        if "Data di regolamento" in ln:
            dm = DATE_RE.search(ln)
            if dm:
                settled_at = datetime.strptime(dm.group(1), "%d/%m/%Y")
                break

    # Price + fee lines: scan all lines for known labels
    price_per_unit_raw: Optional[Decimal] = None
    price_total: Optional[Decimal] = None
    fee_sum = ZERO
    raw_fee_lines: list[dict] = []
    for ln in block.splitlines():
        stripped = ln.strip()
        if stripped.startswith("PREZZO ") and not stripped.startswith("PREZZO BASE"):
            nums = _all_numbers(stripped)
            if len(nums) >= 2:
                price_per_unit_raw = nums[0]
                price_total = nums[1]
            elif len(nums) == 1:
                price_per_unit_raw = nums[0]
        elif stripped.startswith("TOTALE"):
            nums = _all_numbers(stripped)
            # TOTALE line: "TOTALE  EUR 997,50" — last number is the total
            if nums:
                net_amount = abs(nums[-1])
            else:
                net_amount = ZERO
        else:
            for label in FEE_LABELS:
                if stripped.upper().startswith(label):
                    nums = _all_numbers(stripped)
                    # last number on the line is the EUR total (may have trailing -)
                    if nums:
                        val = nums[-1]
                        fee_sum += val
                        raw_fee_lines.append({"label": label, "amount": float(val)})
                    break

    # Bond vs ETF: sede or description
    is_bond = False
    sede_upper = (sede or "").upper()
    if any(k in sede_upper for k in ("MOT", "HMTF", "TIT.STATO", "BOND")):
        is_bond = True
    if not is_bond and _bond_segment(description):
        is_bond = True

    if is_bond:
        price_per_unit = (price_per_unit_raw / 100) if price_per_unit_raw is not None else None
        asset_class = "BOND"
    else:
        price_per_unit = price_per_unit_raw
        asset_class = "ETF"

    # net_amount: prefer TOTALE; fall back to qty*price
    if 'net_amount' not in dir() or net_amount is None:
        net_amount = (quantity * price_per_unit) if price_per_unit is not None else ZERO

    # folded fees here — all fee-like lines (commissioni, spese, costi, rateo,
    # imposta) are summed with their printed signs; for SELL the sign is flipped
    # so that qty*price - fees == TOTALE (engine invariant)
    # GG: Eval if needed to keep all the fees in the database
    fees = fee_sum if txn_type == "BUY" else -fee_sum

    import_hash = hashlib.sha256(f"INTESA_TRADE|{ordine}".encode()).hexdigest()

    return IspTrade(
        ordine=ordine,
        isin=isin,
        description=description,
        transaction_type=txn_type,
        quantity=quantity,
        price_per_unit=price_per_unit,
        fees=fees,
        net_amount=net_amount,
        currency="EUR",
        asset_class=asset_class,
        sede=sede,
        executed_at=executed_at,
        settled_at=settled_at,
        raw_fee_lines=raw_fee_lines,
        import_hash=import_hash,
    )


# ─── Preview (parse + FX, no persistence) ────────────────────────────────────

async def preview_trades(
    file_bytes: bytes,
    existing_hashes: Optional[set[str]] = None,
    account_id: Optional[str] = None,
) -> IspTradePreview:
    trades = parse_pdf(file_bytes)

    # Collect unique execution dates for FX lookup
    fx = FXService()
    try:
        fx_cache: dict[str, Decimal] = {}
        for t in trades:
            if t.executed_at is None:
                continue
            key = t.executed_at.date().isoformat()
            if key not in fx_cache:
                fx_cache[key] = await fx.get_aud_rate("EUR", t.executed_at)
    finally:
        await fx.close()

    existing = existing_hashes or set()
    items: list[IspTradePreviewItem] = []
    duplicates = 0
    for t in trades:
        scoped = scoped_hash(account_id, t.import_hash) if account_id else t.import_hash
        dup = scoped in existing or t.import_hash in existing
        duplicates += 1 if dup else 0
        rate = fx_cache.get(t.executed_at.date().isoformat()) if t.executed_at else None
        items.append(IspTradePreviewItem(
            import_hash=scoped,
            ordine=t.ordine,
            isin=t.isin,
            description=t.description,
            transaction_type=t.transaction_type,
            asset_class=t.asset_class,
            quantity=t.quantity,
            price_per_unit=t.price_per_unit,
            fees=t.fees,
            net_amount=t.net_amount,
            currency="EUR",
            executed_at=t.executed_at,
            settled_at=t.settled_at,
            fx_rate_to_aud=rate,
            net_amount_aud=(t.net_amount * rate).quantize(Decimal("0.01")) if rate else None,
            price_per_unit_aud=(t.price_per_unit * rate).quantize(Decimal("0.000001")) if (rate and t.price_per_unit is not None) else None,
            duplicate=dup,
        ))

    return IspTradePreview(
        trades=items,
        total_trades=len(items),
        duplicates=duplicates,
    )


# ─── Confirm (persistence) ───────────────────────────────────────────────────

async def confirm_trades(
    db: AsyncSession,
    user_id: str,
    account_id: str,
    trades: list[IspTradePreviewItem],
    approved_hashes: set[str],
    market_data=None,
) -> dict:
    """Insert approved trades as BUY/SELL Transaction rows. Skips duplicates."""
    acct = (await db.execute(
        select(Account).where(Account.id == account_id, Account.user_id == user_id)
    )).scalar_one_or_none()
    if not acct:
        raise LookupError("Account not found")

    existing = (await db.execute(
        select(Transaction.import_hash).where(
            Transaction.account_id == account_id,
            Transaction.source == SOURCE,
            Transaction.import_hash.isnot(None),
        )
    )).scalars().all()
    existing_set = {h for h in existing if h}

    saved = 0
    skipped = 0
    for t in trades:
        if t.import_hash not in approved_hashes:
            continue
        if t.import_hash in existing_set:
            skipped += 1
            continue

        asset = await get_or_create_asset_by_isin(
            db,
            isin=t.isin,
            name=t.description or t.isin,
            asset_class=t.asset_class,
            currency="EUR",
            exchange="MOT" if t.asset_class == "BOND" else "ETFPLUS",
        )
        # ETFs/funds: resolve the ISIN to a Yahoo ticker once so live pricing works
        if market_data is not None and t.asset_class != "BOND" and not asset.polygon_ticker:
            ticker = await market_data.resolve_isin_to_ticker(t.isin)
            if ticker:
                asset.polygon_ticker = ticker

        fx_rate = t.fx_rate_to_aud or Decimal("1.0")
        txn = Transaction(
            account_id=account_id,
            user_id=user_id,
            asset_id=asset.id,
            transaction_type=t.transaction_type,
            quantity=t.quantity,
            price_per_unit=t.price_per_unit,
            gross_amount=(t.quantity * t.price_per_unit) if t.price_per_unit is not None else None,
            fees=t.fees,
            net_amount=t.net_amount,
            currency="EUR",
            fx_rate_to_aud=fx_rate,
            net_amount_aud=t.net_amount_aud,
            price_per_unit_aud=t.price_per_unit_aud,
            transacted_at=t.executed_at,
            settled_at=t.settled_at,
            source=SOURCE,
            institution=INSTITUTION,
            import_hash=t.import_hash,
            notes=f"{t.transaction_type} {t.quantity} {t.description} — Ordine {t.ordine}",
            raw_data={
                "ordine": t.ordine,
                "isin": t.isin,
                "asset_class": t.asset_class,
                "description": t.description,
                "sede": t.sede if hasattr(t, 'sede') else None,
            },
        )
        db.add(txn)
        await db.flush()
        saved += 1

    await db.commit()
    return {"saved": saved, "skipped_duplicates": skipped}

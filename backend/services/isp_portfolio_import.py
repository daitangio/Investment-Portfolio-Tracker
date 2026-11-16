"""
Intesa Sanpaolo "patrimonio" (holdings snapshot) importer.

Parses the Intesa Sanpaolo Excel wealth statement (docs/intesa-sample/
patrimonio.xlsx) — a *holdings snapshot*, not a trade history — and turns
each position into an opening-balance (TRANSFER_IN) transaction plus a
DEPOSIT for the cash section, so the FIFO portfolio engine picks them up.

File quirks handled here:
  - every cell is Italian-locale text: "." thousands, "," decimal, " €"/" %"
  - repeated section headers, "Totale ..." total rows, blank rows
  - bonds (BTP/BOT/...) quote price as % of nominal with quantity = nominal €;
    ETFs quote €/unit — disambiguated per row via the file's own fiscal value
  - the bottom "Liquidità"/"Saldo"/"Conto" rows carry the EUR cash balance
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.assets import get_or_create_asset_by_isin
from shared.models import Account, Price, Transaction
from services.fx_service import FXService

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
SOURCE = "INTESA_SNAPSHOT"
INSTITUTION = "intesa_sanpaolo"

ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")

# Column indexes in the patrimonio sheet (0-based)
COL_DESC, COL_ISIN, COL_QTY, COL_FISCAL, COL_MKT, COL_VARPCT, COL_TIME, COL_VAR_PCT, COL_VAR_EUR, COL_FISCAL_VAL, COL_MKT_VAL = range(11)

# Description prefix -> Borsa Italiana MOT path segment (for live bond pricing)
BOND_PREFIX_SEGMENTS = [
    ("BTP ITALIA", "btp-italia"),
    ("BTP VALORE", "btp-valore"),
    ("BTP GREEN", "btp-green"),
    ("BTP FUTURA", "btp-futura"),
    ("BTP", "btp"),
    ("BOT", "bot"),
    ("CCT", "cct"),
    ("CTZ", "ctz"),
]


# ─── Italian-locale parsing ──────────────────────────────────────────────────

def parse_it_number(value) -> Optional[Decimal]:
    """Parse an Italian-locale number: "40.912,25 €" -> 40912.25, "-1,47 %" -> -1.47."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    s = str(value).strip()
    if not s:
        return None
    s = s.replace("€", "").replace("%", "").replace("EUR", "").strip()
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()").strip()
    if s.endswith("-"):
        negative = True
        s = s[:-1].strip()
    if "," in s:
        # Italian format: dots are thousands separators, comma is decimal
        s = s.replace(".", "").replace(",", ".")
    elif "." in s and not re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        # Plain decimal dot (e.g. "10595.12"); grouped "1.234.567" stays thousands
        pass
    else:
        s = s.replace(".", "")
    if negative:
        s = "-" + s
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _cell(row: list, idx: int) -> str:
    return str(row[idx]).strip() if idx < len(row) and row[idx] is not None else ""


def _bond_segment(description: str) -> Optional[str]:
    desc = description.upper()
    for prefix, segment in BOND_PREFIX_SEGMENTS:
        if desc.startswith(prefix):
            return segment
    return None


# ─── Normalized output ───────────────────────────────────────────────────────

@dataclass
class IspHolding:
    isin: str
    description: str
    quantity: Decimal                 # nominal EUR for bonds, units for ETFs
    price_per_unit: Decimal           # normalized: EUR per EUR (bond) or per unit (ETF)
    quoted_price: Decimal             # as printed (bond: % of nominal)
    market_price_per_unit: Optional[Decimal]  # normalized like price_per_unit
    market_value: Optional[Decimal]   # Controvalore €
    fiscal_value: Optional[Decimal]   # Controvalore di carico fiscale €
    var_eur: Optional[Decimal]
    asset_class: str                  # BOND | ETF
    mot_segment: Optional[str]        # Borsa Italiana path segment for bonds
    quote_time: Optional[str]
    raw: dict
    import_hash: str = ""


@dataclass
class IspSnapshot:
    holdings: list[IspHolding]
    cash_eur: Decimal
    deposit_account: Optional[str]    # "Deposito Amministrato 0102..."
    grand_total_eur: Optional[Decimal]
    total_rows: int


@dataclass
class IspPreviewHolding:
    import_hash: str
    isin: str
    description: str
    asset_class: str
    quantity: Decimal
    price_per_unit: Decimal
    market_price_per_unit: Optional[Decimal]
    market_value: Decimal
    currency: str = "EUR"
    fx_rate_to_aud: Optional[Decimal] = None
    price_per_unit_aud: Optional[Decimal] = None
    market_value_aud: Optional[Decimal] = None
    duplicate: bool = False


@dataclass
class IspPreview:
    holdings: list[IspPreviewHolding]
    cash_eur: Decimal
    cash_hash: str
    cash_aud: Optional[Decimal]
    fx_rate_to_aud: Optional[Decimal]
    deposit_account: Optional[str]
    grand_total_eur: Optional[Decimal]
    total_rows: int
    duplicates: int = 0


@dataclass
class ConfirmPlan:
    """Pure decision of what confirm should do (testable without a DB)."""
    insert: list[IspPreviewHolding] = field(default_factory=list)
    skip_duplicates: list[str] = field(default_factory=list)
    delete_stale_hashes: list[str] = field(default_factory=list)
    insert_cash: bool = False


# ─── Sheet parsing ───────────────────────────────────────────────────────────

def _rows_from_excel(content: bytes) -> list[list]:
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    except Exception as exc:
        raise ValueError(f"Not a readable Excel file: {exc}")
    ws = wb.worksheets[0] if wb.worksheets else wb.active
    return [list(r) for r in ws.iter_rows(values_only=True)]


def looks_like_patrimonio(rows: list[list]) -> bool:
    """Detect an Intesa patrimonio sheet by its repeated Descrizione/ISIN header."""
    for row in rows[:60]:
        if _cell(row, COL_DESC).lower() == "descrizione" and _cell(row, COL_ISIN).lower() == "isin":
            if any("controvalore" in _cell(row, i).lower() for i in range(len(row))):
                return True
    return False


def parse_patrimonio(content: bytes) -> IspSnapshot:
    """Parse the patrimonio.xlsx bytes into holdings + cash. Raises ValueError if not Intesa."""
    rows = _rows_from_excel(content)
    if not looks_like_patrimonio(rows):
        raise ValueError("Not an Intesa Sanpaolo patrimonio file (missing Descrizione/ISIN/Controvalore headers)")

    holdings: list[IspHolding] = []
    cash_eur = ZERO
    deposit_account = None
    grand_total = None

    for row in rows:
        desc = _cell(row, COL_DESC)
        isin = _cell(row, COL_ISIN).upper()

        if isin and ISIN_RE.match(isin):
            holdings.append(_parse_holding_row(row, desc, isin))
            continue

        low = desc.lower()
        if low.startswith("deposito amministrato"):
            deposit_account = desc
        elif desc == "Investimenti":
            # grand total sits in the last numeric cell of the row
            for i in range(len(row) - 1, -1, -1):
                v = parse_it_number(row[i])
                if v is not None and v > 0:
                    grand_total = v
                    break
        elif "saldo" in low or low.startswith("conto ") or low == "liquidità":
            # cash rows: "Saldo totale" / "Saldo disponibilità conti" / "Conto 01899/..."
            for i in range(len(row) - 1, -1, -1):
                v = parse_it_number(row[i])
                if v is not None and v > 0:
                    cash_eur = v
                    break

    return IspSnapshot(
        holdings=holdings,
        cash_eur=cash_eur,
        deposit_account=deposit_account,
        grand_total_eur=grand_total,
        total_rows=len(rows),
    )


def _parse_holding_row(row: list, desc: str, isin: str) -> IspHolding:
    quantity = parse_it_number(row[COL_QTY]) or ZERO
    fiscal_quoted = parse_it_number(row[COL_FISCAL])
    market_quoted = parse_it_number(row[COL_MKT])
    var_eur = parse_it_number(row[COL_VAR_EUR])
    fiscal_value = parse_it_number(row[COL_FISCAL_VAL])
    market_value = parse_it_number(row[COL_MKT_VAL])

    # Bond vs per-unit: bonds quote price as % of nominal (qty × price / 100 = value)
    is_bond = False
    if fiscal_quoted is not None and quantity and fiscal_value is not None:
        per_unit_err = abs(quantity * fiscal_quoted - fiscal_value)
        bond_err = abs(quantity * fiscal_quoted / 100 - fiscal_value)
        is_bond = bond_err < per_unit_err
    if not is_bond and _bond_segment(desc):
        is_bond = True

    if is_bond:
        price_per_unit = (fiscal_quoted / 100) if fiscal_quoted is not None else None
        market_per_unit = (market_quoted / 100) if market_quoted is not None else None
    else:
        price_per_unit = fiscal_quoted
        market_per_unit = market_quoted

    asset_class = "BOND" if is_bond else "ETF"
    segment = _bond_segment(desc) if is_bond else None

    raw = {f"col{i}": (str(v) if v is not None else None) for i, v in enumerate(row)}
    hash_input = f"{isin}|{quantity}|{fiscal_quoted}|{market_value}"
    import_hash = hashlib.sha256(hash_input.encode()).hexdigest()

    return IspHolding(
        isin=isin,
        description=desc,
        quantity=quantity,
        price_per_unit=price_per_unit,
        quoted_price=fiscal_quoted,
        market_price_per_unit=market_per_unit,
        market_value=market_value,
        fiscal_value=fiscal_value,
        var_eur=var_eur,
        asset_class=asset_class,
        mot_segment=segment,
        quote_time=_cell(row, COL_TIME) or None,
        raw=raw,
        import_hash=import_hash,
    )


def scoped_hash(account_id: str, legacy_hash: str) -> str:
    return hashlib.sha256(f"{account_id}|{legacy_hash}".encode()).hexdigest()


def cash_import_hash(cash_eur: Decimal, as_of: datetime) -> str:
    return hashlib.sha256(f"CASH|{cash_eur}|{as_of.date().isoformat()}".encode()).hexdigest()


# ─── Preview (parse + FX, no persistence) ────────────────────────────────────

async def preview_snapshot(
    file_bytes: bytes,
    as_of: datetime,
    existing_hashes: Optional[set[str]] = None,
    account_id: Optional[str] = None,
) -> IspPreview:
    snapshot = parse_patrimonio(file_bytes)

    fx = FXService()
    try:
        rate = await fx.get_aud_rate("EUR", as_of)
    finally:
        await fx.close()

    existing = existing_hashes or set()
    holdings: list[IspPreviewHolding] = []
    duplicates = 0
    for h in snapshot.holdings:
        scoped = scoped_hash(account_id, h.import_hash) if account_id else h.import_hash
        dup = scoped in existing or h.import_hash in existing
        duplicates += 1 if dup else 0
        mv = h.market_value if h.market_value is not None else (
            h.quantity * h.market_price_per_unit if h.market_price_per_unit is not None else ZERO
        )
        holdings.append(IspPreviewHolding(
            import_hash=scoped,
            isin=h.isin,
            description=h.description,
            asset_class=h.asset_class,
            quantity=h.quantity,
            price_per_unit=h.price_per_unit,
            market_price_per_unit=h.market_price_per_unit,
            market_value=mv,
            currency="EUR",
            fx_rate_to_aud=rate,
            price_per_unit_aud=(h.price_per_unit * rate).quantize(Decimal("0.000001")) if h.price_per_unit is not None else None,
            market_value_aud=(mv * rate).quantize(Decimal("0.01")),
            duplicate=dup,
        ))

    ch = cash_import_hash(snapshot.cash_eur, as_of)
    cash_scoped = scoped_hash(account_id, ch) if account_id else ch
    return IspPreview(
        holdings=holdings,
        cash_eur=snapshot.cash_eur,
        cash_hash=cash_scoped,
        cash_aud=(snapshot.cash_eur * rate).quantize(Decimal("0.01")),
        fx_rate_to_aud=rate,
        deposit_account=snapshot.deposit_account,
        grand_total_eur=snapshot.grand_total_eur,
        total_rows=snapshot.total_rows,
        duplicates=duplicates,
    )


# ─── Confirm planning (pure) + persistence ───────────────────────────────────

def plan_confirm(
    existing_hashes: set[str],
    holdings: list[IspPreviewHolding],
    cash_hash: str,
    approved_hashes: set[str],
) -> ConfirmPlan:
    """Decide what a confirm does: insert new, skip duplicates, delete stale rows."""
    plan = ConfirmPlan()
    for h in holdings:
        if h.import_hash not in approved_hashes:
            continue
        if h.import_hash in existing_hashes:
            plan.skip_duplicates.append(h.import_hash)
        else:
            plan.insert.append(h)
    if cash_hash in approved_hashes and cash_hash not in existing_hashes:
        plan.insert_cash = True
    plan.delete_stale_hashes = sorted(existing_hashes - approved_hashes)
    return plan


async def confirm_snapshot(
    db: AsyncSession,
    user_id: str,
    account_id: str,
    preview: IspPreview,
    as_of: datetime,
    approved_hashes: set[str],
    market_data=None,
) -> dict:
    """Replace the account's previous INTESA_SNAPSHOT rows with the approved ones."""
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

    plan = plan_confirm(existing_set, preview.holdings, preview.cash_hash, approved_hashes)

    # Remove stale snapshot rows (positions no longer in the new file)
    if plan.delete_stale_hashes:
        await db.execute(
            Transaction.__table__.delete().where(
                Transaction.account_id == account_id,
                Transaction.source == SOURCE,
                Transaction.import_hash.in_(plan.delete_stale_hashes),
            )
        )

    fx_rate = preview.fx_rate_to_aud or Decimal("1.0")
    saved = 0

    for h in plan.insert:
        asset = await get_or_create_asset_by_isin(
            db,
            isin=h.isin,
            name=h.description,
            asset_class=h.asset_class,
            currency="EUR",
            exchange="MOT" if h.asset_class == "BOND" else "ETFPLUS",
        )
        # ETFs/funds: resolve the ISIN to a Yahoo ticker once so live pricing works
        if market_data is not None and h.asset_class != "BOND" and not asset.polygon_ticker:
            ticker = await market_data.resolve_isin_to_ticker(h.isin)
            if ticker:
                asset.polygon_ticker = ticker
        net = h.quantity * h.price_per_unit if h.price_per_unit is not None else None
        txn = Transaction(
            account_id=account_id,
            user_id=user_id,
            asset_id=asset.id,
            transaction_type="TRANSFER_IN",
            quantity=h.quantity,
            price_per_unit=h.price_per_unit,
            gross_amount=net,
            fees=ZERO,
            net_amount=net,
            currency="EUR",
            fx_rate_to_aud=fx_rate,
            net_amount_aud=(net * fx_rate).quantize(Decimal("0.01")) if net is not None else None,
            price_per_unit_aud=h.price_per_unit_aud,
            transacted_at=as_of,
            source=SOURCE,
            institution=INSTITUTION,
            import_hash=h.import_hash,
            notes=h.description,
            raw_data={"isin": h.isin, "asset_class": h.asset_class, "description": h.description},
        )
        db.add(txn)
        await db.flush()
        saved += 1

        # Store the snapshot's own market price as a Price row (valuation fallback)
        if h.market_price_per_unit is not None:
            exists = (await db.execute(
                select(Price.id).where(
                    Price.asset_id == asset.id,
                    Price.price_date == as_of,
                    Price.price_type == "CLOSE",
                    Price.source == SOURCE,
                )
            )).scalar_one_or_none()
            if not exists:
                db.add(Price(
                    asset_id=asset.id,
                    price=h.market_price_per_unit,
                    currency="EUR",
                    price_date=as_of,
                    price_type="CLOSE",
                    source=SOURCE,
                ))

    if plan.insert_cash and preview.cash_eur > 0:
        db.add(Transaction(
            account_id=account_id,
            user_id=user_id,
            asset_id=None,
            transaction_type="DEPOSIT",
            quantity=None,
            price_per_unit=None,
            net_amount=preview.cash_eur,
            currency="EUR",
            fx_rate_to_aud=fx_rate,
            net_amount_aud=preview.cash_aud,
            transacted_at=as_of,
            source=SOURCE,
            institution=INSTITUTION,
            import_hash=preview.cash_hash,
            notes="Liquidità — Intesa Sanpaolo",
        ))
        saved += 1

    await db.commit()
    return {
        "saved": saved,
        "skipped_duplicates": len(plan.skip_duplicates),
        "deleted_stale": len(plan.delete_stale_hashes),
    }

import sys
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.isp_trade_import import (
    SOURCE,
    confirm_trades,
    extract_pdf_pages,
    looks_like_trade_confirmation,
    parse_pdf,
    parse_trade_block,
    preview_trades,
    split_trade_blocks,
)

SAMPLES = Path(__file__).resolve().parents[2] / "docs" / "intesa-sample" / "sample-transactions"
ETF_PDF = SAMPLES / "TFAMB00001_etf-redacted.pdf"
BTP_PDF = SAMPLES / "TFAMB00001_btp-redacted.pdf"
DOUBLE_PDF = SAMPLES / "TFAMB00001_double-redacted.pdf"


class PdfExtractionTests(unittest.TestCase):
    def test_extracts_pages(self):
        pages = extract_pdf_pages(ETF_PDF.read_bytes())
        self.assertEqual(len(pages), 1)
        self.assertIn("CONFERMA OPERAZIONI IN TITOLI", pages[0])

    def test_detects_trade_confirmation(self):
        pages = extract_pdf_pages(DOUBLE_PDF.read_bytes())
        self.assertTrue(looks_like_trade_confirmation(pages))
        self.assertFalse(looks_like_trade_confirmation(["hello world"]))

    def test_split_finds_all_ordine_blocks(self):
        pages = extract_pdf_pages(DOUBLE_PDF.read_bytes())
        blocks = split_trade_blocks(pages)
        self.assertEqual(len(blocks), 2)

    def test_rejects_non_pdf(self):
        with self.assertRaises(ValueError):
            extract_pdf_pages(b"not a pdf at all")


class ParseEtfBuyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trades = parse_pdf(ETF_PDF.read_bytes())

    def test_one_trade(self):
        self.assertEqual(len(self.trades), 1)

    def test_fields(self):
        t = self.trades[0]
        self.assertEqual(t.ordine, "INTE1020026863576693")
        self.assertEqual(t.transaction_type, "BUY")
        self.assertEqual(t.isin, "IE00B1YZSC51")
        self.assertIn("ISHARES CORE MSCI EU", t.description)
        self.assertEqual(t.quantity, Decimal("25"))
        self.assertEqual(t.price_per_unit, Decimal("39.64"))
        self.assertEqual(t.asset_class, "ETF")
        self.assertEqual(t.currency, "EUR")
        self.assertEqual(t.executed_at, datetime(2026, 10, 20, 9, 45, 29))
        self.assertEqual(t.settled_at, datetime(2026, 10, 22))

    def test_fees_folded_and_net(self):
        t = self.trades[0]
        # COMMISSIONI 3.50 + SPESE 0.50 + COSTI 2.50 = 6.50
        self.assertEqual(t.fees, Decimal("6.50"))
        self.assertEqual(t.net_amount, Decimal("997.50"))
        # invariant: qty*price + fees == TOTALE
        self.assertEqual(t.quantity * t.price_per_unit + t.fees, t.net_amount)

    def test_import_hash_stable(self):
        again = parse_pdf(ETF_PDF.read_bytes())
        self.assertEqual(self.trades[0].import_hash, again[0].import_hash)
        self.assertNotEqual(self.trades[0].import_hash, parse_pdf(BTP_PDF.read_bytes())[0].import_hash)


class ParseBtpBuyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trades = parse_pdf(BTP_PDF.read_bytes())

    def test_bond_detected_and_price_normalized(self):
        t = self.trades[0]
        self.assertEqual(t.asset_class, "BOND")
        self.assertEqual(t.isin, "IT0005735201")
        self.assertEqual(t.transaction_type, "BUY")
        self.assertEqual(t.quantity, Decimal("3000"))
        # PREZZO 100.000000 -> /100 -> 1.0
        self.assertEqual(t.price_per_unit, Decimal("1"))
        self.assertEqual(t.net_amount, Decimal("3000"))
        self.assertEqual(t.fees, Decimal("0"))


class ParseDoublePdfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trades = parse_pdf(DOUBLE_PDF.read_bytes())

    def test_two_trades(self):
        self.assertEqual(len(self.trades), 2)

    def test_first_is_etf_buy(self):
        t = self.trades[0]
        self.assertEqual(t.transaction_type, "BUY")
        self.assertEqual(t.isin, "IE00B1YZSC51")
        self.assertEqual(t.asset_class, "ETF")
        self.assertEqual(t.quantity, Decimal("75"))
        self.assertEqual(t.price_per_unit, Decimal("39.935"))
        self.assertEqual(t.fees, Decimal("10.19"))  # 7.19 + 0.50 + 2.50
        self.assertEqual(t.net_amount, Decimal("3005.32"))

    def test_second_is_btp_sell_with_folded_fees(self):
        t = self.trades[1]
        self.assertEqual(t.transaction_type, "SELL")
        self.assertEqual(t.isin, "IT0005495731")
        self.assertEqual(t.asset_class, "BOND")
        self.assertEqual(t.quantity, Decimal("5000"))
        # PREZZO 97.951000 -> /100 -> 0.97951
        self.assertEqual(t.price_per_unit, Decimal("0.97951"))
        # TOTALE 4.929,29
        self.assertEqual(t.net_amount, Decimal("4929.29"))
        # folded fee lines with printed signs: RATEO +52.02, IMPOSTA -6.50,
        # COMMISSIONI -10.28, SPESE -0.50, COSTI -3.00 => sum = 31.74
        # SELL: fees = -sum so that qty*price - fees == TOTALE
        self.assertEqual(t.fees, Decimal("-31.74"))
        # invariant: qty*price - fees == TOTALE
        self.assertAlmostEqual(
            float(t.quantity * t.price_per_unit - t.fees), float(t.net_amount), places=2
        )

    def test_distinct_hashes(self):
        h = [t.import_hash for t in self.trades]
        self.assertEqual(len(set(h)), 2)


class _FakeResult:
    def __init__(self, items):
        self._items = list(items)

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None

    def scalars(self):
        return self

    def all(self):
        return self._items


class _FakeDb:
    def __init__(self, responses):
        self._responses = list(responses)
        self.added = []
        self.committed = False

    async def execute(self, q):
        return _FakeResult(self._responses.pop(0) if self._responses else [])

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = f"fake-{id(obj)}"

    async def commit(self):
        self.committed = True


class _FakeFX:
    async def get_aud_rate(self, ccy, on_date=None):
        assert ccy == "EUR"
        return Decimal("1.60")

    async def close(self):
        pass


class PreviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_preview_enriches_aud(self):
        import services.isp_trade_import as mod
        orig = mod.FXService
        mod.FXService = lambda: _FakeFX()
        try:
            preview = await mod.preview_trades(DOUBLE_PDF.read_bytes(), account_id="acct-1")
        finally:
            mod.FXService = orig
        self.assertEqual(preview.total_trades, 2)
        self.assertEqual(preview.duplicates, 0)
        for item in preview.trades:
            self.assertEqual(item.fx_rate_to_aud, Decimal("1.60"))
            self.assertIsNotNone(item.net_amount_aud)
            self.assertIsNotNone(item.price_per_unit_aud)

    async def test_preview_marks_duplicates(self):
        import services.isp_trade_import as mod
        orig = mod.FXService
        mod.FXService = lambda: _FakeFX()
        try:
            first = await mod.preview_trades(ETF_PDF.read_bytes(), account_id="acct-1")
            existing = {t.import_hash for t in first.trades}
            second = await mod.preview_trades(ETF_PDF.read_bytes(), existing_hashes=existing, account_id="acct-1")
        finally:
            mod.FXService = orig
        self.assertEqual(second.duplicates, 1)
        self.assertTrue(all(t.duplicate for t in second.trades))


class ConfirmTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirm_inserts_and_skips_duplicates(self):
        from shared.models import Account, Transaction

        import services.isp_trade_import as mod

        account = Account(id="acct-1", user_id="u1", name="ISP", account_type="BROKERAGE")
        trades = parse_pdf(ETF_PDF.read_bytes())

        from services.isp_trade_import import IspTradePreviewItem
        items = [
            IspTradePreviewItem(
                import_hash="h1", ordine=t.ordine, isin=t.isin, description=t.description,
                transaction_type=t.transaction_type, asset_class=t.asset_class,
                quantity=t.quantity, price_per_unit=t.price_per_unit, fees=t.fees,
                net_amount=t.net_amount, executed_at=t.executed_at, settled_at=t.settled_at,
                fx_rate_to_aud=Decimal("1.6"), net_amount_aud=Decimal("1596.00"),
                price_per_unit_aud=Decimal("63.424"),
            )
            for t in trades
        ]

        # First confirm: account + existing hashes (empty) + asset lookup
        db = _FakeDb([[account], [], []])
        result = await mod.confirm_trades(db, "u1", "acct-1", items, {"h1"})
        self.assertEqual(result, {"saved": 1, "skipped_duplicates": 0})
        self.assertTrue(db.committed)
        txns = [o for o in db.added if isinstance(o, Transaction)]
        self.assertEqual(len(txns), 1)
        self.assertEqual(txns[0].transaction_type, "BUY")
        self.assertEqual(txns[0].source, "INTESA_TRADE")
        self.assertEqual(txns[0].institution, "intesa_sanpaolo")
        self.assertEqual(txns[0].import_hash, "h1")
        self.assertEqual(txns[0].currency, "EUR")

        # Second confirm with same hash: skip
        db2 = _FakeDb([[account], ["h1"], []])
        result2 = await mod.confirm_trades(db2, "u1", "acct-1", items, {"h1"})
        self.assertEqual(result2, {"saved": 0, "skipped_duplicates": 1})

    async def test_confirm_unknown_account_raises(self):
        import services.isp_trade_import as mod
        db = _FakeDb([[]])
        with self.assertRaises(LookupError):
            await mod.confirm_trades(db, "u1", "missing", [], set())


class _FakeUpload:
    def __init__(self, content: bytes, filename: str):
        self._content = content
        self.filename = filename

    async def read(self):
        return self._content


class _EmptyDb:
    async def execute(self, _q):
        return _FakeResult([])


class RouterTests(unittest.IsolatedAsyncioTestCase):
    """Tests for the PDF dispatch inside POST /api/v1/transactions/import."""

    async def test_import_rejects_non_intesa_pdf_with_422(self):
        from unittest.mock import patch, AsyncMock
        from fastapi import HTTPException
        from routers import transactions
        from shared.models import Account
        account = Account(id="acct-1", user_id="u1", name="ISP", account_type="BROKERAGE")
        fake_user = type("U", (), {"id": "u1"})()
        with patch("routers.transactions.cache_invalidate_user", AsyncMock()):
            with self.assertRaises(HTTPException) as ctx:
                await transactions.import_transactions(
                    file=_FakeUpload(b"not a pdf", "trades.pdf"),
                    account_id="acct-1", broker_hint="intesa_sanpaolo",
                    current_user=fake_user, db=_FakeDb([[account]]),
                )
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_import_rejects_pdf_without_intesa_hint(self):
        from unittest.mock import patch, AsyncMock
        from fastapi import HTTPException
        from routers import transactions
        from shared.models import Account
        account = Account(id="acct-1", user_id="u1", name="ISP", account_type="BROKERAGE")
        fake_user = type("U", (), {"id": "u1"})()
        with patch("routers.transactions.cache_invalidate_user", AsyncMock()):
            with self.assertRaises(HTTPException) as ctx:
                await transactions.import_transactions(
                    file=_FakeUpload(DOUBLE_PDF.read_bytes(), "double.pdf"),
                    account_id="acct-1", broker_hint=None,
                    current_user=fake_user, db=_FakeDb([[account]]),
                )
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_import_pdf_imports_all_trades(self):
        from unittest.mock import patch, AsyncMock
        import services.isp_trade_import as mod
        from routers import transactions
        from shared.models import Account

        orig = mod.FXService
        mod.FXService = lambda: _FakeFX()
        account = Account(id="acct-1", user_id="u1", name="ISP", account_type="BROKERAGE")
        # execute() calls: account validation, existing hashes, confirm's account lookup, confirm's existing hashes, per-asset lookups
        db = _FakeDb([[account], [], [account], [], [], []])
        fake_user = type("U", (), {"id": "u1"})()
        try:
            with patch("routers.transactions.cache_invalidate_user", AsyncMock()):
                resp = await transactions.import_transactions(
                    file=_FakeUpload(DOUBLE_PDF.read_bytes(), "double.pdf"),
                    account_id="acct-1", broker_hint="intesa_sanpaolo",
                    current_user=fake_user, db=db,
                )
        finally:
            mod.FXService = orig
        self.assertEqual(resp.broker_detected, "Intesa Sanpaolo")
        self.assertEqual(resp.total_rows, 2)
        self.assertEqual(resp.imported, 2)
        self.assertEqual(resp.duplicates, 0)

    async def test_import_pdf_dedup_on_second_import(self):
        from unittest.mock import patch, AsyncMock
        import services.isp_trade_import as mod
        from routers import transactions
        from shared.models import Account, Transaction

        orig = mod.FXService
        mod.FXService = lambda: _FakeFX()
        account = Account(id="acct-1", user_id="u1", name="ISP", account_type="BROKERAGE")
        fake_user = type("U", (), {"id": "u1"})()
        try:
            with patch("routers.transactions.cache_invalidate_user", AsyncMock()):
                # First import: account, existing hashes (empty), confirm account, confirm existing (empty), asset lookup
                db1 = _FakeDb([[account], [], [account], [], []])
                resp1 = await transactions.import_transactions(
                    file=_FakeUpload(ETF_PDF.read_bytes(), "etf.pdf"),
                    account_id="acct-1", broker_hint="intesa_sanpaolo",
                    current_user=fake_user, db=db1,
                )
                self.assertEqual(resp1.imported, 1)
                txns = [o for o in db1.added if isinstance(o, Transaction)]
                hashes = {t.import_hash for t in txns}
                # Second import: existing hashes now contain the first import's hash
                db2 = _FakeDb([[account], list(hashes), [account], list(hashes)])
                resp2 = await transactions.import_transactions(
                    file=_FakeUpload(ETF_PDF.read_bytes(), "etf.pdf"),
                    account_id="acct-1", broker_hint="intesa_sanpaolo",
                    current_user=fake_user, db=db2,
                )
        finally:
            mod.FXService = orig
        self.assertEqual(resp2.imported, 0)
        self.assertEqual(resp2.duplicates, 1)


if __name__ == "__main__":
    unittest.main()

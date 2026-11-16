import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.isp_portfolio_import import (
    cash_import_hash,
    looks_like_patrimonio,
    parse_it_number,
    parse_patrimonio,
    plan_confirm,
    scoped_hash,
    IspPreviewHolding,
)

SAMPLE = Path(__file__).resolve().parents[2] / "docs" / "intesa-sample" / "patrimonio.xlsx"


class ParseItNumberTests(unittest.TestCase):
    def test_italian_thousands_and_decimal(self):
        self.assertEqual(parse_it_number("40.912,25 €"), Decimal("40912.25"))
        self.assertEqual(parse_it_number("10.000"), Decimal("10000"))
        self.assertEqual(parse_it_number("101,039081 €"), Decimal("101.039081"))

    def test_negative_and_percent(self):
        self.assertEqual(parse_it_number("-148,91"), Decimal("-148.91"))
        self.assertEqual(parse_it_number("-1,47%"), Decimal("-1.47"))
        self.assertEqual(parse_it_number("(1.234,56 €)"), Decimal("-1234.56"))

    def test_plain_numeric_cell(self):
        self.assertEqual(parse_it_number(10595.12), Decimal("10595.12"))
        self.assertEqual(parse_it_number("10595.12"), Decimal("10595.12"))

    def test_empty_and_garbage(self):
        self.assertIsNone(parse_it_number(""))
        self.assertIsNone(parse_it_number(None))
        self.assertIsNone(parse_it_number("abc"))


class ParsePatrimonioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = parse_patrimonio(SAMPLE.read_bytes())

    def test_detects_sample_file(self):
        from services.isp_portfolio_import import _rows_from_excel
        self.assertTrue(looks_like_patrimonio(_rows_from_excel(SAMPLE.read_bytes())))
        self.assertFalse(looks_like_patrimonio([["a", "b"], ["1", "2"]]))

    def test_extracts_all_holdings_and_cash(self):
        s = self.snapshot
        self.assertEqual(len(s.holdings), 8)  # 6 BTP + 2 ETF
        self.assertEqual(s.cash_eur, Decimal("10595.12"))
        self.assertIsNotNone(s.deposit_account)
        self.assertIn("Deposito Amministrato", s.deposit_account)
        self.assertEqual(s.grand_total_eur, Decimal("40912.25"))

    def test_bond_row_normalized_to_eur_per_eur(self):
        btp = next(h for h in self.snapshot.holdings if h.isin == "IT0005622128")
        self.assertEqual(btp.asset_class, "BOND")
        self.assertEqual(btp.quantity, Decimal("10000"))
        self.assertEqual(btp.price_per_unit, Decimal("1.01039081"))
        self.assertEqual(btp.market_price_per_unit, Decimal("0.9955"))
        self.assertEqual(btp.market_value, Decimal("9955.00"))
        self.assertEqual(btp.mot_segment, "btp")
        # qty * price = market value, as the FIFO engine expects
        self.assertAlmostEqual(float(btp.quantity * btp.market_price_per_unit), 9955.0, places=4)

    def test_etf_row_keeps_per_unit_price(self):
        etf = next(h for h in self.snapshot.holdings if h.isin == "IE00B1YZSC51")
        self.assertEqual(etf.asset_class, "ETF")
        self.assertEqual(etf.quantity, Decimal("295"))
        self.assertEqual(etf.price_per_unit, Decimal("39.274983"))
        self.assertEqual(etf.market_price_per_unit, Decimal("41.49"))
        self.assertIsNone(etf.mot_segment)

    def test_all_isins_valid_and_hashes_stable(self):
        from services.isp_portfolio_import import ISIN_RE
        hashes = [h.import_hash for h in self.snapshot.holdings]
        for h in self.snapshot.holdings:
            self.assertRegex(h.isin, ISIN_RE)
        self.assertEqual(len(set(hashes)), 8)
        again = parse_patrimonio(SAMPLE.read_bytes())
        self.assertEqual([h.import_hash for h in again.holdings], hashes)

    def test_rejects_non_intesa_file(self):
        import io
        import openpyxl
        wb = openpyxl.Workbook()
        wb.active.append(["foo", "bar"])
        buf = io.BytesIO()
        wb.save(buf)
        with self.assertRaises(ValueError):
            parse_patrimonio(buf.getvalue())


class HashTests(unittest.TestCase):
    def test_scoped_hash_stable_per_account_distinct_across(self):
        a = scoped_hash("acct-1", "legacy")
        self.assertEqual(a, scoped_hash("acct-1", "legacy"))
        self.assertNotEqual(a, scoped_hash("acct-2", "legacy"))

    def test_cash_hash_depends_on_date(self):
        d1 = datetime(2026, 11, 26, tzinfo=timezone.utc)
        d2 = datetime(2026, 11, 27, tzinfo=timezone.utc)
        self.assertNotEqual(cash_import_hash(Decimal("100"), d1), cash_import_hash(Decimal("100"), d2))


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
    """Minimal async session fake: queued execute() responses + recorded writes."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.added = []
        self.executed = []
        self.committed = False

    async def execute(self, q):
        self.executed.append(q)
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


class PreviewAndConfirmTests(unittest.IsolatedAsyncioTestCase):
    async def test_preview_enriches_aud(self):
        import services.isp_portfolio_import as mod
        orig = mod.FXService
        mod.FXService = lambda: _FakeFX()
        try:
            as_of = datetime(2026, 11, 26, tzinfo=timezone.utc)
            preview = await mod.preview_snapshot(SAMPLE.read_bytes(), as_of, account_id="acct-1")
        finally:
            mod.FXService = orig
        self.assertEqual(len(preview.holdings), 8)
        self.assertEqual(preview.fx_rate_to_aud, Decimal("1.60"))
        self.assertEqual(preview.cash_aud, Decimal("16952.19"))  # 10595.12 * 1.60
        btp = next(h for h in preview.holdings if h.isin == "IT0005622128")
        self.assertEqual(btp.price_per_unit_aud, (Decimal("1.01039081") * Decimal("1.60")).quantize(Decimal("0.000001")))
        self.assertEqual(preview.duplicates, 0)

    async def test_confirm_replace_flow(self):
        import services.isp_portfolio_import as mod
        from shared.models import Account, Transaction, Price

        as_of = datetime(2026, 11, 26, tzinfo=timezone.utc)
        account = Account(id="acct-1", user_id="u1", name="ISP", account_type="BROKERAGE")
        existing_hashes = {"stale-hash", "dup-hash"}

        holdings = [
            mod.IspPreviewHolding(import_hash="dup-hash", isin="IT0005622128", description="BTP 15OT27 2,70%",
                                  asset_class="BOND", quantity=Decimal("10000"), price_per_unit=Decimal("1.01039081"),
                                  market_price_per_unit=Decimal("0.9955"), market_value=Decimal("9955.00"),
                                  fx_rate_to_aud=Decimal("1.6"), price_per_unit_aud=Decimal("1.616625"),
                                  market_value_aud=Decimal("15928.00")),
            mod.IspPreviewHolding(import_hash="new-hash", isin="IE00B1YZSC51", description="ISHARES CORE MSCI EU",
                                  asset_class="ETF", quantity=Decimal("295"), price_per_unit=Decimal("39.274983"),
                                  market_price_per_unit=Decimal("41.49"), market_value=Decimal("12239.55"),
                                  fx_rate_to_aud=Decimal("1.6"), price_per_unit_aud=Decimal("62.839973"),
                                  market_value_aud=Decimal("19583.28")),
        ]
        preview = mod.IspPreview(holdings=holdings, cash_eur=Decimal("10595.12"), cash_hash="cash-hash",
                                 cash_aud=Decimal("16952.19"), fx_rate_to_aud=Decimal("1.6"),
                                 deposit_account=None, grand_total_eur=None, total_rows=28)

        # execute() call order: Account, existing hashes, [delete], per holding: Asset lookup, Price check
        db = _FakeDb([ [account], list(existing_hashes), [], [], [], [] ])
        result = await mod.confirm_snapshot(db, "u1", "acct-1", preview, as_of, {"dup-hash", "new-hash", "cash-hash"})

        self.assertEqual(result, {"saved": 2, "skipped_duplicates": 1, "deleted_stale": 1})
        self.assertTrue(db.committed)
        txns = [o for o in db.added if isinstance(o, Transaction)]
        prices = [o for o in db.added if isinstance(o, Price)]
        # 1 TRANSFER_IN inserted (dup skipped) + 1 DEPOSIT
        self.assertEqual(len(txns), 2)
        transfer = next(t for t in txns if t.transaction_type == "TRANSFER_IN")
        self.assertEqual(transfer.import_hash, "new-hash")
        self.assertEqual(transfer.source, "INTESA_SNAPSHOT")
        self.assertEqual(transfer.currency, "EUR")
        self.assertEqual(transfer.fx_rate_to_aud, Decimal("1.6"))
        self.assertEqual(transfer.transacted_at, as_of)
        self.assertEqual(transfer.net_amount_aud, (Decimal("295") * Decimal("39.274983") * Decimal("1.6")).quantize(Decimal("0.01")))
        deposit = next(t for t in txns if t.transaction_type == "DEPOSIT")
        self.assertEqual(deposit.net_amount, Decimal("10595.12"))
        # one Price row for the inserted holding's market price
        self.assertEqual(len(prices), 1)
        self.assertEqual(prices[0].price, Decimal("41.49"))
        self.assertEqual(prices[0].currency, "EUR")


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
    async def test_upload_rejects_non_intesa_file_with_422(self):
        from fastapi import HTTPException
        from routers import isp_import
        with self.assertRaises(HTTPException) as ctx:
            await isp_import.upload_patrimonio(
                file=_FakeUpload(b"a,b\n1,2\n", "trades.csv"),
                as_of="2026-11-26", account_id=None,
                current_user=None, db=_EmptyDb(),
            )
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_upload_returns_preview_for_sample(self):
        import services.isp_portfolio_import as mod
        from routers import isp_import
        orig = mod.FXService
        mod.FXService = lambda: _FakeFX()
        try:
            resp = await isp_import.upload_patrimonio(
                file=_FakeUpload(SAMPLE.read_bytes(), "patrimonio.xlsx"),
                as_of="2026-11-26", account_id="acct-1",
                current_user=None, db=_EmptyDb(),
            )
        finally:
            mod.FXService = orig
        self.assertEqual(len(resp.holdings), 8)
        self.assertEqual(resp.cash_eur, 10595.12)
        self.assertEqual(resp.fx_rate_to_aud, 1.6)
        self.assertIn("Deposito Amministrato", resp.deposit_account)

    async def test_confirm_unknown_account_404(self):
        from fastapi import HTTPException
        from routers import isp_import
        req = isp_import.IspConfirmRequest(
            account_id="missing", as_of="2026-11-26", import_hashes=[], cash_hash="c",
            cash_eur=0, cash_aud=None, fx_rate_to_aud=None, holdings=[],
        )
        fake_user = type("U", (), {"id": "u1"})()
        with self.assertRaises(HTTPException) as ctx:
            await isp_import.confirm_patrimonio(body=req, current_user=fake_user, db=_EmptyDb())
        self.assertEqual(ctx.exception.status_code, 404)


    async def test_confirm_resolves_etf_ticker(self):
        import services.isp_portfolio_import as mod
        from shared.models import Account, Asset

        class _FakeMD:
            async def resolve_isin_to_ticker(self, isin):
                return {"IE00B1YZSC51": "IWMO.DE"}.get(isin)

        as_of = datetime(2026, 11, 26, tzinfo=timezone.utc)
        account = Account(id="acct-1", user_id="u1", name="ISP", account_type="BROKERAGE")
        holding = mod.IspPreviewHolding(
            import_hash="h-etf", isin="IE00B1YZSC51", description="ISHARES CORE MSCI EU",
            asset_class="ETF", quantity=Decimal("295"), price_per_unit=Decimal("39.274983"),
            market_price_per_unit=Decimal("41.49"), market_value=Decimal("12239.55"),
            fx_rate_to_aud=Decimal("1.6"),
        )
        preview = mod.IspPreview(holdings=[holding], cash_eur=Decimal("0"), cash_hash="c",
                                 cash_aud=None, fx_rate_to_aud=Decimal("1.6"),
                                 deposit_account=None, grand_total_eur=None, total_rows=1)
        db = _FakeDb([[account], [], [], []])
        await mod.confirm_snapshot(db, "u1", "acct-1", preview, as_of, {"h-etf"}, market_data=_FakeMD())
        assets = [o for o in db.added if isinstance(o, Asset)]
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0].polygon_ticker, "IWMO.DE")
        self.assertEqual(assets[0].isin, "IE00B1YZSC51")
        self.assertEqual(assets[0].symbol, "IE00B1YZSC51")
        self.assertEqual(assets[0].asset_class, "ETF")


class PlanConfirmTests(unittest.TestCase):
    def _holding(self, h):
        return IspPreviewHolding(
            import_hash=h, isin="IT0000000001", description="x", asset_class="BOND",
            quantity=Decimal("1"), price_per_unit=Decimal("1"), market_price_per_unit=Decimal("1"),
            market_value=Decimal("1"),
        )

    def test_insert_skip_and_delete(self):
        existing = {"old-1", "same-1"}
        holdings = [self._holding("same-1"), self._holding("new-1"), self._holding("unapproved")]
        plan = plan_confirm(existing, holdings, "cash-hash", {"same-1", "new-1", "cash-hash"})
        self.assertEqual([h.import_hash for h in plan.insert], ["new-1"])
        self.assertEqual(plan.skip_duplicates, ["same-1"])
        self.assertEqual(plan.delete_stale_hashes, ["old-1"])
        self.assertTrue(plan.insert_cash)

    def test_double_confirm_skips_everything(self):
        holdings = [self._holding("h1")]
        first = plan_confirm(set(), holdings, "cash", {"h1", "cash"})
        self.assertEqual(len(first.insert), 1)
        second = plan_confirm({"h1", "cash"}, holdings, "cash", {"h1", "cash"})
        self.assertEqual(second.insert, [])
        self.assertEqual(second.skip_duplicates, ["h1"])
        self.assertFalse(second.insert_cash)
        self.assertEqual(second.delete_stale_hashes, [])


if __name__ == "__main__":
    unittest.main()

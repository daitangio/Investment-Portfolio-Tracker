import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.portfolio_engine import PortfolioEngine, PortfolioState
from shared.models import Asset, Transaction


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _FakeScalars(self._rows)


class _FakeDb:
    def __init__(self, assets):
        self._assets = assets

    async def execute(self, _query):
        return _FakeResult(self._assets)


class _FakeMarketData:
    def __init__(self, prices=None):
        self._prices = prices or {"BTC": 30000.0}

    async def get_batch_prices(self, _symbols, _symbol_currencies=None, _symbol_meta=None):
        return self._prices


class _FakeFXService:
    @staticmethod
    def _normalize_currency(code):
        c = code.upper()
        return "USD" if c in {"USDT", "USDC", "DAI", "BUSD"} else c

    async def get_rate_on_date(self, from_currency, to_currency="AUD", on_date=None):
        from_c = self._normalize_currency(from_currency)
        to_c = self._normalize_currency(to_currency)
        if from_c == to_c:
            return Decimal("1.0")
        if from_c == "USD" and to_c == "AUD":
            return Decimal("1.7")
        if from_c == "AUD" and to_c == "USD":
            return Decimal("0.5882352941")
        if from_c == "EUR" and to_c == "AUD":
            return Decimal("1.60")
        if from_c == "AUD" and to_c == "EUR":
            return Decimal("0.625")  # 1/1.60
        if from_c == "EUR" and to_c == "USD":
            return Decimal("1.1")
        if from_c == "USD" and to_c == "EUR":
            return Decimal("0.9090909091")  # 1/1.1
        raise AssertionError(f"Unexpected FX lookup {from_currency}/{to_currency}")

    async def close(self):
        return None


class PortfolioCurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_crypto_prices_are_usd_and_realized_gain_uses_historical_fx_legs(self):
        asset = Asset(
            id="asset-btc",
            symbol="BTC",
            name="Bitcoin",
            asset_class="CRYPTO",
            currency="AUD",  # Simulates an imported asset record with account/native currency.
        )
        engine = PortfolioEngine(_FakeDb([asset]), _FakeMarketData())
        state = PortfolioState(as_of=datetime(2026, 1, 2, tzinfo=timezone.utc))

        buy = Transaction(
            id="buy-1",
            account_id="acct",
            user_id="user",
            asset_id=asset.id,
            transaction_type="BUY",
            quantity=Decimal("1"),
            price_per_unit=Decimal("10000"),
            fees=Decimal("0"),
            currency="USD",
            fx_rate_to_aud=Decimal("1.5"),
            transacted_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        sell = Transaction(
            id="sell-1",
            account_id="acct",
            user_id="user",
            asset_id=asset.id,
            transaction_type="SELL",
            quantity=Decimal("0.4"),
            price_per_unit=Decimal("20000"),
            fees=Decimal("0"),
            currency="USD",
            fx_rate_to_aud=Decimal("1.6"),
            transacted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        state = engine._apply_buy(state, buy, asset)
        state = engine._apply_sell(state, sell, asset, "FIFO")

        with patch("services.portfolio_engine.FXService", _FakeFXService):
            aud = await engine._hydrate_with_prices(state, "user", "AUD")
            usd = await engine._hydrate_with_prices(state, "user", "USD")

        self.assertEqual(aud.holdings[0].original_currency, "USD")
        self.assertEqual(aud.holdings[0].last_price, Decimal("51000.000000"))
        self.assertEqual(aud.holdings[0].total_cost_basis, Decimal("9000.0000000000"))
        self.assertEqual(aud.holdings[0].market_value, Decimal("30600.0000000000"))
        self.assertEqual(aud.total_realized_gain_long, Decimal("6800.0000000000"))

        self.assertEqual(usd.holdings[0].last_price, Decimal("30000.000000"))
        # USD display: cost basis in USD directly (0.6 × 10000 = 6000), not AUD round-trip
        self.assertEqual(usd.holdings[0].total_cost_basis, Decimal("6000.0000000000"))
        self.assertEqual(usd.holdings[0].market_value, Decimal("18000.0000000000"))
        self.assertEqual(usd.total_realized_gain_long, Decimal("4000.0000000000"))

    async def test_display_currency_toggle_preserves_unrealized_gain_sign_and_percent(self):
        asset = Asset(
            id="asset-us",
            symbol="ABC",
            name="ABC Corp",
            asset_class="EQUITY",
            currency="USD",
        )
        engine = PortfolioEngine(_FakeDb([asset]), _FakeMarketData({"ABC": 80.0}))
        state = PortfolioState(as_of=datetime(2026, 1, 2, tzinfo=timezone.utc))

        buy = Transaction(
            id="buy-abc",
            account_id="acct",
            user_id="user",
            asset_id=asset.id,
            transaction_type="BUY",
            quantity=Decimal("1"),
            price_per_unit=Decimal("100"),
            fees=Decimal("0"),
            currency="USD",
            fx_rate_to_aud=Decimal("1.0"),
            transacted_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )

        state = engine._apply_buy(state, buy, asset)

        with patch("services.portfolio_engine.FXService", _FakeFXService):
            aud = await engine._hydrate_with_prices(state, "user", "AUD")
            usd = await engine._hydrate_with_prices(state, "user", "USD")

        # Price dropped 100→80 USD. AUD display shows FX-driven gain (+36 AUD, USD weakened
        # vs AUD from 1.0 to 1.7). USD display shows price-driven loss (-20 USD, same ccy).
        self.assertEqual(aud.total_unrealized_gain, Decimal("36.0000000000"))
        self.assertEqual(usd.total_unrealized_gain, Decimal("-20.0000000000"))
        self.assertEqual(usd.holdings[0].unrealized_gain, Decimal("-20.000000"))

    async def test_income_without_open_holdings_converts_from_aud_base_for_display(self):
        engine = PortfolioEngine(_FakeDb([]), _FakeMarketData({}))
        state = PortfolioState(as_of=datetime(2026, 1, 2, tzinfo=timezone.utc))
        dividend = Transaction(
            id="div-1",
            account_id="acct",
            user_id="user",
            asset_id=None,
            transaction_type="DIVIDEND",
            net_amount=Decimal("100"),
            currency="USD",
            fx_rate_to_aud=Decimal("1.5"),
            transacted_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )

        state = engine._apply_dividend(state, dividend, None)

        with patch("services.portfolio_engine.FXService", _FakeFXService):
            aud = await engine._hydrate_with_prices(state, "user", "AUD")
            usd = await engine._hydrate_with_prices(state, "user", "USD")

        self.assertEqual(aud.dividend_income, Decimal("150.0000000000"))
        self.assertEqual(usd.dividend_income, Decimal("88.2352941176"))
        self.assertEqual(usd.holdings, [])

    async def test_eur_display_currency_conversion(self):
        """Test that EUR display currency conversion works correctly."""
        asset = Asset(
            id="asset-eur",
            symbol="ALV.DE",
            name="Allianz",
            asset_class="EQUITY",
            currency="EUR",
        )
        engine = PortfolioEngine(_FakeDb([asset]), _FakeMarketData({"ALV.DE": 100.0}))
        state = PortfolioState(as_of=datetime(2026, 1, 2, tzinfo=timezone.utc))

        buy = Transaction(
            id="buy-eur",
            account_id="acct",
            user_id="user",
            asset_id=asset.id,
            transaction_type="BUY",
            quantity=Decimal("10"),
            price_per_unit=Decimal("80"),
            fees=Decimal("0"),
            currency="EUR",
            fx_rate_to_aud=Decimal("1.6"),
            transacted_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )

        state = engine._apply_buy(state, buy, asset)

        with patch("services.portfolio_engine.FXService", _FakeFXService):
            eur = await engine._hydrate_with_prices(state, "user", "EUR")
            aud = await engine._hydrate_with_prices(state, "user", "AUD")
            usd = await engine._hydrate_with_prices(state, "user", "USD")

        # EUR display: values should be in EUR
        self.assertEqual(eur.holdings[0].original_currency, "EUR")
        self.assertEqual(eur.holdings[0].last_price, Decimal("100.000000"))
        self.assertEqual(eur.holdings[0].total_cost_basis, Decimal("800.000000"))
        self.assertEqual(eur.holdings[0].market_value, Decimal("1000.000000"))
        self.assertEqual(eur.total_market_value, Decimal("1000.000000"))
        self.assertEqual(eur.total_cost_basis, Decimal("800.000000"))

        # AUD display: EUR values converted to AUD
        # 100 EUR * 1.6 = 160 AUD (price)
        # 800 EUR * 1.6 = 1280 AUD (cost basis)
        # 1000 EUR * 1.6 = 1600 AUD (market value)
        self.assertEqual(aud.holdings[0].last_price, Decimal("160.000000"))
        self.assertEqual(aud.holdings[0].total_cost_basis, Decimal("1280.000000"))
        self.assertEqual(aud.holdings[0].market_value, Decimal("1600.000000"))
        self.assertEqual(aud.total_market_value, Decimal("1600.000000"))
        self.assertEqual(aud.total_cost_basis, Decimal("1280.000000"))

        # USD display: EUR values converted to USD via AUD pivot
        # EUR->AUD: 1.6, AUD->USD: 0.5882352941
        # EUR->USD: 1.6 * 0.5882352941 = 0.9411764706
        # 100 EUR * 0.9411764706 = 94.11764706 USD (price)
        self.assertAlmostEqual(float(usd.holdings[0].last_price), 94.11764706, places=6)


class _DateAwareFakeFXService:
    """FX service where historical and current EUR→AUD rates differ, simulating
    real-world FX drift between acquisition date and today."""

    @staticmethod
    def _normalize_currency(code):
        c = code.upper()
        return "USD" if c in {"USDT", "USDC", "DAI", "BUSD"} else c

    async def get_rate_on_date(self, from_currency, to_currency="AUD", on_date=None):
        from_c = self._normalize_currency(from_currency)
        to_c = self._normalize_currency(to_currency)
        if from_c == to_c:
            return Decimal("1.0")
        # Historical rate (2025-06-01): 1 EUR = 1.65 AUD
        # Current rate (2026-01-02):     1 EUR = 1.70 AUD
        if from_c == "EUR" and to_c == "AUD":
            if on_date is not None and on_date.year == 2025:
                return Decimal("1.65")
            return Decimal("1.70")
        if from_c == "AUD" and to_c == "EUR":
            if on_date is not None and on_date.year == 2025:
                return Decimal("0.6060606061")  # 1/1.65
            return Decimal("0.5882352941")  # 1/1.70
        raise AssertionError(f"Unexpected FX lookup {from_currency}/{to_currency} on {on_date}")

    async def close(self):
        return None


class CostBasisDisplayCurrencyTests(unittest.IsolatedAsyncioTestCase):
    """Regression: when display currency == asset currency (EUR), cost basis must
    NOT drift due to AUD round-trip with different historical/current FX rates.
    IT0005735201: 3000 EUR nominal at 100% → cost basis must be 3000 EUR, not 2907.60."""

    async def test_eur_cost_basis_unchanged_when_display_is_eur(self):
        asset = Asset(
            id="asset-btp",
            symbol="IT0005735201",
            name="BTP 15GN27 2,65%",
            asset_class="BOND",
            currency="EUR",
        )
        engine = PortfolioEngine(_FakeDb([asset]), _FakeMarketData({"IT0005735201": 1.017}))
        state = PortfolioState(as_of=datetime(2026, 1, 2, tzinfo=timezone.utc))

        buy = Transaction(
            id="buy-btp",
            account_id="acct",
            user_id="user",
            asset_id=asset.id,
            transaction_type="BUY",
            quantity=Decimal("3000"),
            price_per_unit=Decimal("1"),  # 100% of nominal, normalized
            fees=Decimal("0"),
            currency="EUR",
            fx_rate_to_aud=None,  # Force historical FX lookup (not stored)
            transacted_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )
        state = engine._apply_buy(state, buy, asset)

        with patch("services.portfolio_engine.FXService", _DateAwareFakeFXService):
            eur = await engine._hydrate_with_prices(state, "user", "EUR")

        # Cost basis in EUR display must be exactly 3000, not 3000 × 1.65/1.70 = 2911.76
        self.assertEqual(eur.holdings[0].total_cost_basis, Decimal("3000.000000"))
        self.assertEqual(eur.holdings[0].average_cost_basis, Decimal("1.000000"))
        self.assertEqual(eur.total_cost_basis, Decimal("3000.000000"))
        # Market value: 3000 × 1.017 = 3051 EUR
        self.assertEqual(eur.holdings[0].market_value, Decimal("3051.000000"))
        # last_price is 1.017; frontend multiplies by 100 for BOND display → 101.70
        self.assertEqual(eur.holdings[0].last_price, Decimal("1.017000"))

    async def test_aud_cost_basis_uses_historical_fx(self):
        """AUD display still uses historical FX for cost basis (correct for ATO)."""
        asset = Asset(
            id="asset-btp2",
            symbol="IT0005735201",
            name="BTP 15GN27 2,65%",
            asset_class="BOND",
            currency="EUR",
        )
        engine = PortfolioEngine(_FakeDb([asset]), _FakeMarketData({"IT0005735201": 1.017}))
        state = PortfolioState(as_of=datetime(2026, 1, 2, tzinfo=timezone.utc))

        buy = Transaction(
            id="buy-btp2",
            account_id="acct",
            user_id="user",
            asset_id=asset.id,
            transaction_type="BUY",
            quantity=Decimal("3000"),
            price_per_unit=Decimal("1"),
            fees=Decimal("0"),
            currency="EUR",
            fx_rate_to_aud=None,
            transacted_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )
        state = engine._apply_buy(state, buy, asset)

        with patch("services.portfolio_engine.FXService", _DateAwareFakeFXService):
            aud = await engine._hydrate_with_prices(state, "user", "AUD")

        # AUD cost basis: 3000 EUR × 1.65 (historical) = 4950 AUD
        self.assertEqual(aud.holdings[0].total_cost_basis, Decimal("4950.000000"))


if __name__ == "__main__":
    unittest.main()

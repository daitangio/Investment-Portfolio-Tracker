"""ETF market-data tests: history via resolved ticker, stored-Price fallback,
worker daily-close dedupe, and the ETFPlus live-pricing regression."""
import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.market_data_service import MarketDataService
from services.portfolio_engine import PortfolioEngine, PortfolioState, HoldingSnapshot
from shared.models import Asset, Price, Transaction


class FakeResp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def json_resp(payload):
    class JsonResp(FakeResp):
        def __init__(self):
            super().__init__(200, "")
            self._payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    return JsonResp()


class FakeHttp:
    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[str] = []

    async def get(self, url, headers=None, params=None):
        self.calls.append(url)
        for prefix, resp in self.routes.items():
            if url.startswith(prefix):
                return resp
        return FakeResp(404)


class FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)

    def all(self):
        return list(self._rows)


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return FakeScalars(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


async def _cache_none(_key):
    return None


async def _cache_noop(_key, _value, ttl=None):
    return None


class _FakeMarketData:
    def __init__(self, prices=None, history=None):
        self._prices = prices if prices is not None else {}
        self._history = history or [
            {"date": "2026-01-02", "open": 80.0, "high": 81.5, "low": 79.9, "close": 80.0, "volume": 0},
            {"date": "2026-01-05", "open": 81.0, "high": 81.9, "low": 80.5, "close": 81.39, "volume": 0},
        ]
        self.history_calls: list[dict] = []

    async def get_batch_prices(self, _symbols, _symbol_currencies=None, _symbol_meta=None):
        return self._prices

    async def get_historical_prices(self, symbol, start, end, currency="USD", asset_class=None, ticker=None):
        self.history_calls.append({"symbol": symbol, "currency": currency, "asset_class": asset_class, "ticker": ticker})
        return self._history


class _FakeFXService:
    @staticmethod
    def _normalize_currency(code):
        return code.upper()

    async def get_rate_on_date(self, from_currency, to_currency="AUD", on_date=None):
        rates = {
            ("EUR", "AUD"): Decimal("1.60"),
            ("AUD", "EUR"): Decimal("0.625"),
        }
        if from_currency.upper() == to_currency.upper():
            return Decimal("1.0")
        if (from_currency.upper(), to_currency.upper()) in rates:
            return rates[(from_currency.upper(), to_currency.upper())]
        raise AssertionError(f"Unexpected FX lookup {from_currency}/{to_currency}")

    async def close(self):
        return None


def _etf_asset(ticker=None) -> Asset:
    return Asset(
        id="asset-amundi",
        symbol="LU1900066033",
        name="AMUNDI MSCI SEMICONDUCTORS UCITS ETF ACC",
        asset_class="ETF",
        currency="EUR",
        polygon_ticker=ticker,
    )


def _state_with_buy(asset: Asset) -> PortfolioState:
    engine = PortfolioEngine.__new__(PortfolioEngine)
    state = PortfolioState(as_of=datetime(2026, 11, 22, tzinfo=timezone.utc))
    buy = Transaction(
        id="buy-1",
        account_id="acct",
        user_id="user",
        asset_id=asset.id,
        transaction_type="BUY",
        quantity=Decimal("10"),
        price_per_unit=Decimal("70"),
        fees=Decimal("0"),
        currency="EUR",
        fx_rate_to_aud=Decimal("1.6"),
        transacted_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
    )
    return engine._apply_buy(state, buy, asset)


class HistoryTickerTests(unittest.IsolatedAsyncioTestCase):
    """The resolved ticker must drive provider lookups for ISIN-keyed ETFs."""

    def _svc(self, yahoo_rows):
        svc = MarketDataService.__new__(MarketDataService)
        svc._bond_segment_cache = {}
        svc._asx_symbols = set()
        svc._http = FakeHttp({})
        svc.calls: list[str] = []

        async def polygon(symbol, start, end):
            svc.calls.append(f"polygon:{symbol}")
            return []

        async def yahoo(symbol, start, end, currency="USD"):
            svc.calls.append(f"yahoo:{symbol}")
            return [dict(r) for r in yahoo_rows]

        svc._polygon_history = polygon
        svc._yahoo_history = yahoo
        return svc

    async def test_historical_prices_use_resolved_ticker(self):
        svc = self._svc([{"date": "2026-01-05", "open": 81.0, "high": 81.9, "low": 80.5, "close": 81.39, "volume": 0}])
        with patch("services.market_data_service.cache_get", new=_cache_none), \
             patch("services.market_data_service.cache_set", new=_cache_noop):
            prices = await svc.get_historical_prices(
                "LU1900066033",
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 1, 31, tzinfo=timezone.utc),
                currency="EUR", asset_class="ETF", ticker="CHIP.MI",
            )
        self.assertEqual(svc.calls, ["polygon:CHIP.MI", "yahoo:CHIP.MI"])
        self.assertAlmostEqual(prices[-1]["close"], 81.39)

    async def test_historical_prices_without_ticker_degrade(self):
        svc = self._svc([])
        with patch("services.market_data_service.cache_get", new=_cache_none), \
             patch("services.market_data_service.cache_set", new=_cache_noop):
            prices = await svc.get_historical_prices(
                "LU1900066033",
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 1, 31, tzinfo=timezone.utc),
                currency="EUR", asset_class="ETF", ticker=None,
            )
        self.assertEqual(svc.calls, ["polygon:LU1900066033", "yahoo:LU1900066033"])
        self.assertEqual(prices, [])  # empty history, no error

    async def test_price_at_date_uses_resolved_ticker(self):
        svc = self._svc([{"date": "2026-01-05", "open": 81.0, "high": 81.9, "low": 80.5, "close": 81.11, "volume": 0}])
        with patch("services.market_data_service.cache_get", new=_cache_none), \
             patch("services.market_data_service.cache_set", new=_cache_noop):
            price = await svc.get_price_at_date(
                "LU1900066033", datetime(2026, 1, 5, tzinfo=timezone.utc), ticker="CHIP.MI"
            )
        self.assertAlmostEqual(price, 81.11)
        self.assertTrue(all(call.endswith("CHIP.MI") for call in svc.calls))

    async def test_chart_ohlcv_uses_resolved_ticker(self):
        svc = MarketDataService.__new__(MarketDataService)
        svc._bond_segment_cache = {}
        svc._asx_symbols = set()
        svc._http = FakeHttp({
            "https://query1.finance.yahoo.com/v8/finance/chart/CHIP.MI": json_resp({
                "chart": {
                    "result": [{
                        "meta": {"currency": "EUR"},
                        "timestamp": [1767225600],
                        "indicators": {"quote": [{"open": [81.0], "high": [81.9], "low": [80.5], "close": [81.39], "volume": [10]}]},
                    }],
                    "error": None,
                }
            })
        })
        with patch("services.market_data_service.cache_get", new=_cache_none), \
             patch("services.market_data_service.cache_set", new=_cache_noop):
            rows = await svc.get_chart_ohlcv(
                "LU1900066033", "D",
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 1, 31, tzinfo=timezone.utc),
                asset_class="ETF", currency="EUR", ticker="CHIP.MI",
            )
        self.assertTrue(rows)
        self.assertAlmostEqual(rows[0]["close"], 81.39)
        self.assertTrue(any(url.endswith("/CHIP.MI") for url in svc._http.calls))
        self.assertFalse(any("LU1900066033" in url for url in svc._http.calls))


class PeriodReturnTickerTests(unittest.IsolatedAsyncioTestCase):
    """Callers that hold an Asset pass its stored ticker to the history path."""

    async def test_period_price_return_passes_ticker(self):
        from routers.portfolio import _period_price_return_by_asset
        holding = HoldingSnapshot(
            asset_id="asset-amundi",
            symbol="LU1900066033",
            name="AMUNDI MSCI SEMICONDUCTORS UCITS ETF ACC",
            asset_class="ETF",
            quantity=Decimal("10"),
            average_cost_basis=Decimal("70"),
            total_cost_basis=Decimal("700"),
            last_price=Decimal("81.39"),
            market_value=Decimal("813.9"),
            unrealized_gain=Decimal("113.9"),
            unrealized_gain_pct=Decimal("16.27"),
            original_currency="EUR",
            polygon_ticker="CHIP.MI",
        )
        market_data = _FakeMarketData(history=[
            {"date": "2026-01-02", "close": 80.0},
            {"date": "2026-01-05", "close": 81.39},
        ])
        with patch("routers.portfolio.FXService", _FakeFXService):
            returns = await _period_price_return_by_asset(
                [holding],
                datetime(2026, 1, 2, tzinfo=timezone.utc),
                datetime(2026, 1, 5, tzinfo=timezone.utc),
                market_data,
            )
        self.assertEqual(market_data.history_calls[0]["ticker"], "CHIP.MI")
        self.assertAlmostEqual(returns["asset-amundi"], 1.74)  # 81.39/80 − 1, FX cancels


class _HydrateDb:
    """Routes queries by entity: Asset metadata vs stored Price rows."""

    def __init__(self, assets, price_rows):
        self._assets = assets
        self._prices = price_rows

    async def execute(self, query):
        entity = getattr(query, "column_descriptions", [{}])[0].get("entity")
        if entity is Price:
            return FakeResult(self._prices)
        return FakeResult(self._assets)


class StoredPriceFallbackTests(unittest.IsolatedAsyncioTestCase):
    """Provider down + stored Price row exists -> the portfolio still values the ETF."""

    async def test_etf_without_live_price_uses_stored_price_row(self):
        asset = _etf_asset(ticker=None)
        state = _state_with_buy(asset)
        price_row = Price(
            id="price-1",
            asset_id=asset.id,
            price=Decimal("81.39"),
            currency="EUR",
            price_date=datetime(2026, 11, 20, tzinfo=timezone.utc),
            price_type="CLOSE",
            source="IMPORT",
        )
        engine = PortfolioEngine(_HydrateDb([asset], [price_row]), _FakeMarketData(prices={}))
        with patch("services.portfolio_engine.FXService", _FakeFXService):
            aud = await engine._hydrate_with_prices(state, "user", "AUD")
        # Last-trade 81.39 EUR -> AUD via 1.60 FX; market value = 10 × that
        self.assertAlmostEqual(float(aud.holdings[0].last_price), 130.224, places=3)
        self.assertAlmostEqual(float(aud.holdings[0].market_value), 1302.24, places=2)


class EtfPlusLivePricingRegressionTests(unittest.IsolatedAsyncioTestCase):
    """Regression: ETFPLUS holdings priced live in EUR and converted to the
    display currency — not stalled on the import-time snapshot."""

    async def test_live_eur_price_flows_to_both_display_currencies(self):
        asset = _etf_asset(ticker="CHIP.MI")
        state = _state_with_buy(asset)
        engine = PortfolioEngine(_HydrateDb([asset], []), _FakeMarketData(prices={"LU1900066033": 81.39}))
        with patch("services.portfolio_engine.FXService", _FakeFXService):
            eur = await engine._hydrate_with_prices(state, "user", "EUR")
            aud = await engine._hydrate_with_prices(state, "user", "AUD")
        self.assertAlmostEqual(float(eur.holdings[0].last_price), 81.39, places=2)
        self.assertAlmostEqual(float(eur.holdings[0].market_value), 813.90, places=2)
        self.assertAlmostEqual(float(aud.holdings[0].last_price), 130.224, places=3)
        self.assertAlmostEqual(float(aud.holdings[0].market_value), 1302.24, places=2)


# ETFPlus scheda mid-session (captured live 2026-11-23, market open): last
# trade 39.56 quoted in the summary block while "Closing Price" reads N.A.,
# with Number Trades 49 and Turnover 986,540.94 in the same table — the cells
# the old unbounded parse picked garbage closes from.
ETF_SCHEDA_NA = """
<div class="l-box u-pt u-pb"> <div class="summary-value">
<span class="t-text -black-warm-60 -formatPrice">
<strong>39.56</strong>
</span> </div>
<table><tbody>
<tr><td><span class="t-text"><strong>Day Low</strong></span></td>
<td><span class="t-text -right">39.035</span></td></tr>
<tr><td><span class="t-text"><strong>Closing Price</strong></span></td>
<td><span class="t-text -right">N.A.</span></td></tr>
<tr><td><span class="t-text"><strong>Number Trades</strong></span></td>
<td><span class="t-text -right">49</span></td></tr>
<tr><td><span class="t-text"><strong>Turnover</strong></span></td>
<td><span class="t-text -right">986,540.94</span></td></tr>
</tbody></table>
"""


class _FakeSession:
    def __init__(self, assets):
        self._assets = assets
        self.added: list[Price] = []
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.commits += 1

    async def execute(self, query):
        entity = getattr(query, "column_descriptions", [{}])[0].get("entity")
        if entity is Asset:
            return FakeResult(self._assets)
        # Price existence check: dedupe against rows this session already added
        params = query.compile().params
        aid = next((v for k, v in params.items() if k.startswith("asset_id")), None)
        day = next((v for k, v in params.items() if k.startswith("price_date")), None)
        hit = next((p for p in self.added if p.asset_id == aid and p.price_date == day), None)
        return FakeResult([hit] if hit else [])


class DailyEtfPriceRefreshTests(unittest.IsolatedAsyncioTestCase):
    """The daily task appends one row per ISIN-keyed ETF per day and never duplicates."""

    async def test_refresh_appends_once_and_dedupes_same_day(self):
        from workers.tasks.market_data_tasks import _refresh_bond_prices

        bond = Asset(id="asset-btp", symbol="IT0005622128", name="BTP 15OT27 2,70%",
                     asset_class="BOND", currency="EUR")
        etf = _etf_asset()  # ISIN-keyed, no ticker needed for daily close
        plain_ticker_etf = Asset(id="asset-spy", symbol="SPY", name="SPDR S&P 500",
                                 asset_class="ETF", currency="USD")
        session = _FakeSession([bond, etf, plain_ticker_etf])

        close_day = datetime(2026, 11, 21, tzinfo=timezone.utc)
        with patch("database.AsyncSessionLocal", return_value=session), \
             patch.object(MarketDataService, "borsa_italiana_official_close",
                          AsyncMock(return_value=(Decimal("0.9954607"), close_day))), \
             patch.object(MarketDataService, "borsa_etf_official_close",
                          AsyncMock(return_value=81.39)):
            first = await _refresh_bond_prices()
            second = await _refresh_bond_prices()

        self.assertEqual(first["added"], 2)  # bond + ETF; SPY (no ISIN) skipped
        self.assertEqual(first["etfs"], 1)
        self.assertEqual(second["added"], 0)  # same day: no duplicates
        self.assertEqual(len(session.added), 2)

        etf_rows = [p for p in session.added if p.asset_id == "asset-amundi"]
        self.assertEqual(len(etf_rows), 1)
        self.assertAlmostEqual(float(etf_rows[0].price), 81.39)
        self.assertEqual(etf_rows[0].currency, "EUR")
        self.assertEqual(etf_rows[0].price_type, "CLOSE")
        self.assertEqual(etf_rows[0].source, "BORSA_ITALIANA")
        bond_rows = [p for p in session.added if p.asset_id == "asset-btp"]
        self.assertEqual(bond_rows[0].price_date, close_day)


class DailyRefreshSchedaNaGuardTests(unittest.IsolatedAsyncioTestCase):
    """Mid-session regression: a scheda quoting N.A. for the close appends no
    Price row for that asset (no garbage, no live last-trade relabeled CLOSE),
    while populated assets still get theirs and dedupe stays intact."""

    async def test_na_scheda_appends_no_row_populated_assets_still_do(self):
        from workers.tasks.market_data_tasks import _refresh_bond_prices

        bond = Asset(id="asset-btp", symbol="IT0005622128", name="BTP 15OT27 2,70%",
                     asset_class="BOND", currency="EUR")
        etf = _etf_asset()  # LU1900066033, ISIN-keyed
        session = _FakeSession([bond, etf])

        close_day = datetime(2026, 11, 21, tzinfo=timezone.utc)

        async def scheda_page(isin, segment):
            return ETF_SCHEDA_NA  # market open: closing N.A., last trade 39.56

        with patch("database.AsyncSessionLocal", return_value=session), \
             patch.object(MarketDataService, "borsa_italiana_official_close",
                          AsyncMock(return_value=(Decimal("0.9954607"), close_day))), \
             patch.object(MarketDataService, "_borsa_italiana_page", side_effect=scheda_page):
            first = await _refresh_bond_prices()
            second = await _refresh_bond_prices()

        self.assertEqual(first["added"], 1)  # bond only; the N.A. ETF is skipped
        self.assertEqual(first["bonds"], 1)
        self.assertEqual(first["etfs"], 0)
        self.assertEqual(second["added"], 0)  # dedupe intact for populated rows
        self.assertEqual(len(session.added), 1)
        rows = [(p.asset_id, p.price_type, p.source) for p in session.added]
        self.assertEqual(rows, [("asset-btp", "CLOSE", "BORSA_ITALIANA")])
        self.assertFalse(any(p.asset_id == "asset-amundi" for p in session.added))


if __name__ == "__main__":
    unittest.main()

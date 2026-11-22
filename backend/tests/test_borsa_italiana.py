import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.market_data_service import MarketDataService

# Real markup captured from borsaitaliana.it (IT0005622128, MOT btp scheda page)
BORSA_HTML = """
<div class="l-box u-pt u-pb"> <div class="summary-value">
<span class="t-text -black-warm-60 -formatPrice">
<strong>99.529</strong>
</span> </div>
<table>
<tr><td><span class="t-text"><strong>Official Close</strong></span></td>
<td><span class="t-text -right">99.54607</span></td></tr>
<tr><td><span class="t-text"><strong>Official Close Date</strong></span></td>
<td><span class="t-text -right">26/11/13</span></td></tr>
</table>
"""


class FakeResp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


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


class BorsaItalianaTests(unittest.IsolatedAsyncioTestCase):
    def test_is_isin(self):
        self.assertTrue(MarketDataService._is_isin("IT0005622128"))
        self.assertTrue(MarketDataService._is_isin("IE00B1YZSC51"))
        self.assertFalse(MarketDataService._is_isin("CBA"))
        self.assertFalse(MarketDataService._is_isin("BTC"))
        self.assertFalse(MarketDataService._is_isin(""))

    def test_bond_segments_from_name(self):
        self.assertEqual(MarketDataService.borsa_type_segments("BTP 15OT27 2,70%"), ["btp"])
        self.assertEqual(MarketDataService.borsa_type_segments("BOT ZC SEP27"), ["bot"])
        self.assertEqual(MarketDataService.borsa_type_segments("BTP Italia Nv28"), ["btp-italia"])
        self.assertEqual(MarketDataService.borsa_type_segments(None), list(MarketDataService._BOND_SEGMENTS))

    def test_parse_last_price_and_official_close(self):
        self.assertAlmostEqual(MarketDataService._parse_borsa_last_price(BORSA_HTML), 99.529)
        close = MarketDataService._parse_borsa_official_close(BORSA_HTML)
        self.assertIsNotNone(close)
        self.assertAlmostEqual(close[0], 99.54607)
        self.assertEqual(close[1], datetime(2013, 11, 26, tzinfo=timezone.utc))

    def test_parse_garbage_returns_none(self):
        self.assertIsNone(MarketDataService._parse_borsa_last_price("<html>nope</html>"))
        self.assertIsNone(MarketDataService._parse_borsa_official_close("<html>nope</html>"))

    async def test_spot_uses_working_segment_and_caches_it(self):
        svc = MarketDataService.__new__(MarketDataService)
        svc._bond_segment_cache = {}
        svc._http = FakeHttp({
            "https://www.borsaitaliana.it/borsa/obbligazioni/mot/btp/": FakeResp(200, BORSA_HTML),
        })
        price = await svc._borsa_italiana_spot("IT0005622128")
        # MOT quotes % of nominal (99.529) — normalized to EUR per EUR of nominal
        self.assertAlmostEqual(price, 0.99529)
        self.assertEqual(svc._bond_segment_cache["IT0005622128"], "btp")

    async def test_spot_market_value_matches_nominal_times_price(self):
        # Regression: IT0005622128 = EUR 10.000 nominal; dashboard must show
        # ~9952.90 EUR, not 995290 (100x off from unnormalized % price)
        svc = MarketDataService.__new__(MarketDataService)
        svc._bond_segment_cache = {}
        svc._http = FakeHttp({
            "https://www.borsaitaliana.it/borsa/obbligazioni/mot/btp/": FakeResp(200, BORSA_HTML),
        })
        price = await svc._borsa_italiana_spot("IT0005622128")
        self.assertAlmostEqual(10000 * price, 9952.90, places=2)

    async def test_spot_falls_back_to_official_close(self):
        svc = MarketDataService.__new__(MarketDataService)
        svc._bond_segment_cache = {}
        html_no_summary = BORSA_HTML.replace('<div class="summary-value">', '<div class="other">')
        svc._http = FakeHttp({
            "https://www.borsaitaliana.it/borsa/obbligazioni/mot/btp/": FakeResp(200, html_no_summary),
        })
        price = await svc._borsa_italiana_spot("IT0005622128", segments=["btp"])
        self.assertAlmostEqual(price, 0.9954607)

    async def test_spot_returns_none_when_all_segments_404(self):
        svc = MarketDataService.__new__(MarketDataService)
        svc._bond_segment_cache = {}
        svc._http = FakeHttp({})
        price = await svc._borsa_italiana_spot("IT0005622128", segments=["btp", "bot"])
        self.assertIsNone(price)
        self.assertEqual(len(svc._http.calls), 2)

    async def test_official_close_with_date(self):
        svc = MarketDataService.__new__(MarketDataService)
        svc._bond_segment_cache = {}
        svc._http = FakeHttp({
            "https://www.borsaitaliana.it/borsa/obbligazioni/mot/btp/": FakeResp(200, BORSA_HTML),
        })
        close = await svc.borsa_italiana_official_close("IT0005622128", segments=["btp"])
        self.assertIsNotNone(close)
        self.assertAlmostEqual(close[0], 0.9954607)  # normalized to EUR per EUR
        self.assertEqual(close[1].date().isoformat(), "2013-11-26")

    async def test_resolve_isin_to_ticker(self):
        svc = MarketDataService.__new__(MarketDataService)

        class JsonResp(FakeResp):
            def __init__(self):
                super().__init__(200, "")
                self._json = {"quotes": [
                    {"quoteType": "NEWS", "symbol": "X"},
                    {"quoteType": "ETF", "symbol": "IWMO.DE"},
                ]}

            def raise_for_status(self):
                pass

            def json(self):
                return self._json

        svc._http = FakeHttp({"https://query1.finance.yahoo.com/v1/finance/search": JsonResp()})
        self.assertEqual(await svc.resolve_isin_to_ticker("IE00B1YZSC51"), "IWMO.DE")


class NormalizeBondPriceTests(unittest.TestCase):
    """Regression: _normalize_bond_price must divide BOND % quotes by 100
    but leave ETF/non-bond prices unchanged."""

    def test_bond_isin_raw_pct_divided(self):
        # IT0005735201 MOT quote 101.70 → 1.017
        self.assertAlmostEqual(
            MarketDataService._normalize_bond_price(101.70, "BOND", "IT0005735201"), 1.017
        )

    def test_bond_already_per_eur_unchanged(self):
        self.assertAlmostEqual(
            MarketDataService._normalize_bond_price(0.99, "BOND", "IT0005735201"), 0.99
        )

    def test_etf_isin_unchanged(self):
        # IE00B1YZSC51 at 39.64 must NOT be divided
        self.assertAlmostEqual(
            MarketDataService._normalize_bond_price(39.64, "ETF", "IE00B1YZSC51"), 39.64
        )

    def test_etf_isin_no_class_unchanged(self):
        # Even without asset_class, ETF ISIN price must not be divided
        self.assertAlmostEqual(
            MarketDataService._normalize_bond_price(39.64, None, "IE00B1YZSC51"), 39.64
        )

    def test_none_price(self):
        self.assertIsNone(MarketDataService._normalize_bond_price(None, "BOND", "IT0005735201"))

    def test_non_isin_unchanged(self):
        self.assertAlmostEqual(MarketDataService._normalize_bond_price(150.0, None, "AAPL"), 150.0)


class YahooFallbackBondNormalizationTests(unittest.IsolatedAsyncioTestCase):
    """Regression: when Borsa Italiana is down, the Yahoo fallback for a BOND
    ISIN must still return a normalized (÷100) price, not the raw quote."""

    async def test_yahoo_fallback_normalizes_bond_price(self):
        svc = MarketDataService.__new__(MarketDataService)
        svc._bond_segment_cache = {}
        svc._asx_symbols = set()

        class YahooResp(FakeResp):
            def __init__(self):
                super().__init__(200, "")
                self._json = {
                    "chart": {
                        "result": [{
                            "meta": {"regularMarketPrice": 101.70, "previousClose": 101.50},
                        }],
                        "error": None,
                    }
                }

            def raise_for_status(self):
                pass

            def json(self):
                return self._json

        # Borsa returns 404 for all segments; Yahoo returns raw 101.70
        svc._http = FakeHttp({
            "https://query1.finance.yahoo.com/v8/finance/chart/IT0005735201": YahooResp(),
        })
        price = await svc._get_equity_price("IT0005735201", "EUR", asset_class="BOND")
        self.assertAlmostEqual(price, 1.017)

    async def test_yahoo_fallback_etf_not_normalized(self):
        svc = MarketDataService.__new__(MarketDataService)
        svc._bond_segment_cache = {}
        svc._asx_symbols = set()

        class YahooResp(FakeResp):
            def __init__(self):
                super().__init__(200, "")
                self._json = {
                    "chart": {
                        "result": [{
                            "meta": {"regularMarketPrice": 39.64, "previousClose": 39.50},
                        }],
                        "error": None,
                    }
                }

            def raise_for_status(self):
                pass

            def json(self):
                return self._json

        svc._http = FakeHttp({
            "https://query1.finance.yahoo.com/v8/finance/chart/IWMO.DE": YahooResp(),
        })
        price = await svc._get_equity_price("IE00B1YZSC51", "EUR", asset_class="ETF", ticker="IWMO.DE")
        self.assertAlmostEqual(price, 39.64)


class BondMarketValueRegressionTests(unittest.TestCase):
    """Regression: IT0005735201 — 3000 EUR nominal at MOT quote 101.70 →
    market value 3051 EUR, displayed bond price 101.70 (last_price × 100), gain ≈ +1.70%."""

    def test_market_value_and_display_price(self):
        from decimal import Decimal
        price = MarketDataService._normalize_bond_price(101.70, "BOND", "IT0005735201")
        self.assertAlmostEqual(price, 1.017)
        qty = Decimal("3000")
        market_value = qty * Decimal(str(price))
        self.assertAlmostEqual(float(market_value), 3051.0, places=1)
        # Frontend displays last_price × 100 for BOND rows
        display_price = Decimal(str(price)) * 100
        self.assertAlmostEqual(float(display_price), 101.70, places=2)
        cost = Decimal("3000")
        gain_pct = float((market_value - cost) / cost * 100)
        self.assertAlmostEqual(gain_pct, 1.70, places=1)


class NormalizeHistoryRowsTests(unittest.TestCase):
    def test_bond_rows_divided(self):
        rows = [{"date": "2026-01-01", "open": 100.5, "high": 101.7, "low": 100.2, "close": 101.7, "volume": 1000}]
        out = MarketDataService._normalize_history_rows(rows, "BOND", "IT0005735201")
        self.assertAlmostEqual(out[0]["close"], 1.017)
        self.assertAlmostEqual(out[0]["open"], 1.005)

    def test_non_bond_rows_unchanged(self):
        rows = [{"date": "2026-01-01", "open": 100.5, "high": 101.7, "low": 100.2, "close": 101.7, "volume": 1000}]
        out = MarketDataService._normalize_history_rows(rows, "ETF", "IWMO.DE")
        self.assertAlmostEqual(out[0]["close"], 101.7)

    def test_empty_rows(self):
        self.assertEqual(MarketDataService._normalize_history_rows([], "BOND", "IT0005735201"), [])


if __name__ == "__main__":
    unittest.main()

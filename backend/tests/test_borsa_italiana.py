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

# Markup captured from the ETFPlus scheda page (LU1900066033,
# /borsa/etf/scheda/LU1900066033-ETFP.html — Amundi MSCI Semiconductors)
BORSA_ETF_HTML = """
<div class="l-box u-pt u-pb"> <div class="summary-value">
<span class="t-text -black-warm-60 -formatPrice">
<strong>81.39</strong>
</span> </div>
<table><tbody>
<tr><td><span class="t-text"><strong>Day Low</strong></span></td>
<td><span class="t-text -right">81.34</span></td></tr>
<tr><td><span class="t-text"><strong>Closing Price</strong></span></td>
<td><span class="t-text -right">81.39</span></td></tr>
</tbody></table>
<table><tbody>
<tr><td><span class="t-text"><strong>Alphanumeric Code</strong></span></td>
<td><span class="t-text -right">CHIP</span></td></tr>
<tr><td><span class="t-text"><strong>Isin Code</strong></span></td>
<td><span class="t-text -right">LU1900066033</span></td></tr>
</tbody></table>
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


async def _cache_none(_key):
    return None


async def _cache_noop(_key, _value, ttl=None):
    return None


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
        # Scheda close-date cell is YY/MM/DD: "26/11/13" = 2026-11-13 (Friday's
        # close on the captured page), not 2013-11-26 (the old DD/MM/YY reading)
        self.assertEqual(close[1], datetime(2026, 11, 13, tzinfo=timezone.utc))

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
        # "26/11/13" reads YY/MM/DD = 2026-11-13 (page captured mid-Nov 2026)
        self.assertEqual(close[1].date().isoformat(), "2026-11-13")

    async def test_resolve_isin_to_ticker(self):
        svc = MarketDataService.__new__(MarketDataService)
        svc._http = FakeHttp({
            "https://query1.finance.yahoo.com/v1/finance/search": json_resp({
                "quotes": [
                    {"quoteType": "NEWS", "symbol": "X"},
                    {"quoteType": "ETF", "symbol": "IWMO.DE"},
                ]
            }),
            "https://query1.finance.yahoo.com/v8/finance/chart/IWMO.DE": json_resp(
                {"chart": {"result": [{"meta": {"currency": "EUR"}}], "error": None}}
            ),
        })
        self.assertEqual(await svc.resolve_isin_to_ticker("IE00B1YZSC51"), "IWMO.DE")

    async def test_resolve_prefers_borsa_page_ticker(self):
        # LU1900066033: Borsa scheda Alphanumeric Code CHIP -> CHIP.MI, no search at all
        svc = MarketDataService.__new__(MarketDataService)
        svc._http = FakeHttp({
            "https://www.borsaitaliana.it/borsa/etf/": FakeResp(200, BORSA_ETF_HTML),
            "https://query1.finance.yahoo.com/v8/finance/chart/CHIP.MI": json_resp(
                {"chart": {"result": [{"meta": {"currency": "EUR"}}], "error": None}}
            ),
        })
        self.assertEqual(await svc.resolve_isin_to_ticker("LU1900066033"), "CHIP.MI")
        self.assertFalse(any("/search" in url for url in svc._http.calls))

    async def test_resolve_rejects_currency_mismatch(self):
        # Only candidate is the Swiss listing whose Yahoo metadata says USD -> nothing stored
        svc = MarketDataService.__new__(MarketDataService)
        svc._http = FakeHttp({
            "https://query1.finance.yahoo.com/v1/finance/search": json_resp({
                "quotes": [{"quoteType": "ETF", "symbol": "CHIP.SW"}]
            }),
            "https://query1.finance.yahoo.com/v8/finance/chart/CHIP.SW": json_resp(
                {"chart": {"result": [{"meta": {"currency": "USD"}}], "error": None}}
            ),
        })
        self.assertIsNone(await svc.resolve_isin_to_ticker("LU1900066033"))

    async def test_resolve_prefers_mi_listing_among_candidates(self):
        # Search returns Swiss and Milan hits; the EUR Milan listing wins
        svc = MarketDataService.__new__(MarketDataService)
        svc._http = FakeHttp({
            "https://query1.finance.yahoo.com/v1/finance/search": json_resp({
                "quotes": [
                    {"quoteType": "ETF", "symbol": "CHIP.SW"},
                    {"quoteType": "ETF", "symbol": "CHIP.MI"},
                ]
            }),
            "https://query1.finance.yahoo.com/v8/finance/chart/CHIP.SW": json_resp(
                {"chart": {"result": [{"meta": {"currency": "USD"}}], "error": None}}
            ),
            "https://query1.finance.yahoo.com/v8/finance/chart/CHIP.MI": json_resp(
                {"chart": {"result": [{"meta": {"currency": "EUR"}}], "error": None}}
            ),
        })
        self.assertEqual(await svc.resolve_isin_to_ticker("LU1900066033"), "CHIP.MI")


    async def test_resolve_rejects_page_ticker_on_concrete_mismatch(self):
        # Scheda-page ticker whose Yahoo metadata contradicts the asset currency -> rejected
        svc = MarketDataService.__new__(MarketDataService)
        svc._http = FakeHttp({
            "https://www.borsaitaliana.it/borsa/etf/": FakeResp(200, BORSA_ETF_HTML),
            "https://query1.finance.yahoo.com/v8/finance/chart/CHIP.MI": json_resp(
                {"chart": {"result": [{"meta": {"currency": "CHF"}}], "error": None}}
            ),
        })
        self.assertIsNone(await svc.resolve_isin_to_ticker("LU1900066033"))

    async def test_resolve_keeps_page_ticker_when_validation_unavailable(self):
        # Yahoo rate-limits (429): the scheda page IS the Milan listing, so its
        # ticker is stored; only a concrete currency mismatch blocks it.
        svc = MarketDataService.__new__(MarketDataService)
        svc._http = FakeHttp({
            "https://www.borsaitaliana.it/borsa/etf/": FakeResp(200, BORSA_ETF_HTML),
            "https://query1.finance.yahoo.com/v8/finance/chart/CHIP.MI": FakeResp(429, "Too Many Requests"),
        })
        self.assertEqual(await svc.resolve_isin_to_ticker("LU1900066033"), "CHIP.MI")


class BorsaEtfPlusTests(unittest.IsolatedAsyncioTestCase):
    """ETF ISINs price from the ETFPlus scheda page in EUR per share —
    never divided by 100 (that normalization is bond % of nominal only)."""

    def test_parse_etf_ticker_and_closing_price(self):
        self.assertEqual(MarketDataService._parse_borsa_etf_ticker(BORSA_ETF_HTML), "CHIP")
        self.assertAlmostEqual(MarketDataService._parse_borsa_closing_price(BORSA_ETF_HTML), 81.39)

    def test_parse_etf_garbage_returns_none(self):
        self.assertIsNone(MarketDataService._parse_borsa_etf_ticker("<html>nope</html>"))
        self.assertIsNone(MarketDataService._parse_borsa_closing_price("<html>nope</html>"))

    async def test_etf_spot_eur_not_normalized(self):
        svc = MarketDataService.__new__(MarketDataService)
        svc._bond_segment_cache = {}
        svc._http = FakeHttp({"https://www.borsaitaliana.it/borsa/etf/": FakeResp(200, BORSA_ETF_HTML)})
        price = await svc._borsa_etf_spot("LU1900066033")
        self.assertAlmostEqual(price, 81.39)  # EUR per share, NOT 0.8139

    async def test_etf_spot_falls_back_to_closing_price(self):
        # summary-value destroyed (99.99 garbage); Closing Price row must take over
        svc = MarketDataService.__new__(MarketDataService)
        svc._bond_segment_cache = {}
        html = BORSA_ETF_HTML.replace('formatPrice"><strong>81.39', 'formatPrice"><strong>99.99')
        svc._http = FakeHttp({"https://www.borsaitaliana.it/borsa/etf/": FakeResp(200, html)})
        self.assertAlmostEqual(await svc._borsa_etf_spot("LU1900066033"), 81.39)

    async def test_etf_isin_priced_from_borsa_before_yahoo(self):
        # Only the scheda page route exists: the chain must stop at Borsa (81.39)
        svc = MarketDataService.__new__(MarketDataService)
        svc._bond_segment_cache = {}
        svc._asx_symbols = set()
        svc._http = FakeHttp({"https://www.borsaitaliana.it/borsa/etf/": FakeResp(200, BORSA_ETF_HTML)})
        price = await svc._get_equity_price("LU1900066033", "EUR", asset_class="ETF", ticker="CHIP.MI")
        self.assertAlmostEqual(price, 81.39)
        self.assertFalse(any("finance.yahoo" in url for url in svc._http.calls))

    async def test_get_price_etf_isin_uses_etfplus(self):
        from unittest.mock import patch
        svc = MarketDataService.__new__(MarketDataService)
        svc._bond_segment_cache = {}
        svc._asx_symbols = set()
        svc._http = FakeHttp({"https://www.borsaitaliana.it/borsa/etf/": FakeResp(200, BORSA_ETF_HTML)})
        with patch("services.market_data_service.cache_get", new=_cache_none), \
             patch("services.market_data_service.cache_set", new=_cache_noop):
            price = await svc.get_price("LU1900066033", "EUR", asset_class="ETF")
        self.assertAlmostEqual(price, 81.39)


class BondIsinAliasTests(unittest.IsolatedAsyncioTestCase):
    """Dual-ISIN retail BTPs (MEF "special"/"regular" codes): the custodied
    placement ISIN has no MOT scheda page — quotes route via the market ISIN."""

    def test_market_isin_passthrough_and_resolution(self):
        self.assertEqual(MarketDataService._market_isin("IT0005622128"), "IT0005622128")
        self.assertEqual(MarketDataService._market_isin("it0005622128"), "IT0005622128")
        self.assertIsNone(MarketDataService._market_isin(None))
        self.assertEqual(MarketDataService._market_isin("IT0005713539"), "IT0005713547")
        self.assertEqual(MarketDataService._market_isin("IT0005634792"), "IT0005634800")
        self.assertEqual(MarketDataService._market_isin("IT0005696320"), "IT0005696338")

    async def test_spot_routes_placement_isin_to_market_scheda(self):
        svc = MarketDataService.__new__(MarketDataService)
        svc._bond_segment_cache = {}
        svc._http = FakeHttp({
            "https://www.borsaitaliana.it/borsa/obbligazioni/mot/btp/scheda/IT0005713547-MOTX.html": FakeResp(200, BORSA_HTML),
        })
        price = await svc._borsa_italiana_spot("IT0005713539", segments=["btp"])
        self.assertAlmostEqual(price, 0.99529)  # MOT last 99.529 ÷ 100
        urls = " ".join(svc._http.calls)
        self.assertIn("IT0005713547", urls)
        self.assertNotIn("IT0005713539", urls)  # the custody ISIN has no page
        self.assertEqual(svc._bond_segment_cache["IT0005713547"], "btp")

    async def test_official_close_routes_placement_isin(self):
        svc = MarketDataService.__new__(MarketDataService)
        svc._bond_segment_cache = {}
        svc._http = FakeHttp({
            "https://www.borsaitaliana.it/borsa/obbligazioni/mot/btp/scheda/IT0005634800-MOTX.html": FakeResp(200, BORSA_HTML),
        })
        close = await svc.borsa_italiana_official_close("IT0005634792", segments=["btp"])
        self.assertAlmostEqual(close[0], 0.9954607)
        urls = " ".join(svc._http.calls)
        self.assertIn("IT0005634800", urls)
        self.assertNotIn("IT0005634792", urls)

    async def test_unmapped_bond_fetched_by_own_isin(self):
        # Pre-Feb-2025 retail bonds quote under their own ISIN — regression guard
        svc = MarketDataService.__new__(MarketDataService)
        svc._bond_segment_cache = {}
        svc._http = FakeHttp({
            "https://www.borsaitaliana.it/borsa/obbligazioni/mot/btp/": FakeResp(200, BORSA_HTML),
        })
        price = await svc._borsa_italiana_spot("IT0005622128", segments=["btp"])
        self.assertAlmostEqual(price, 0.99529)
        self.assertIn("IT0005622128", " ".join(svc._http.calls))


class OfficialCloseDateParseTests(unittest.TestCase):
    """The scheda close-date cell is YY/MM/DD; readings that are not plausible
    recent closes fall back to DD/MM/YY(YY); nothing plausible yields None."""

    def test_close_date_short_form_reads_yymmdd(self):
        close = MarketDataService._parse_borsa_official_close(
            BORSA_HTML.replace("26/11/13", "26/11/20"))
        self.assertEqual(close[1].date().isoformat(), "2026-11-20")  # not 2020-11-26

    def test_close_date_long_form_ddmmyyyy_fallback(self):
        # 4-digit year: YY/MM/DD reading gives year 2611 — impossible, so DD/MM/YYYY
        close = MarketDataService._parse_borsa_official_close(
            BORSA_HTML.replace("26/11/13", "20/11/2026"))
        self.assertEqual(close[1].date().isoformat(), "2026-11-20")

    def test_implausible_close_date_yields_none(self):
        # 31 Feb is not a calendar day in either reading
        close = MarketDataService._parse_borsa_official_close(
            BORSA_HTML.replace("26/11/13", "31/02/26"))
        self.assertIsNotNone(close)  # the price still parses
        self.assertIsNone(close[1])  # the date does not
        self.assertIsNone(MarketDataService._parse_borsa_close_date("15/06/91"))


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


class _RefreshResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _RefreshSession:
    """AsyncSession fake for the daily refresh task (same routing pattern as
    test_etf_market_data._FakeSession, kept inline per this file's style)."""

    def __init__(self, assets):
        self._assets = assets
        self.added = []
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
        if getattr(query, "column_descriptions", [{}])[0].get("entity").__name__ == "Asset":
            return _RefreshResult(self._assets)
        params = query.compile().params
        aid = next((v for k, v in params.items() if k.startswith("asset_id")), None)
        day = next((v for k, v in params.items() if k.startswith("price_date")), None)
        hit = next((p for p in self.added if p.asset_id == aid and p.price_date == day), None)
        return _RefreshResult([hit] if hit else [])


class RefreshBondPricesDateTests(unittest.IsolatedAsyncioTestCase):
    """Daily refresh with real scheda markup: rows are dated by the YY/MM/DD
    close cell and a second run for the same close appends no duplicate."""

    async def test_refresh_stores_true_close_date_and_dedupes(self):
        from unittest.mock import AsyncMock, patch
        from shared.models import Asset

        from workers.tasks.market_data_tasks import _refresh_bond_prices

        # Placement ISIN held in custody (Intesa sheet); market ISIN = IT0005696338
        placement = Asset(
            id="asset-btp-valore", symbol="IT0005696320", name="BTPVAL 10MZ32 SU CUM",
            asset_class="BOND", currency="EUR",
        )
        session = _RefreshSession([placement])
        scheda = BORSA_HTML.replace("26/11/13", "26/11/20")
        with patch("database.AsyncSessionLocal", return_value=session), \
             patch.object(MarketDataService, "_borsa_italiana_page", AsyncMock(return_value=scheda)):
            first = await _refresh_bond_prices()
            second = await _refresh_bond_prices()

        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["bonds"], 1)
        self.assertEqual(first["added"], 1)
        self.assertEqual(second["added"], 0)  # same close date: no duplicate
        row = session.added[0]
        self.assertEqual(row.asset_id, "asset-btp-valore")  # keyed on the custody ISIN
        self.assertEqual(row.price_date.date().isoformat(), "2026-11-20")  # not 2020-11-26
        self.assertAlmostEqual(float(row.price), 0.9954607)
        self.assertEqual(row.source, "BORSA_ITALIANA")
        self.assertEqual(row.currency, "EUR")


if __name__ == "__main__":
    unittest.main()

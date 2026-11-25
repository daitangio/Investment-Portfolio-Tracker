"""btpfacile.it fallback provider tests (openspec change add-btpfacile-btp-fallback).

Covers: quote/date parsing (against the live capture in
openspec/changes/add-btpfacile-btp-fallback/fixtures/), spot + official-close
methods, dual-ISIN alias resolution, the Borsa Italiana -> btpfacile -> Yahoo
fallback ordering, and the daily-refresh BTPFACILE Price rows.
"""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.market_data_service import MarketDataService
from shared.models import Asset, Price

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "openspec/changes/add-btpfacile-btp-fallback/fixtures/btpfacile_IT0005622128.html"
# Live capture of https://btpfacile.it/it/btp/IT0005622128 (2026-11-24): quote
# badge 99,58, "Ultimo aggiornamento prezzo" cell 24/11/2026 17:47:24.
BTPFACILE_HTML = FIXTURE.read_text(encoding="utf-8") if FIXTURE.exists() else ""

# Minimal Borsa Italiana MOT bond scheda (same shape as test_borsa_italiana.BORSA_HTML)
BORSA_BOND_HTML = """
<div class="summary-value">
<span class="t-text -black-warm-60 -formatPrice">
<strong>99.529</strong>
</span> </div>
"""


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


async def _cache_none(_key):
    return None


async def _cache_noop(_key, _value, ttl=None):
    return None


def _svc(routes: dict) -> MarketDataService:
    svc = MarketDataService.__new__(MarketDataService)
    svc._bond_segment_cache = {}
    svc._asx_symbols = set()
    svc._http = FakeHttp(routes)
    return svc


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


class _FakeSession:
    def __init__(self, assets):
        self._assets = assets
        self.added: list[Price] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        pass

    async def execute(self, query):
        entity = getattr(query, "column_descriptions", [{}])[0].get("entity")
        if entity is Asset:
            return FakeResult(self._assets)
        params = query.compile().params
        aid = next((v for k, v in params.items() if k.startswith("asset_id")), None)
        day = next((v for k, v in params.items() if k.startswith("price_date")), None)
        src = next((v for k, v in params.items() if k.startswith("source")), None)
        hit = next(
            (p for p in self.added if p.asset_id == aid and p.price_date == day and p.source == src),
            None,
        )
        return FakeResult([hit] if hit else [])


class BtpFacileParseTests(unittest.TestCase):
    def test_parse_quote_from_badge_fixture(self):
        self.assertAlmostEqual(MarketDataService._parse_btpfacile_quote(BTPFACILE_HTML), 99.58)

    def test_parse_quote_falls_back_to_prezzo_di_text(self):
        html = BTPFACILE_HTML.replace('<span class="bg-warning fs-1 txt-col-black xtxt-b px-2 py-1">99,58</span>', "")
        self.assertAlmostEqual(MarketDataService._parse_btpfacile_quote(html), 99.58)

    def test_parse_it_comma_float(self):
        self.assertAlmostEqual(MarketDataService._parse_it_comma_float("99,58"), 99.58)
        self.assertAlmostEqual(MarketDataService._parse_it_comma_float("1.234,56"), 1234.56)
        self.assertIsNone(MarketDataService._parse_it_comma_float("abc"))

    def test_parse_garbage_returns_none(self):
        self.assertIsNone(MarketDataService._parse_btpfacile_quote("<html>nope</html>"))


class BtpFacileQuoteDateTests(unittest.TestCase):
    """Task 4.2: dedicated date-parsing unit tests for _parse_btpfacile_quote_date."""

    def test_structured_cell_from_fixture(self):
        d = MarketDataService._parse_btpfacile_quote_date(BTPFACILE_HTML)
        self.assertEqual(d, datetime(2026, 11, 24, 17, 47, 24, tzinfo=timezone.utc))

    def test_h2_fallback_text(self):
        html = BTPFACILE_HTML.replace(
            '<span class="fs-6">Ultimo aggiornamento prezzo</span><br /><b>24/11/2026 17:47:24</b>', ""
        )
        d = MarketDataService._parse_btpfacile_quote_date(html)
        self.assertEqual(d, datetime(2026, 11, 24, 17, 47, 0, tzinfo=timezone.utc))

    def test_oggi_ore_relative_wording(self):
        html = "<p>ultima quotazione oggi ore 17:56.</p>"
        d = MarketDataService._parse_btpfacile_quote_date(html)
        now = datetime.now(timezone.utc)
        self.assertEqual(d, datetime(now.year, now.month, now.day, 17, 56, tzinfo=timezone.utc))

    def test_missing_timestamp_returns_none(self):
        self.assertIsNone(MarketDataService._parse_btpfacile_quote_date("<html>nope</html>"))

    def test_garbage_timestamp_returns_none(self):
        html = "Ultimo aggiornamento prezzo</span><br /><b>32/13/2026 99:99</b>"
        self.assertIsNone(MarketDataService._parse_btpfacile_quote_date(html))

    def test_invalid_calendar_date_returns_none(self):
        html = "Ultimo aggiornamento prezzo</span><br /><b>31/02/2026 10:00</b>"
        self.assertIsNone(MarketDataService._parse_btpfacile_quote_date(html))

    def test_implausible_date_outside_window_returns_none(self):
        html = "Ultimo aggiornamento prezzo</span><br /><b>01/01/1990 10:00</b>"
        self.assertIsNone(MarketDataService._parse_btpfacile_quote_date(html))


class BtpFacileSpotTests(unittest.IsolatedAsyncioTestCase):
    async def test_spot_from_fixture_normalized(self):
        svc = _svc({"https://btpfacile.it/it/btp/IT0005622128": FakeResp(200, BTPFACILE_HTML)})
        price = await svc._btpfacile_spot("IT0005622128")
        self.assertAlmostEqual(price, 0.9958)  # 99,58 % of nominal ÷ 100

    async def test_spot_resolves_market_isin_alias(self):
        svc = _svc({"https://btpfacile.it/it/btp/IT0005713547": FakeResp(200, BTPFACILE_HTML)})
        price = await svc._btpfacile_spot("IT0005713539")  # placement ISIN
        self.assertAlmostEqual(price, 0.9958)
        self.assertTrue(any("IT0005713547" in u for u in svc._http.calls))
        self.assertFalse(any("IT0005713539" in u for u in svc._http.calls))

    async def test_spot_redirect_302_returns_none(self):
        # Non-BTP ISINs get 302 -> home; httpx does not follow redirects
        svc = _svc({"https://btpfacile.it/": FakeResp(302)})
        self.assertIsNone(await svc._btpfacile_spot("LU1900066033"))

    async def test_spot_garbage_page_returns_none(self):
        svc = _svc({"https://btpfacile.it/": FakeResp(200, "<html>home</html>")})
        self.assertIsNone(await svc._btpfacile_spot("IT0005622128"))

    async def test_official_close_returns_price_and_quote_date(self):
        svc = _svc({"https://btpfacile.it/it/btp/IT0005622128": FakeResp(200, BTPFACILE_HTML)})
        close = await svc.btpfacile_official_close("IT0005622128")
        self.assertIsNotNone(close)
        price, day = close
        self.assertAlmostEqual(price, 0.9958)
        self.assertEqual(day, datetime(2026, 11, 24, 17, 47, 24, tzinfo=timezone.utc))


class BtpFacileFallbackChainTests(unittest.IsolatedAsyncioTestCase):
    async def test_borsa_429_falls_back_to_btpfacile(self):
        svc = _svc({
            "https://www.borsaitaliana.it/": FakeResp(429),
            "https://btpfacile.it/": FakeResp(200, BTPFACILE_HTML),
        })
        price = await svc._get_equity_price("IT0005622128", "EUR", asset_class="BOND")
        self.assertAlmostEqual(price, 0.9958)
        self.assertTrue(any("btpfacile.it" in u for u in svc._http.calls))

    async def test_borsa_success_never_touches_btpfacile(self):
        svc = _svc({
            "https://www.borsaitaliana.it/": FakeResp(200, BORSA_BOND_HTML),
            "https://btpfacile.it/": FakeResp(200, BTPFACILE_HTML),
        })
        price = await svc._get_equity_price("IT0005622128", "EUR", asset_class="BOND")
        self.assertAlmostEqual(price, 0.99529)
        self.assertFalse(any("btpfacile.it" in u for u in svc._http.calls))

    async def test_btpfacile_redirect_falls_through_to_yahoo(self):
        # Non-BTP ISIN: borsa down, btpfacile 302, Yahoo quotes 99.58 (% of nominal)
        svc = _svc({
            "https://www.borsaitaliana.it/": FakeResp(429),
            "https://btpfacile.it/": FakeResp(302),
            "https://query1.finance.yahoo.com/": json_resp(
                {"chart": {"result": [{"meta": {"regularMarketPrice": 99.58}}]}}
            ),
        })
        price = await svc._get_equity_price("IT0005622128", "EUR", asset_class="BOND")
        self.assertAlmostEqual(price, 0.9958)  # normalized ÷100 like every bond source

    async def test_get_price_bond_uses_btpfacile_on_borsa_429(self):
        svc = _svc({
            "https://www.borsaitaliana.it/": FakeResp(429),
            "https://btpfacile.it/": FakeResp(200, BTPFACILE_HTML),
        })
        with patch("services.market_data_service.cache_get", new=_cache_none), \
             patch("services.market_data_service.cache_set", new=_cache_noop):
            price = await svc.get_price("IT0005622128", "EUR", asset_class="BOND")
        self.assertAlmostEqual(price, 0.9958)


class DailyRefreshBtpFacileTests(unittest.IsolatedAsyncioTestCase):
    """Daily refresh stores BTPFACILE rows (quote date truncated to the day)
    when Borsa Italiana is unavailable, and dedupes on re-run."""

    async def test_borsa_down_stores_btpfacile_row_and_dedupes(self):
        from workers.tasks.market_data_tasks import _refresh_bond_prices

        bond = Asset(id="asset-btp", symbol="IT0005622128", name="BTP FX 2,7% ott 2027",
                     asset_class="BOND", currency="EUR")
        session = _FakeSession([bond])
        quote_ts = datetime(2026, 11, 24, 17, 47, 24, tzinfo=timezone.utc)

        with patch("database.AsyncSessionLocal", return_value=session), \
             patch.object(MarketDataService, "borsa_italiana_official_close", AsyncMock(return_value=None)), \
             patch.object(MarketDataService, "btpfacile_official_close",
                          AsyncMock(return_value=(0.9958, quote_ts))):
            first = await _refresh_bond_prices()
            second = await _refresh_bond_prices()

        self.assertEqual(first["added"], 1)
        self.assertEqual(first["bonds"], 1)
        self.assertEqual(second["added"], 0)  # same date: no duplicate BTPFACILE row
        self.assertEqual(len(session.added), 1)
        row = session.added[0]
        self.assertEqual(row.source, "BTPFACILE")
        self.assertEqual(row.price_type, "CLOSE")
        self.assertAlmostEqual(float(row.price), 0.9958)
        # one row per date: the quote timestamp is truncated to midnight
        self.assertEqual(row.price_date, datetime(2026, 11, 24, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()

"""
Market Data Service.

Fetches real-time and historical prices from multiple providers with
Redis caching and automatic fallback chain.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config import get_settings
from shared.cache import cache_get, cache_set

logger = logging.getLogger(__name__)
settings = get_settings()


class MarketDataService:
    """
    Multi-provider market data service with caching.

    Price priority chain:
      Equities: Polygon → Yahoo Finance → Alpha Vantage
      Crypto:   CoinGecko → CoinMarketCap
      Bonds (ISIN): Borsa Italiana MOT → Yahoo → stored Price row
    """

    CRYPTO_SYMBOLS = {
        "BTC", "ETH", "SOL", "USDT", "USDC", "BNB", "XRP", "ADA", "MATIC", "LINK",
        "DOT", "AVAX", "EIGEN", "BABY", "DOGE", "UNI", "AAVE", "ATOM", "LTC",
    }

    _YAHOO_INTERVALS = {
        "15": "15m",
        "60": "60m",
        "240": "60m",  # fetched hourly, resampled to 4h locally
        "D": "1d",
        "W": "1wk",
    }

    # ISIN pattern: 2-letter country prefix + 9 alphanumerics + check digit
    _ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")

    # Borsa Italiana MOT path segments to try for Italian government bonds
    _BOND_SEGMENTS = ("btp", "bot", "cct", "ctz", "btp-italia", "btp-valore", "btp-green", "btp-futura")
    _BORSA_BASE = "https://www.borsaitaliana.it"
    _UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}

    def __init__(self):
        self._http = httpx.AsyncClient(timeout=15.0, limits=httpx.Limits(max_connections=100))
        self._asx_symbols: set[str] = set()  # Track symbols that need .AX suffix
        self._bond_segment_cache: dict[str, str] = {}  # ISIN -> working MOT segment

    @classmethod
    def _is_isin(cls, symbol: str) -> bool:
        return bool(symbol) and bool(cls._ISIN_RE.match(symbol))

    @classmethod
    def borsa_type_segments(cls, name: Optional[str]) -> list[str]:
        """Candidate MOT path segments derived from an instrument name."""
        if not name:
            return list(cls._BOND_SEGMENTS)
        desc = name.upper()
        for prefix, segment in (
            ("BTP ITALIA", "btp-italia"), ("BTP VALORE", "btp-valore"),
            ("BTP GREEN", "btp-green"), ("BTP FUTURA", "btp-futura"),
            ("BTP", "btp"), ("BOT", "bot"), ("CCT", "cct"), ("CTZ", "ctz"),
        ):
            if desc.startswith(prefix):
                return [segment]
        return list(cls._BOND_SEGMENTS)

    async def get_price(self, symbol: str, currency: str = "USD", asset_class: Optional[str] = None) -> Optional[float]:
        """Get current price for a single symbol."""
        # For AUD assets, use .AX cache key to differentiate from US version
        cache_suffix = ":AX" if currency.upper() == "AUD" else ""
        cache_key = f"market:price:{symbol}{cache_suffix}:spot"
        cached = await cache_get(cache_key)
        if cached is not None:
            return cached

        price = None
        if self._is_crypto(symbol):
            price = await self._get_crypto_price(symbol)
        elif asset_class == "BOND" or (asset_class is None and self._is_isin(symbol)):
            # Italian government bonds etc. are priced by ISIN on Borsa Italiana
            price = await self._borsa_italiana_spot(symbol)
            if price is None:
                price = await self._get_equity_price(symbol, currency, asset_class=asset_class)
        else:
            price = await self._get_equity_price(symbol, currency)

        if price is not None:
            await cache_set(cache_key, price, ttl=60)  # 60s TTL for spot prices

        return price

    async def get_batch_prices(
        self,
        symbols: list[str],
        symbol_currencies: Optional[dict[str, str]] = None,
        symbol_meta: Optional[dict[str, dict]] = None,
    ) -> dict[str, float]:
        """
        Get current prices for multiple symbols efficiently.
        symbol_currencies: optional dict of {symbol: currency} to resolve exchange.
        symbol_meta: optional dict of {symbol: {"asset_class":..., "ticker":...}}.
        """
        if not symbols:
            return {}

        ccys = symbol_currencies or {}
        meta = symbol_meta or {}

        # Check cache first
        result: dict[str, float] = {}
        uncached: list[str] = []

        for sym in symbols:
            ccy = ccys.get(sym, "USD").upper()
            cache_suffix = ":AX" if ccy == "AUD" else ""
            cached = await cache_get(f"market:price:{sym}{cache_suffix}:spot")
            if cached is not None:
                result[sym] = cached
            else:
                uncached.append(sym)

        if not uncached:
            return result

        # Separate equity vs crypto
        crypto_syms = [s for s in uncached if self._is_crypto(s)]
        equity_syms = [s for s in uncached if not self._is_crypto(s)]

        if crypto_syms:
            crypto_prices = await self._get_batch_crypto_prices(crypto_syms)
            result.update(crypto_prices)
            for sym, price in crypto_prices.items():
                await cache_set(f"market:price:{sym}:spot", price, ttl=60)

        if equity_syms:
            equity_prices = await self._get_batch_equity_prices(equity_syms, ccys, meta)
            result.update(equity_prices)
            for sym, price in equity_prices.items():
                ccy = ccys.get(sym, "USD").upper()
                cache_suffix = ":AX" if ccy == "AUD" else ""
                await cache_set(f"market:price:{sym}{cache_suffix}:spot", price, ttl=60)

        return result

    async def get_historical_prices(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        currency: str = "USD",
        asset_class: Optional[str] = None,
    ) -> list[dict]:
        """
        Get daily OHLCV prices for a symbol over a date range.
        Returns list of {date, open, high, low, close, volume}.
        """
        cache_suffix = ":AX" if currency.upper() == "AUD" else ""
        cache_key = f"market:history:{symbol}{cache_suffix}:{start_date.date()}:{end_date.date()}"
        cached = await cache_get(cache_key)
        if cached is not None:
            return cached

        if self._is_crypto(symbol):
            prices = await self._get_crypto_history(symbol, start_date, end_date)
        else:
            prices = await self._get_equity_history(symbol, start_date, end_date, currency, asset_class=asset_class)

        if prices:
            # Cache historical data for longer
            await cache_set(cache_key, prices, ttl=3600 * 6)

        return prices

    async def get_chart_ohlcv(
        self,
        symbol: str,
        interval: str,
        start_date: datetime,
        end_date: datetime,
        asset_class: Optional[str] = None,
        currency: str = "USD",
        exchange: Optional[str] = None,
    ) -> list[dict]:
        """
        Get OHLCV candles for chart/signal analysis.

        interval accepts TradingView-style values used by the frontend:
        "15", "60", "240", "D", "W".
        """
        interval = interval.upper()
        if interval not in self._YAHOO_INTERVALS:
            raise ValueError(f"Unsupported interval: {interval}")

        cache_suffix = f":{exchange or currency or ''}:{asset_class or ''}"
        cache_key = (
            f"market:chart:{symbol}:{interval}{cache_suffix}:"
            f"{int(start_date.timestamp())}:{int(end_date.timestamp())}"
        )
        cached = await cache_get(cache_key)
        if cached is not None:
            return cached

        rows = await self._yahoo_chart_history(
            symbol=symbol,
            interval=interval,
            start=start_date,
            end=end_date,
            asset_class=asset_class,
            currency=currency,
            exchange=exchange,
        )

        if rows:
            await cache_set(cache_key, rows, ttl=300 if interval in {"15", "60", "240"} else 3600)
        return rows

    async def get_price_at_date(self, symbol: str, date: datetime) -> Optional[float]:
        """Get the closing price for a symbol on a specific date."""
        cache_key = f"market:price:{symbol}:{date.date()}:close"
        cached = await cache_get(cache_key)
        if cached is not None:
            return cached

        prices = await self.get_historical_prices(symbol, date, date + timedelta(days=1))
        if prices:
            price = prices[-1]["close"]
            await cache_set(cache_key, price, ttl=86400)  # Cache historical prices 24h
            return price
        return None

    # ─── Equity Providers ────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4))
    async def _get_equity_price(
        self, symbol: str, currency: str = "USD", asset_class: Optional[str] = None, ticker: Optional[str] = None
    ) -> Optional[float]:
        """Polygon → Yahoo Finance fallback. Currency hint for exchange resolution."""
        # Bonds and other ISIN-keyed instruments: Borsa Italiana first
        if asset_class == "BOND" or (asset_class is None and self._is_isin(symbol)):
            price = await self._borsa_italiana_spot(symbol)
            if price is not None:
                return price

        lookup = ticker or symbol  # resolved alias (e.g. Yahoo ticker for an ETF ISIN)
        # Skip Polygon for AUD assets (it doesn't support ASX)
        if currency.upper() != "AUD":
            try:
                p = await self._polygon_spot(lookup)
                if p is not None:
                    return self._normalize_bond_price(p, asset_class, symbol)
            except Exception as e:
                logger.warning(f"Polygon failed for {lookup}: {e}")

        try:
            p = await self._yahoo_spot(lookup, currency)
            return self._normalize_bond_price(p, asset_class, symbol)
        except Exception as e:
            logger.warning(f"Yahoo failed for {lookup}: {e}")

        return None

    async def _get_batch_equity_prices(
        self,
        symbols: list[str],
        symbol_currencies: Optional[dict[str, str]] = None,
        symbol_meta: Optional[dict[str, dict]] = None,
    ) -> dict[str, float]:
        """Fetch multiple equity prices."""
        ccys = symbol_currencies or {}
        meta = symbol_meta or {}
        results = {}
        for sym in symbols:
            ccy = ccys.get(sym, "USD")
            m = meta.get(sym, {})
            price = await self._get_equity_price(
                sym, ccy, asset_class=m.get("asset_class"), ticker=m.get("ticker")
            )
            if price is not None:
                results[sym] = price
        return results

    async def _polygon_spot(self, symbol: str) -> Optional[float]:
        """Fetch last trade price from Polygon.io."""
        api_key = settings.polygon_api_key.get_secret_value()
        if not api_key:
            return None

        url = f"https://api.polygon.io/v2/last/trade/{symbol}"
        resp = await self._http.get(url, headers={"Authorization": f"Bearer {api_key}"})
        resp.raise_for_status()
        data = resp.json()
        return float(data["results"]["p"])  # price

    async def _yahoo_spot(self, symbol: str, currency: str = "USD") -> Optional[float]:
        """Fetch price from Yahoo Finance. For AUD assets, tries .AX first (ASX)."""
        # AUD assets → try .AX first, then plain; USD assets → plain first, then .AX
        if currency.upper() == "AUD":
            suffixes = (".AX", "")
        else:
            suffixes = ("", ".AX")

        for suffix in suffixes:
            try:
                yf_symbol = f"{symbol}{suffix}"
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_symbol}"
                headers = {"User-Agent": "Mozilla/5.0"}
                resp = await self._http.get(url, headers=headers, params={"interval": "1d", "range": "1d"})
                resp.raise_for_status()
                data = resp.json()
                meta = data["chart"]["result"][0]["meta"]
                price = float(meta.get("regularMarketPrice", meta.get("previousClose", 0)))
                if price > 0:
                    if suffix == ".AX":
                        self._asx_symbols.add(symbol)
                    return price
            except Exception as e:
                logger.debug(f"Yahoo spot {symbol}{suffix}: {e}")
                continue
        return None

    # ─── Borsa Italiana MOT (Italian government bonds, priced by ISIN) ────

    @staticmethod
    def _parse_it_float(text: str) -> Optional[float]:
        """Borsa Italiana en pages print plain dot-decimals like 99.54607."""
        try:
            return float(text.replace(",", ""))
        except ValueError:
            return None

    @classmethod
    def _parse_borsa_last_price(cls, html: str) -> Optional[float]:
        """Big summary price: <div class="summary-value"> ... -formatPrice"> <strong>99.529</strong>"""
        m = re.search(r'summary-value.*?-formatPrice">\s*<strong>\s*([\d]+(?:[.,][\d]+)?)', html, re.S)
        return cls._parse_it_float(m.group(1)) if m else None

    @classmethod
    def _parse_borsa_official_close(cls, html: str) -> Optional[tuple[float, Optional[datetime]]]:
        """Market data table: <strong>Official Close</strong> ... <span class="t-text -right">99.54607</span>"""
        m = re.search(r'Official Close</strong>.*?t-text -right">\s*([\d]+(?:[.,][\d]+)?)', html, re.S)
        if not m:
            return None
        price = cls._parse_it_float(m.group(1))
        if price is None:
            return None
        day = None
        dm = re.search(r'Official Close Date</strong>.*?t-text -right">\s*(\d{2}/\d{2}/\d{2,4})', html, re.S)
        if dm:
            try:
                day = datetime.strptime(dm.group(1), "%d/%m/%y" if len(dm.group(1)) == 8 else "%d/%m/%Y").replace(tzinfo=timezone.utc)
            except ValueError:
                day = None
        return price, day

    async def _borsa_italiana_page(self, isin: str, segment: str) -> Optional[str]:
        url = f"{self._BORSA_BASE}/borsa/obbligazioni/mot/{segment}/scheda/{isin}-MOTX.html?lang=en"
        try:
            resp = await self._http.get(url, headers=self._UA)
        except Exception as e:
            logger.debug(f"Borsa Italiana {isin} ({segment}): {e}")
            return None
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            logger.debug(f"Borsa Italiana {isin} ({segment}): HTTP {resp.status_code}")
            return None
        return resp.text

    @staticmethod
    def _borsa_price_per_eur(quoted_pct: float) -> float:
        """MOT quotes bond prices as % of nominal (99.529); our Price rows and
        cost basis use EUR per EUR of nominal, so divide by 100. This keeps
        quantity(nominal) × price = market value in the portfolio engine."""
        return quoted_pct / 100.0

    @staticmethod
    def _normalize_bond_price(price: Optional[float], asset_class: Optional[str], symbol: str) -> Optional[float]:
        """Normalize a raw price to EUR-per-EUR-of-nominal for BOND assets.

        Borsa Italiana MOT quotes % of nominal (e.g. 101.70); fallback providers
        (Yahoo, Polygon) return the same raw quote for bond ISINs. Divide by 100
        so quantity(nominal) × price = market value holds consistently across
        all sources. Only applies when asset_class is explicitly "BOND" — when
        asset_class is unknown, ETF ISINs (e.g. price 39.64) must NOT be divided.
        """
        if price is None:
            return None
        if asset_class == "BOND" and price >= 10:
            return price / 100.0
        return price

    async def _borsa_italiana_spot(self, isin: str, segments: Optional[list[str]] = None) -> Optional[float]:
        """Last-trade price (fallback: official close) for a bond ISIN from Borsa
        Italiana, normalized to EUR per EUR of nominal."""
        isin = isin.upper()
        if isin in self._bond_segment_cache:
            candidates = [self._bond_segment_cache[isin]]
        else:
            candidates = segments or list(self._BOND_SEGMENTS)
        for segment in candidates:
            html = await self._borsa_italiana_page(isin, segment)
            if html is None:
                continue
            price = self._parse_borsa_last_price(html)
            if price is None:
                close = self._parse_borsa_official_close(html)
                price = close[0] if close else None
            if price:
                self._bond_segment_cache[isin] = segment
                return self._borsa_price_per_eur(price)
        return None

    async def borsa_italiana_official_close(
        self, isin: str, segments: Optional[list[str]] = None
    ) -> Optional[tuple[float, datetime]]:
        """Official close price (EUR per EUR of nominal) + date for a bond ISIN
        (used by the daily refresh task)."""
        isin = isin.upper()
        candidates = [self._bond_segment_cache[isin]] if isin in self._bond_segment_cache else (segments or list(self._BOND_SEGMENTS))
        for segment in candidates:
            html = await self._borsa_italiana_page(isin, segment)
            if html is None:
                continue
            close = self._parse_borsa_official_close(html)
            if close and close[0]:
                self._bond_segment_cache[isin] = segment
                return self._borsa_price_per_eur(close[0]), close[1] or datetime.now(timezone.utc)
        return None

    async def resolve_isin_to_ticker(self, isin: str) -> Optional[str]:
        """Resolve an ISIN (e.g. an ETF) to a Yahoo Finance ticker via symbol search."""
        try:
            resp = await self._http.get(
                "https://query1.finance.yahoo.com/v1/finance/search",
                headers=self._UA,
                params={"q": isin, "quotesCount": 8, "newsCount": 0},
            )
            resp.raise_for_status()
            for quote in resp.json().get("quotes", []):
                if quote.get("quoteType") in ("EQUITY", "ETF", "MUTUALFUND") and quote.get("symbol"):
                    return quote["symbol"]
        except Exception as e:
            logger.debug(f"Yahoo ISIN search failed for {isin}: {e}")
        return None

    async def _get_equity_history(self, symbol: str, start: datetime, end: datetime, currency: str = "USD", asset_class: Optional[str] = None) -> list[dict]:
        """Fetch OHLCV from Polygon or Yahoo."""
        if currency.upper() != "AUD":
            try:
                prices = await self._polygon_history(symbol, start, end)
                if prices:
                    return self._normalize_history_rows(prices, asset_class, symbol)
            except Exception:
                pass
        try:
            prices = await self._yahoo_history(symbol, start, end, currency)
            return self._normalize_history_rows(prices, asset_class, symbol)
        except Exception:
            return []

    @staticmethod
    def _normalize_history_rows(rows: list[dict], asset_class: Optional[str], symbol: str) -> list[dict]:
        """Divide OHLC values by 100 for BOND assets so historical prices match
        the EUR-per-EUR-of-nominal convention used by spot prices."""
        if asset_class != "BOND" or not rows:
            return rows
        out = []
        for r in rows:
            nr = dict(r)
            for k in ("open", "high", "low", "close"):
                v = nr.get(k)
                if v is not None and v >= 10:
                    nr[k] = v / 100.0
            out.append(nr)
        return out

    async def _polygon_history(self, symbol: str, start: datetime, end: datetime) -> list[dict]:
        api_key = settings.polygon_api_key.get_secret_value()
        if not api_key:
            return []

        url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day/{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}"
        resp = await self._http.get(url, params={"adjusted": "true"}, headers={"Authorization": f"Bearer {api_key}"})
        resp.raise_for_status()
        data = resp.json()

        return [
            {
                "date": datetime.fromtimestamp(r["t"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d"),
                "open": r["o"], "high": r["h"], "low": r["l"],
                "close": r["c"], "volume": r["v"],
            }
            for r in data.get("results", [])
        ]

    async def _yahoo_history(self, symbol: str, start: datetime, end: datetime, currency: str = "USD") -> list[dict]:
        suffixes = (".AX", "") if currency.upper() == "AUD" else ("", ".AX")
        headers = {"User-Agent": "Mozilla/5.0"}
        params = {
            "interval": "1d",
            "period1": int(start.timestamp()),
            "period2": int(end.timestamp()),
        }

        for suffix in suffixes:
            try:
                yf_symbol = f"{symbol}{suffix}"
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_symbol}"
                resp = await self._http.get(url, headers=headers, params=params)
                resp.raise_for_status()
                data = resp.json()
                result = data["chart"]["result"][0]
                timestamps = result["timestamp"]
                quotes = result["indicators"]["quote"][0]
                rows = [
                    {
                        "date": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"),
                        "open": quotes["open"][i], "high": quotes["high"][i],
                        "low": quotes["low"][i], "close": quotes["close"][i],
                        "volume": quotes["volume"][i],
                    }
                    for i, ts in enumerate(timestamps)
                    if quotes["close"][i] is not None
                ]
                if rows:
                    if suffix == ".AX":
                        self._asx_symbols.add(symbol)
                    return rows
            except Exception as e:
                logger.debug(f"Yahoo history {symbol}{suffix}: {e}")
                continue
        return []

    async def _yahoo_chart_history(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
        asset_class: Optional[str] = None,
        currency: str = "USD",
        exchange: Optional[str] = None,
    ) -> list[dict]:
        """Fetch timeframe-aware OHLCV from Yahoo Finance chart API."""
        import pandas as pd

        yahoo_interval = self._YAHOO_INTERVALS[interval]
        yf_symbols = self._yahoo_symbol_candidates(symbol, asset_class, currency, exchange)
        headers = {"User-Agent": "Mozilla/5.0"}
        params = {
            "interval": yahoo_interval,
            "period1": int(start.timestamp()),
            "period2": int(end.timestamp()),
            "includePrePost": "false",
        }

        for yf_symbol in yf_symbols:
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_symbol}"
                resp = await self._http.get(url, headers=headers, params=params)
                resp.raise_for_status()
                data = resp.json()
                result = data["chart"]["result"][0]
                timestamps = result.get("timestamp") or []
                quotes = result.get("indicators", {}).get("quote", [{}])[0]
                rows = [
                    {
                        "date": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                        "open": quotes.get("open", [None])[i],
                        "high": quotes.get("high", [None])[i],
                        "low": quotes.get("low", [None])[i],
                        "close": quotes.get("close", [None])[i],
                        "volume": quotes.get("volume", [None])[i] or 0,
                    }
                    for i, ts in enumerate(timestamps)
                    if quotes.get("close", [None])[i] is not None
                ]
                if not rows:
                    continue

                if interval == "240":
                    df = pd.DataFrame(rows)
                    df["date"] = pd.to_datetime(df["date"], utc=True)
                    df = (
                        df.set_index("date")
                        .resample("4h", label="right", closed="right")
                        .agg({
                            "open": "first",
                            "high": "max",
                            "low": "min",
                            "close": "last",
                            "volume": "sum",
                        })
                        .dropna(subset=["close"])
                    )
                    rows = [
                        {
                            "date": idx.isoformat(),
                            "open": row["open"],
                            "high": row["high"],
                            "low": row["low"],
                            "close": row["close"],
                            "volume": row["volume"],
                        }
                        for idx, row in df.iterrows()
                    ]

                if yf_symbol.endswith(".AX"):
                    self._asx_symbols.add(symbol)
                return self._normalize_history_rows(rows, asset_class, symbol)
            except Exception as e:
                logger.debug("Yahoo chart history %s %s failed: %s", yf_symbol, interval, e)
                continue
        return []

    def _yahoo_symbol_candidates(
        self,
        symbol: str,
        asset_class: Optional[str] = None,
        currency: str = "USD",
        exchange: Optional[str] = None,
    ) -> list[str]:
        sym = symbol.upper()
        if asset_class == "CRYPTO" or self._is_crypto(sym):
            return [f"{sym}-USD", sym]
        if sym.endswith(".AX"):
            return [sym, sym.removesuffix(".AX")]
        if (exchange and "ASX" in exchange.upper()) or currency.upper() == "AUD":
            return [f"{sym}.AX", sym]
        return [sym, f"{sym}.AX"]

    # ─── Crypto Providers ────────────────────────────────────────────────

    async def _get_crypto_price(self, symbol: str) -> Optional[float]:
        """CoinGecko spot price."""
        prices = await self._get_batch_crypto_prices([symbol])
        return prices.get(symbol)

    async def _get_batch_crypto_prices(self, symbols: list[str]) -> dict[str, float]:
        """Batch CoinGecko price fetch."""
        try:
            return await self._coingecko_batch(symbols)
        except Exception as e:
            logger.warning(f"CoinGecko batch failed: {e}")
            return {}

    async def _coingecko_batch(self, symbols: list[str]) -> dict[str, float]:
        """CoinGecko simple/price endpoint for multiple coins."""
        # Map symbols to CoinGecko IDs
        id_map = self._symbol_to_coingecko_id(symbols)
        coin_ids = list(id_map.values())
        if not coin_ids:
            return {}

        params: dict = {"ids": ",".join(coin_ids), "vs_currencies": "usd"}
        api_key = settings.coingecko_api_key.get_secret_value()
        if api_key and not api_key.startswith("your-"):
            params["x_cg_pro_api_key"] = api_key

        resp = await self._http.get("https://api.coingecko.com/api/v3/simple/price", params=params)
        resp.raise_for_status()
        data = resp.json()

        result = {}
        for sym, cg_id in id_map.items():
            if cg_id in data and "usd" in data[cg_id]:
                result[sym] = data[cg_id]["usd"]
        return result

    async def _get_crypto_history(self, symbol: str, start: datetime, end: datetime) -> list[dict]:
        """CoinGecko historical prices."""
        import asyncio
        cg_id = self._symbol_to_coingecko_id([symbol]).get(symbol)
        if not cg_id:
            return []

        params = {
            "vs_currency": "usd",
            "from": int(start.timestamp()),
            "to": int(end.timestamp()),
        }
        try:
            # Small delay to avoid CoinGecko rate limits (free tier: ~10-30 req/min)
            await asyncio.sleep(0.5)
            resp = await self._http.get(
                f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart/range",
                params=params,
            )
            if resp.status_code == 429:
                logger.warning(f"CoinGecko rate limit for {symbol}, retrying after delay")
                await asyncio.sleep(5)
                resp = await self._http.get(
                    f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart/range",
                    params=params,
                )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"CoinGecko history failed for {symbol} ({cg_id}): {e}")
            return []

        # Deduplicate by date (CoinGecko can return multiple points per day for short ranges)
        seen_dates: set[str] = set()
        results: list[dict] = []
        for p in data.get("prices", []):
            date_str = datetime.fromtimestamp(p[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            if date_str not in seen_dates:
                seen_dates.add(date_str)
                results.append({
                    "date": date_str,
                    "close": p[1], "open": p[1], "high": p[1], "low": p[1], "volume": 0,
                })
        return results

    # ─── Utilities ───────────────────────────────────────────────────────

    def _is_crypto(self, symbol: str) -> bool:
        return symbol.upper() in self.CRYPTO_SYMBOLS

    @staticmethod
    def _symbol_to_coingecko_id(symbols: list[str]) -> dict[str, str]:
        MAPPING = {
            "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
            "USDT": "tether", "USDC": "usd-coin", "BNB": "binancecoin",
            "XRP": "ripple", "ADA": "cardano", "MATIC": "matic-network",
            "LINK": "chainlink", "DOT": "polkadot", "AVAX": "avalanche-2",
            "DOGE": "dogecoin", "UNI": "uniswap", "AAVE": "aave",
            "ATOM": "cosmos", "LTC": "litecoin", "BCH": "bitcoin-cash",
            "ALGO": "algorand", "XLM": "stellar",
            "EIGEN": "eigenlayer", "BABY": "babylon",
        }
        return {sym: MAPPING[sym.upper()] for sym in symbols if sym.upper() in MAPPING}

    async def close(self):
        await self._http.aclose()

"""
Binance Public Futures API Client — No API Key Required
Uses FAPI (futures) endpoints with automatic fallback URLs
to bypass geo-blocks (HTTP 451) on fapi.binance.com
"""

import aiohttp
import asyncio
import logging
from typing import List, Dict, Optional
from config import MIN_VOLUME_USD, TOP_PAIRS_LIMIT

logger = logging.getLogger(__name__)

# Binance provides alternative base URLs for geo-restricted regions.
# The client tries each one in order until one works.
FAPI_BASE_URLS = [
    "https://fapi.binance.com",       # Primary
    "https://fapi1.binance.com",      # Fallback 1
    "https://fapi2.binance.com",      # Fallback 2
    "https://fapi3.binance.com",      # Fallback 3
    "https://fapi4.binance.com",      # Fallback 4
]


class BinanceClient:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self._base_url: Optional[str] = None  # cached working URL

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def _get_working_base_url(self) -> str:
        """
        Try each Binance futures base URL and return the first one
        that responds without a geo-block (451) or connection error.
        Result is cached for the session lifetime.
        """
        if self._base_url:
            return self._base_url

        session = await self._get_session()
        for url in FAPI_BASE_URLS:
            try:
                test_url = f"{url}/fapi/v1/ping"
                async with session.get(test_url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        logger.info(f"✅ Using Binance futures URL: {url}")
                        self._base_url = url
                        return url
                    else:
                        logger.warning(f"⚠️ {url} returned HTTP {resp.status}, trying next...")
            except Exception as e:
                logger.warning(f"⚠️ {url} unreachable: {e}, trying next...")

        raise ConnectionError(
            "❌ All Binance futures endpoints are geo-blocked or unreachable.\n"
            "Your server IP is restricted by Binance (HTTP 451).\n"
            "Fix: Run the bot on a VPS in an unrestricted country (e.g. Germany, Netherlands, Singapore)."
        )

    async def get(self, path: str, params: dict = None) -> any:
        base = await self._get_working_base_url()
        session = await self._get_session()
        url = f"{base}{path}"
        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 451:
                    logger.warning(f"HTTP 451 on {base}, trying next fallback URL...")
                    self._base_url = None
                    idx = FAPI_BASE_URLS.index(base) if base in FAPI_BASE_URLS else -1
                    remaining = FAPI_BASE_URLS[idx+1:] if idx >= 0 else []
                    if not remaining:
                        raise ConnectionError("All Binance futures URLs are geo-blocked (HTTP 451). Use a VPS or proxy.")
                    next_base = remaining[0]
                    async with session.get(f"{next_base}{path}", params=params) as resp2:
                        resp2.raise_for_status()
                        self._base_url = next_base
                        return await resp2.json()
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientResponseError as e:
            if e.status == 451:
                raise ConnectionError(
                    "Binance futures API geo-blocked (HTTP 451).\n"
                    "Run the bot on a VPS in an unrestricted region."
                ) from e
            logger.error(f"API error {url}: {e}")
            raise

    async def get_usdt_futures_pairs(self) -> List[Dict]:
        """Get all active USDT perpetual futures pairs sorted by volume"""
        data = await self.get("/fapi/v1/ticker/24hr")
        pairs = []
        for item in data:
            symbol = item.get("symbol", "")
            if not symbol.endswith("USDT"):
                continue
            try:
                volume_usd = float(item.get("quoteVolume", 0))
                price = float(item.get("lastPrice", 0))
                price_change = float(item.get("priceChangePercent", 0))
                if volume_usd >= MIN_VOLUME_USD and price > 0:
                    pairs.append({
                        "symbol": symbol,
                        "volume_usd": volume_usd,
                        "price": price,
                        "price_change_pct": price_change,
                    })
            except (ValueError, TypeError):
                continue

        pairs.sort(key=lambda x: x["volume_usd"], reverse=True)
        return pairs[:TOP_PAIRS_LIMIT]

    async def get_klines(self, symbol: str, interval: str, limit: int = 100) -> List[Dict]:
        """Fetch futures OHLCV candlestick data"""
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        raw = await self.get("/fapi/v1/klines", params)
        candles = []
        for k in raw:
            candles.append({
                "open_time": k[0],
                "open":  float(k[1]),
                "high":  float(k[2]),
                "low":   float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "close_time": k[6],
            })
        return candles

    async def get_klines_both_tf(self, symbol: str, htf: str, ltf: str, limit: int = 100):
        """Fetch higher and lower timeframe candles concurrently"""
        htf_task = self.get_klines(symbol, htf, limit)
        ltf_task = self.get_klines(symbol, ltf, limit)
        results = await asyncio.gather(htf_task, ltf_task, return_exceptions=True)
        if isinstance(results[0], Exception):
            raise results[0]
        if isinstance(results[1], Exception):
            raise results[1]
        return results[0], results[1]

    async def get_open_interest(self, symbol: str) -> dict:
        """Get futures open interest"""
        return await self.get("/fapi/v1/openInterest", {"symbol": symbol})

"""
Binance Public API Client — No API Key Required
Uses Futures public endpoints for real-time data
"""

import aiohttp
import asyncio
import logging
from typing import List, Dict, Optional
from config import BINANCE_BASE_URL, BINANCE_SPOT_URL, MIN_VOLUME_USD, TOP_PAIRS_LIMIT

logger = logging.getLogger(__name__)


class BinanceClient:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def get(self, base_url: str, path: str, params: dict = None) -> dict:
        session = await self._get_session()
        url = f"{base_url}{path}"
        try:
            async with session.get(url, params=params) as resp:
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as e:
            logger.error(f"API error {url}: {e}")
            raise

    async def get_usdt_futures_pairs(self) -> List[Dict]:
        """Get all USDT perpetual futures pairs with volume filter"""
        data = await self.get(BINANCE_BASE_URL, "/fapi/v1/ticker/24hr")
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

        # Sort by volume descending, take top N
        pairs.sort(key=lambda x: x["volume_usd"], reverse=True)
        return pairs[:TOP_PAIRS_LIMIT]

    async def get_klines(self, symbol: str, interval: str, limit: int = 100) -> List[Dict]:
        """
        Fetch candlestick data from Binance Futures public API
        Returns list of OHLCV dicts
        """
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
        raw = await self.get(BINANCE_BASE_URL, "/fapi/v1/klines", params)

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

    async def get_orderbook_depth(self, symbol: str, limit: int = 20) -> dict:
        """Get order book snapshot"""
        params = {"symbol": symbol, "limit": limit}
        return await self.get(BINANCE_BASE_URL, "/fapi/v1/depth", params)

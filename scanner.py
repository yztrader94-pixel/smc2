"""
Market Scanner
Scans all top USDT pairs and runs strategy analysis concurrently
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional
from binance_client import BinanceClient
from strategy import generate_signal
from config import (
    HIGHER_TF, LOWER_TF, CANDLES_TO_FETCH,
    MIN_PROBABILITY_SCORE, TOP_PAIRS_LIMIT
)

logger = logging.getLogger(__name__)

MAX_CONCURRENT = 10  # Limit concurrent API calls


class MarketScanner:
    def __init__(self):
        self.client = BinanceClient()

    async def get_top_usdt_pairs(self) -> List[Dict]:
        return await self.client.get_usdt_futures_pairs()

    async def analyze_pair(self, symbol: str) -> Optional[Dict]:
        try:
            htf_candles, ltf_candles = await self.client.get_klines_both_tf(
                symbol, HIGHER_TF, LOWER_TF, CANDLES_TO_FETCH
            )
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            signal = generate_signal(symbol, htf_candles, ltf_candles, now)
            return signal
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug(f"Error analyzing {symbol}: {e}")
            return None

    async def scan_all_pairs(self) -> List[Dict]:
        """Scan all top USDT pairs and return filtered signals"""
        logger.info("Starting market scan...")

        pairs = await self.get_top_usdt_pairs()
        symbols = [p["symbol"] for p in pairs]

        logger.info(f"Scanning {len(symbols)} pairs on {HIGHER_TF}/{LOWER_TF}")

        signals = []
        semaphore = asyncio.Semaphore(MAX_CONCURRENT)

        async def analyze_with_semaphore(sym: str):
            async with semaphore:
                result = await self.analyze_pair(sym)
                if result and result["probability"] >= MIN_PROBABILITY_SCORE:
                    signals.append(result)

        tasks = [analyze_with_semaphore(sym) for sym in symbols]
        await asyncio.gather(*tasks, return_exceptions=True)

        # Sort by probability descending
        signals.sort(key=lambda x: x["probability"], reverse=True)

        logger.info(f"Scan complete: {len(signals)} signals found")
        return signals

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.close()

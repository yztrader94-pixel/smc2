"""
═══════════════════════════════════════════════════════
  STRATEGY BACKTESTER — Real Binance Historical Data
  Tests the exact same strategy logic used in live bot
═══════════════════════════════════════════════════════

Usage:
  python backtest.py                        # BTC, 90 days
  python backtest.py --pair ETHUSDT         # specific pair
  python backtest.py --days 180             # longer period
  python backtest.py --pairs BTCUSDT ETHUSDT SOLUSDT
  python backtest.py --all --days 60        # top 20 pairs
"""

import asyncio
import argparse
import sys
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
import aiohttp

# ── Import strategy components ──────────────────────
from strategy import (
    to_candles, get_htf_bias, detect_market_structure,
    detect_liquidity_sweep, detect_order_blocks, detect_fvg,
    calculate_rsi, detect_volume_spike, detect_rejection_candle,
    _calculate_atr, _price_decimals
)
from config import (
    RSI_OVERSOLD, RSI_OVERBOUGHT, MIN_RR_RATIO,
    HIGHER_TF, LOWER_TF
)

FAPI_URLS = [
    "https://fapi.binance.com",
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
]

# ── How many LTF candles to use as context before each signal scan
LOOKBACK_CANDLES = 100
# ── After signal, how many forward candles to simulate trade outcome
MAX_FORWARD_CANDLES = 200
# ── Fees (maker+taker round trip, realistic for futures)
FEE_PCT = 0.05 / 100


# ═══════════════════════════════════════════════════════
# DATA FETCHER
# ═══════════════════════════════════════════════════════
class HistoricalFetcher:
    def __init__(self):
        self._base = None
        self._session = None

    async def _get_session(self):
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    async def _find_base(self):
        if self._base:
            return self._base
        session = await self._get_session()
        for url in FAPI_URLS:
            try:
                async with session.get(f"{url}/fapi/v1/ping", timeout=aiohttp.ClientTimeout(total=6)) as r:
                    if r.status == 200:
                        self._base = url
                        return url
            except:
                continue
        raise ConnectionError("All Binance endpoints unreachable (geo-block?)")

    async def fetch_klines(self, symbol: str, interval: str,
                           start_ms: int, end_ms: int) -> List[Dict]:
        """Fetch all candles in [start_ms, end_ms] handling pagination"""
        base = await self._find_base()
        session = await self._get_session()
        all_candles = []
        current_start = start_ms

        while current_start < end_ms:
            params = {
                "symbol":    symbol,
                "interval":  interval,
                "startTime": current_start,
                "endTime":   end_ms,
                "limit":     1500,
            }
            async with session.get(f"{base}/fapi/v1/klines", params=params) as r:
                r.raise_for_status()
                raw = await r.json()

            if not raw:
                break

            for k in raw:
                all_candles.append({
                    "open_time": k[0],
                    "open":  float(k[1]),
                    "high":  float(k[2]),
                    "low":   float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                })

            if len(raw) < 1500:
                break
            current_start = raw[-1][0] + 1
            await asyncio.sleep(0.1)  # be nice to API

        return all_candles

    async def fetch_top_pairs(self, n: int = 20) -> List[str]:
        base = await self._find_base()
        session = await self._get_session()
        async with session.get(f"{base}/fapi/v1/ticker/24hr") as r:
            data = await r.json()
        pairs = [
            (d["symbol"], float(d.get("quoteVolume", 0)))
            for d in data
            if d["symbol"].endswith("USDT")
        ]
        pairs.sort(key=lambda x: x[1], reverse=True)
        return [p[0] for p in pairs[:n]]

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


# ═══════════════════════════════════════════════════════
# TRADE SIMULATOR
# ═══════════════════════════════════════════════════════
def simulate_trade(
    signal_dir: str,
    entry: float,
    sl: float,
    tp1: float,
    tp2: float,
    forward_candles: List[Dict],
    fee_pct: float = FEE_PCT,
) -> Dict:
    """
    Walk forward candle by candle and determine outcome.
    Returns result dict with outcome, pnl, candles_held.
    """
    tp1_hit = False
    result = {
        "outcome":       None,   # TP1 / TP2 / SL / TIMEOUT
        "tp1_hit":       False,
        "tp2_hit":       False,
        "sl_hit":        False,
        "pnl_pct":       0.0,
        "candles_held":  0,
        "exit_price":    entry,
    }

    for i, c in enumerate(forward_candles):
        high = c["high"]
        low  = c["low"]

        if signal_dir == "LONG":
            # Check SL first (worst case within candle)
            if not tp1_hit and low <= sl:
                result.update({
                    "outcome": "SL",
                    "sl_hit": True,
                    "exit_price": sl,
                    "candles_held": i + 1,
                    "pnl_pct": round(((sl - entry) / entry * 100) - fee_pct * 100, 3),
                })
                return result

            if not tp1_hit and high >= tp1:
                tp1_hit = True
                result["tp1_hit"] = True

            if tp1_hit and high >= tp2:
                result.update({
                    "outcome": "TP2",
                    "tp2_hit": True,
                    "exit_price": tp2,
                    "candles_held": i + 1,
                    "pnl_pct": round(((tp2 - entry) / entry * 100) - fee_pct * 100, 3),
                })
                return result

        else:  # SHORT
            if not tp1_hit and high >= sl:
                result.update({
                    "outcome": "SL",
                    "sl_hit": True,
                    "exit_price": sl,
                    "candles_held": i + 1,
                    "pnl_pct": round(((entry - sl) / entry * 100) - fee_pct * 100, 3),
                })
                return result

            if not tp1_hit and low <= tp1:
                tp1_hit = True
                result["tp1_hit"] = True

            if tp1_hit and low <= tp2:
                result.update({
                    "outcome": "TP2",
                    "tp2_hit": True,
                    "exit_price": tp2,
                    "candles_held": i + 1,
                    "pnl_pct": round(((entry - tp2) / entry * 100) - fee_pct * 100, 3),
                })
                return result

    # Timeout — close at last candle close
    last_close = forward_candles[-1]["close"] if forward_candles else entry
    if signal_dir == "LONG":
        pnl = ((last_close - entry) / entry * 100) - fee_pct * 100
    else:
        pnl = ((entry - last_close) / entry * 100) - fee_pct * 100

    outcome = "TP1_PARTIAL" if tp1_hit else "TIMEOUT"
    result.update({
        "outcome":      outcome,
        "exit_price":   last_close,
        "candles_held": len(forward_candles),
        "pnl_pct":      round(pnl, 3),
    })
    return result


# ═══════════════════════════════════════════════════════
# SIGNAL SCANNER (same logic as live bot, on history)
# ═══════════════════════════════════════════════════════
def scan_for_signal(
    htf_raw: List[Dict],
    ltf_raw: List[Dict],
    symbol: str,
    timestamp: str,
) -> Optional[Dict]:
    """Run the exact same 5-gate strategy on a historical window"""
    htf = to_candles(htf_raw)
    ltf = to_candles(ltf_raw)

    if len(ltf) < 30 or len(htf) < 10:
        return None

    current_price = ltf[-1].close

    htf_bias   = get_htf_bias(htf)
    structure  = detect_market_structure(ltf)
    liq_sweep  = detect_liquidity_sweep(ltf)
    ob         = detect_order_blocks(ltf)
    fvg        = detect_fvg(ltf)
    rsi_vals   = calculate_rsi(ltf)
    current_rsi = rsi_vals[-1] if rsi_vals else 50.0
    vol        = detect_volume_spike(ltf)
    rejection  = detect_rejection_candle(ltf)

    ob_bullish  = ob.get("ob_type")  == "bullish" and ob.get("price_in_ob")
    ob_bearish  = ob.get("ob_type")  == "bearish" and ob.get("price_in_ob")
    fvg_bullish = fvg.get("fvg_type") == "bullish" and fvg.get("price_in_fvg")
    fvg_bearish = fvg.get("fvg_type") == "bearish" and fvg.get("price_in_fvg")

    # ── LONG gates
    long_g1 = htf_bias == "bullish"
    long_g2 = structure["trend"] in ("bullish", "bullish_reversal") and \
              (structure["bos"] or structure["choch"])
    long_g3 = ob_bullish or fvg_bullish
    long_g4 = liq_sweep.get("sweep_type") == "bullish"
    long_conf = sum([
        current_rsi < RSI_OVERSOLD,
        vol.get("spike", False),
        rejection.get("pattern") in ("bullish_engulfing", "hammer"),
    ])
    long_g5 = long_conf >= 2

    # ── SHORT gates
    short_g1 = htf_bias == "bearish"
    short_g2 = structure["trend"] in ("bearish", "bearish_reversal") and \
               (structure["bos"] or structure["choch"])
    short_g3 = ob_bearish or fvg_bearish
    short_g4 = liq_sweep.get("sweep_type") == "bearish"
    short_conf = sum([
        current_rsi > RSI_OVERBOUGHT,
        vol.get("spike", False),
        rejection.get("pattern") in ("bearish_engulfing", "shooting_star"),
    ])
    short_g5 = short_conf >= 2

    long_pass  = all([long_g1,  long_g2,  long_g3,  long_g4,  long_g5])
    short_pass = all([short_g1, short_g2, short_g3, short_g4, short_g5])

    if long_pass and short_pass:
        return None
    if not long_pass and not short_pass:
        return None

    signal_dir = "LONG" if long_pass else "SHORT"
    conf_score = long_conf if long_pass else short_conf
    probability = min(65 + conf_score * 5 + (5 if structure["bos"] else 0), 95)

    # Risk management
    atr = _calculate_atr(ltf, 14)
    dec = _price_decimals(current_price)

    if signal_dir == "LONG":
        entry = round(current_price, dec)
        sl = round(entry - atr * 1.5, dec)
        if structure["last_low"]:
            sl = min(sl, round(structure["last_low"] * 0.999, dec))
        risk = entry - sl
        tp1  = round(entry + risk * 2,   dec)
        tp2  = round(entry + risk * 3.5, dec)
    else:
        entry = round(current_price, dec)
        sl = round(entry + atr * 1.5, dec)
        if structure["last_high"]:
            sl = max(sl, round(structure["last_high"] * 1.001, dec))
        risk = sl - entry
        tp1  = round(entry - risk * 2,   dec)
        tp2  = round(entry - risk * 3.5, dec)

    rr = abs(tp2 - entry) / abs(sl - entry) if abs(sl - entry) > 0 else 0
    if rr < MIN_RR_RATIO:
        return None

    return {
        "pair":        symbol,
        "signal":      signal_dir,
        "entry":       entry,
        "sl":          sl,
        "tp1":         tp1,
        "tp2":         tp2,
        "rr":          round(rr, 2),
        "probability": probability,
        "timestamp":   timestamp,
    }


# ═══════════════════════════════════════════════════════
# BACKTEST ENGINE
# ═══════════════════════════════════════════════════════
async def backtest_pair(
    fetcher: HistoricalFetcher,
    symbol: str,
    days: int,
    step_candles: int = 3,  # scan every N LTF candles (not every single one — realistic)
) -> List[Dict]:
    """
    Fetch historical data, walk through it, fire signals,
    simulate each trade, collect results.
    """
    now_ms    = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms  = now_ms - days * 24 * 3600 * 1000

    print(f"  Fetching {symbol} {HIGHER_TF} candles...")
    htf_all = await fetcher.fetch_klines(symbol, HIGHER_TF, start_ms, now_ms)

    print(f"  Fetching {symbol} {LOWER_TF} candles...")
    ltf_all = await fetcher.fetch_klines(symbol, LOWER_TF, start_ms, now_ms)

    if len(ltf_all) < LOOKBACK_CANDLES + MAX_FORWARD_CANDLES:
        print(f"  ⚠️  Not enough candles for {symbol}, skipping")
        return []

    trades = []
    active_trade_until = -1  # index — skip overlapping signals

    total_steps = len(ltf_all) - LOOKBACK_CANDLES - MAX_FORWARD_CANDLES
    print(f"  Running {total_steps} scan steps...")

    for i in range(LOOKBACK_CANDLES, len(ltf_all) - MAX_FORWARD_CANDLES, step_candles):
        if i < active_trade_until:
            continue

        ltf_window = ltf_all[i - LOOKBACK_CANDLES: i]
        current_ts = datetime.fromtimestamp(
            ltf_all[i]["open_time"] / 1000, tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M")

        # Build HTF window aligned to this point in time
        current_time_ms = ltf_all[i]["open_time"]
        htf_window = [c for c in htf_all if c["open_time"] <= current_time_ms][-LOOKBACK_CANDLES:]

        if len(htf_window) < 20:
            continue

        sig = scan_for_signal(htf_window, ltf_window, symbol, current_ts)
        if not sig:
            continue

        # Simulate trade on forward candles
        forward = ltf_all[i: i + MAX_FORWARD_CANDLES]
        result  = simulate_trade(
            sig["signal"], sig["entry"], sig["sl"],
            sig["tp1"], sig["tp2"], forward
        )

        trade = {**sig, **result}
        trades.append(trade)

        # Skip forward to avoid overlapping trades
        active_trade_until = i + result["candles_held"] + 1

    return trades


# ═══════════════════════════════════════════════════════
# REPORT GENERATOR
# ═══════════════════════════════════════════════════════
def print_report(all_trades: List[Dict], days: int):
    sep = "═" * 56

    if not all_trades:
        print(f"\n{sep}")
        print("  No signals found in this period.")
        print(f"{sep}\n")
        return

    total      = len(all_trades)
    wins       = [t for t in all_trades if t["outcome"] in ("TP2", "TP1_PARTIAL") and t["pnl_pct"] > 0]
    losses     = [t for t in all_trades if t["outcome"] == "SL"]
    timeouts   = [t for t in all_trades if t["outcome"] == "TIMEOUT"]
    tp2_hits   = [t for t in all_trades if t["outcome"] == "TP2"]
    tp1_hits   = [t for t in all_trades if t["tp1_hit"]]

    win_rate   = len(wins) / total * 100
    tp2_rate   = len(tp2_hits) / total * 100
    tp1_rate   = len(tp1_hits) / total * 100

    total_pnl  = sum(t["pnl_pct"] for t in all_trades)
    avg_win    = sum(t["pnl_pct"] for t in wins)   / len(wins)   if wins   else 0
    avg_loss   = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0
    avg_hold   = sum(t["candles_held"] for t in all_trades) / total

    # Max drawdown (consecutive losses)
    peak = 0
    equity = 0
    max_dd = 0
    for t in all_trades:
        equity += t["pnl_pct"]
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    # Profit factor
    gross_profit = sum(t["pnl_pct"] for t in all_trades if t["pnl_pct"] > 0)
    gross_loss   = abs(sum(t["pnl_pct"] for t in all_trades if t["pnl_pct"] < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Pairs breakdown
    pairs = {}
    for t in all_trades:
        p = t["pair"]
        if p not in pairs:
            pairs[p] = {"total": 0, "wins": 0, "pnl": 0.0}
        pairs[p]["total"] += 1
        pairs[p]["pnl"]   += t["pnl_pct"]
        if t["pnl_pct"] > 0:
            pairs[p]["wins"] += 1

    print(f"\n{sep}")
    print(f"  BACKTEST RESULTS  —  {days} Days")
    print(f"{sep}")
    print(f"  Total Signals     {total}")
    print(f"  Signals/Day       {total/days:.1f}")
    print(f"  Period            {days} days")
    print(f"{sep}")
    print(f"  Win Rate          {win_rate:.1f}%")
    print(f"  TP2 Hit Rate      {tp2_rate:.1f}%")
    print(f"  TP1 Hit Rate      {tp1_rate:.1f}%")
    print(f"  Losses (SL)       {len(losses)}  ({len(losses)/total*100:.1f}%)")
    print(f"  Timeouts          {len(timeouts)}")
    print(f"{sep}")
    print(f"  Total PnL         {total_pnl:+.2f}%")
    print(f"  Avg Win           {avg_win:+.2f}%")
    print(f"  Avg Loss          {avg_loss:+.2f}%")
    print(f"  Profit Factor     {pf:.2f}")
    print(f"  Max Drawdown      -{max_dd:.2f}%")
    print(f"  Avg Hold          {avg_hold:.0f} candles")
    print(f"{sep}")

    # Verdict
    print(f"\n  VERDICT:")
    if win_rate >= 55 and pf >= 1.5 and total_pnl > 0:
        verdict = "✅  STRATEGY HAS EDGE — consider paper trading"
    elif win_rate >= 45 and pf >= 1.2:
        verdict = "⚠️   MARGINAL EDGE — needs more data / optimization"
    else:
        verdict = "❌  NO CLEAR EDGE — do not trade with real money"
    print(f"  {verdict}")

    print(f"\n  PER PAIR BREAKDOWN:")
    print(f"  {'Pair':<14} {'Signals':>7} {'WR%':>6} {'PnL%':>8}")
    print(f"  {'-'*38}")
    for pair, data in sorted(pairs.items(), key=lambda x: x[1]["pnl"], reverse=True):
        wr = data["wins"] / data["total"] * 100 if data["total"] > 0 else 0
        print(f"  {pair:<14} {data['total']:>7} {wr:>5.1f}% {data['pnl']:>+7.2f}%")

    print(f"\n  TRADE LOG (last 20):")
    print(f"  {'#':<4} {'Pair':<12} {'Dir':<6} {'Outcome':<12} {'PnL%':>7} {'Date'}")
    print(f"  {'-'*60}")
    for idx, t in enumerate(all_trades[-20:], 1):
        outcome_icon = {
            "TP2": "🏆", "TP1_PARTIAL": "🎯",
            "SL": "🛑", "TIMEOUT": "⏱"
        }.get(t["outcome"], "?")
        print(
            f"  {idx:<4} {t['pair']:<12} {t['signal']:<6} "
            f"{outcome_icon} {t['outcome']:<10} {t['pnl_pct']:>+7.2f}%  {t['timestamp']}"
        )

    print(f"\n{sep}\n")


# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════
async def main():
    parser = argparse.ArgumentParser(description="SMC Strategy Backtester")
    parser.add_argument("--pair",  type=str, default="BTCUSDT",   help="Single pair to backtest")
    parser.add_argument("--pairs", type=str, nargs="+",           help="Multiple pairs")
    parser.add_argument("--days",  type=int, default=90,          help="Lookback days (default 90)")
    parser.add_argument("--all",   action="store_true",           help="Backtest top 20 USDT pairs")
    parser.add_argument("--step",  type=int, default=3,           help="Scan every N candles (default 3)")
    args = parser.parse_args()

    fetcher = HistoricalFetcher()

    try:
        # Determine pairs to test
        if args.all:
            print("Fetching top 20 USDT pairs by volume...")
            pairs = await fetcher.fetch_top_pairs(20)
        elif args.pairs:
            pairs = [p.upper() for p in args.pairs]
        else:
            pairs = [args.pair.upper()]

        print(f"\n{'═'*56}")
        print(f"  SMC STRATEGY BACKTESTER")
        print(f"  Pairs: {', '.join(pairs)}")
        print(f"  Period: {args.days} days")
        print(f"  Timeframes: {HIGHER_TF.upper()} trend / {LOWER_TF.upper()} entry")
        print(f"  Fees: {FEE_PCT*100:.3f}% per side")
        print(f"{'═'*56}\n")

        all_trades = []

        for pair in pairs:
            print(f"▶  Backtesting {pair}...")
            try:
                trades = await backtest_pair(fetcher, pair, args.days, args.step)
                all_trades.extend(trades)
                print(f"   → {len(trades)} trades found\n")
            except Exception as e:
                print(f"   ❌ Error on {pair}: {e}\n")

        print_report(all_trades, args.days)

    finally:
        await fetcher.close()


if __name__ == "__main__":
    asyncio.run(main())

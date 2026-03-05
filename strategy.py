"""
Smart Money Concepts Strategy Engine
Implements: BOS, CHOCH, Liquidity Sweeps, Order Blocks, FVG, RSI, Volume
"""

import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from config import (
    RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
    VOLUME_SPIKE_MULTIPLIER, MIN_RR_RATIO
)

logger = logging.getLogger(__name__)


@dataclass
class Candle:
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def body_size(self):
        return abs(self.close - self.open)

    @property
    def upper_wick(self):
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self):
        return min(self.open, self.close) - self.low

    @property
    def is_bullish(self):
        return self.close > self.open

    @property
    def is_bearish(self):
        return self.close < self.open

    @property
    def range(self):
        return self.high - self.low


def to_candles(raw: List[Dict]) -> List[Candle]:
    return [Candle(r['open'], r['high'], r['low'], r['close'], r['volume']) for r in raw]


# ─────────────────────────────────────────────
# RSI Calculation
# ─────────────────────────────────────────────
def calculate_rsi(candles: List[Candle], period: int = RSI_PERIOD) -> List[float]:
    if len(candles) < period + 1:
        return [50.0] * len(candles)

    closes = [c.close for c in candles]
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]

    gains = [max(d, 0) for d in deltas]
    losses = [abs(min(d, 0)) for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    rsi_values = [50.0] * (period + 1)

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100 - (100 / (1 + rs)))

    return rsi_values


# ─────────────────────────────────────────────
# Market Structure
# ─────────────────────────────────────────────
def detect_swing_points(candles: List[Candle], lookback: int = 5) -> Tuple[List[int], List[int]]:
    """Returns indices of swing highs and swing lows"""
    highs, lows = [], []
    n = len(candles)
    for i in range(lookback, n - lookback):
        is_high = all(candles[i].high >= candles[j].high for j in range(i - lookback, i + lookback + 1) if j != i)
        is_low = all(candles[i].low <= candles[j].low for j in range(i - lookback, i + lookback + 1) if j != i)
        if is_high:
            highs.append(i)
        if is_low:
            lows.append(i)
    return highs, lows


def detect_market_structure(candles: List[Candle]) -> Dict:
    """
    Detect:
    - Higher Highs / Higher Lows (uptrend)
    - Lower Highs / Lower Lows (downtrend)
    - BOS (Break of Structure)
    - CHOCH (Change of Character)
    """
    result = {
        "trend": "neutral",
        "bos": False,
        "choch": False,
        "bos_direction": None,
        "last_high": None,
        "last_low": None,
        "structure_description": "Neutral/ranging market",
    }

    swing_highs, swing_lows = detect_swing_points(candles, lookback=3)

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return result

    recent_highs = [candles[i].high for i in swing_highs[-4:]]
    recent_lows = [candles[i].low for i in swing_lows[-4:]]

    result["last_high"] = recent_highs[-1]
    result["last_low"] = recent_lows[-1]

    hh = all(recent_highs[i] < recent_highs[i+1] for i in range(len(recent_highs)-1))
    hl = all(recent_lows[i] < recent_lows[i+1] for i in range(len(recent_lows)-1))
    lh = all(recent_highs[i] > recent_highs[i+1] for i in range(len(recent_highs)-1))
    ll = all(recent_lows[i] > recent_lows[i+1] for i in range(len(recent_lows)-1))

    last_close = candles[-1].close
    prev_high = recent_highs[-2] if len(recent_highs) >= 2 else None
    prev_low = recent_lows[-2] if len(recent_lows) >= 2 else None

    if hh and hl:
        result["trend"] = "bullish"
        result["structure_description"] = "HH+HL uptrend structure confirmed"
        # BOS = price breaks above previous swing high in uptrend
        if prev_high and last_close > prev_high:
            result["bos"] = True
            result["bos_direction"] = "bullish"
            result["structure_description"] = "BOS Bullish: price broke above prior HH"

    elif lh and ll:
        result["trend"] = "bearish"
        result["structure_description"] = "LH+LL downtrend structure confirmed"
        if prev_low and last_close < prev_low:
            result["bos"] = True
            result["bos_direction"] = "bearish"
            result["structure_description"] = "BOS Bearish: price broke below prior LL"

    else:
        # CHOCH: trend reversal signal
        if hh and ll:
            result["choch"] = True
            result["trend"] = "bearish_reversal"
            result["structure_description"] = "CHOCH: Higher Highs but Lower Lows — bearish reversal forming"
        elif lh and hl:
            result["choch"] = True
            result["trend"] = "bullish_reversal"
            result["structure_description"] = "CHOCH: Lower Highs but Higher Lows — bullish reversal forming"
        else:
            result["structure_description"] = "Ranging / no clear structure"

    return result


# ─────────────────────────────────────────────
# Liquidity Sweeps
# ─────────────────────────────────────────────
def detect_liquidity_sweep(candles: List[Candle], lookback: int = 20) -> Dict:
    """
    Detect stop hunts:
    - Price spikes above recent high then closes back below (bearish sweep)
    - Price spikes below recent low then closes back above (bullish sweep)
    """
    result = {
        "sweep_detected": False,
        "sweep_type": None,
        "sweep_level": None,
        "description": None,
    }

    if len(candles) < lookback + 3:
        return result

    recent = candles[-(lookback + 3):-3]
    last3 = candles[-3:]

    recent_high = max(c.high for c in recent)
    recent_low = min(c.low for c in recent)

    for c in last3:
        # Bearish sweep: wick above previous high, body closes below
        if c.high > recent_high and c.close < recent_high:
            wick_ratio = c.upper_wick / c.range if c.range > 0 else 0
            if wick_ratio > 0.3:
                result["sweep_detected"] = True
                result["sweep_type"] = "bearish"
                result["sweep_level"] = round(recent_high, 6)
                result["description"] = f"Bearish liquidity sweep above ${recent_high:.4f} — stop hunt above highs"
                return result

        # Bullish sweep: wick below previous low, body closes above
        if c.low < recent_low and c.close > recent_low:
            wick_ratio = c.lower_wick / c.range if c.range > 0 else 0
            if wick_ratio > 0.3:
                result["sweep_detected"] = True
                result["sweep_type"] = "bullish"
                result["sweep_level"] = round(recent_low, 6)
                result["description"] = f"Bullish liquidity sweep below ${recent_low:.4f} — stop hunt below lows"
                return result

    return result


# ─────────────────────────────────────────────
# Order Blocks
# ─────────────────────────────────────────────
def detect_order_blocks(candles: List[Candle], lookback: int = 30) -> Dict:
    """
    Bullish OB: Last bearish candle before a strong bullish impulse
    Bearish OB: Last bullish candle before a strong bearish impulse
    """
    result = {
        "ob_detected": False,
        "ob_type": None,
        "ob_high": None,
        "ob_low": None,
        "description": None,
        "price_in_ob": False,
    }

    if len(candles) < 10:
        return result

    window = candles[-lookback:]
    current_price = candles[-1].close

    # Look for OBs by finding strong impulse moves
    for i in range(3, len(window) - 2):
        candle = window[i]
        next_candles = window[i+1:i+4]

        if not next_candles:
            continue

        move = sum(abs(c.close - c.open) for c in next_candles)
        avg_body = sum(abs(c.close - c.open) for c in window) / len(window)

        # Bearish OB: bullish candle before big down move
        if candle.is_bullish and all(c.is_bearish for c in next_candles[:2]):
            if move > avg_body * 2:
                ob_h = candle.high
                ob_l = candle.low
                # Check if price is retesting the OB
                if ob_l <= current_price <= ob_h:
                    result.update({
                        "ob_detected": True,
                        "ob_type": "bearish",
                        "ob_high": round(ob_h, 6),
                        "ob_low": round(ob_l, 6),
                        "description": f"Bearish OB zone ${ob_l:.4f}–${ob_h:.4f} — price retesting supply",
                        "price_in_ob": True,
                    })
                    return result

        # Bullish OB: bearish candle before big up move
        if candle.is_bearish and all(c.is_bullish for c in next_candles[:2]):
            if move > avg_body * 2:
                ob_h = candle.high
                ob_l = candle.low
                if ob_l <= current_price <= ob_h:
                    result.update({
                        "ob_detected": True,
                        "ob_type": "bullish",
                        "ob_high": round(ob_h, 6),
                        "ob_low": round(ob_l, 6),
                        "description": f"Bullish OB zone ${ob_l:.4f}–${ob_h:.4f} — price retesting demand",
                        "price_in_ob": True,
                    })
                    return result

    return result


# ─────────────────────────────────────────────
# Fair Value Gaps (FVG)
# ─────────────────────────────────────────────
def detect_fvg(candles: List[Candle], lookback: int = 20) -> Dict:
    """
    FVG: 3-candle pattern where candle[0].high < candle[2].low (bullish)
    or candle[0].low > candle[2].high (bearish)
    """
    result = {
        "fvg_detected": False,
        "fvg_type": None,
        "fvg_high": None,
        "fvg_low": None,
        "description": None,
        "price_in_fvg": False,
    }

    if len(candles) < 10:
        return result

    window = candles[-lookback:]
    current_price = candles[-1].close

    for i in range(len(window) - 2):
        c0, c1, c2 = window[i], window[i+1], window[i+2]

        # Bullish FVG
        if c0.high < c2.low:
            gap_high = c2.low
            gap_low = c0.high
            gap_size = gap_high - gap_low
            if gap_size > 0 and gap_low <= current_price <= gap_high:
                result.update({
                    "fvg_detected": True,
                    "fvg_type": "bullish",
                    "fvg_high": round(gap_high, 6),
                    "fvg_low": round(gap_low, 6),
                    "description": f"Bullish FVG ${gap_low:.4f}–${gap_high:.4f} — price filling imbalance",
                    "price_in_fvg": True,
                })

        # Bearish FVG
        if c0.low > c2.high:
            gap_high = c0.low
            gap_low = c2.high
            gap_size = gap_high - gap_low
            if gap_size > 0 and gap_low <= current_price <= gap_high:
                result.update({
                    "fvg_detected": True,
                    "fvg_type": "bearish",
                    "fvg_high": round(gap_high, 6),
                    "fvg_low": round(gap_low, 6),
                    "description": f"Bearish FVG ${gap_low:.4f}–${gap_high:.4f} — price filling imbalance",
                    "price_in_fvg": True,
                })

    return result


# ─────────────────────────────────────────────
# Volume Analysis
# ─────────────────────────────────────────────
def detect_volume_spike(candles: List[Candle], lookback: int = 20) -> Dict:
    if len(candles) < lookback + 1:
        return {"spike": False, "ratio": 1.0, "description": "Insufficient data"}

    avg_vol = sum(c.volume for c in candles[-lookback-1:-1]) / lookback
    last_vol = candles[-1].volume
    ratio = last_vol / avg_vol if avg_vol > 0 else 1.0

    return {
        "spike": ratio >= VOLUME_SPIKE_MULTIPLIER,
        "ratio": round(ratio, 2),
        "description": f"Volume {ratio:.1f}x average — {'spike confirmed ✅' if ratio >= VOLUME_SPIKE_MULTIPLIER else 'normal'}",
    }


# ─────────────────────────────────────────────
# Rejection / Engulfing Candles
# ─────────────────────────────────────────────
def detect_rejection_candle(candles: List[Candle]) -> Dict:
    result = {"detected": False, "pattern": None, "description": None}
    if len(candles) < 2:
        return result

    last = candles[-1]
    prev = candles[-2]

    # Bullish engulfing
    if prev.is_bearish and last.is_bullish:
        if last.close > prev.open and last.open < prev.close:
            result.update({
                "detected": True,
                "pattern": "bullish_engulfing",
                "description": "Bullish engulfing candle — strong rejection of lows"
            })
            return result

    # Bearish engulfing
    if prev.is_bullish and last.is_bearish:
        if last.close < prev.open and last.open > prev.close:
            result.update({
                "detected": True,
                "pattern": "bearish_engulfing",
                "description": "Bearish engulfing candle — strong rejection of highs"
            })
            return result

    # Hammer (bullish rejection)
    if last.range > 0:
        lower_ratio = last.lower_wick / last.range
        if lower_ratio > 0.6 and last.close > last.open:
            result.update({
                "detected": True,
                "pattern": "hammer",
                "description": "Hammer candle — long lower wick, bullish rejection"
            })
            return result

        # Shooting star (bearish rejection)
        upper_ratio = last.upper_wick / last.range
        if upper_ratio > 0.6 and last.close < last.open:
            result.update({
                "detected": True,
                "pattern": "shooting_star",
                "description": "Shooting star — long upper wick, bearish rejection"
            })
            return result

    return result


# ─────────────────────────────────────────────
# Higher Timeframe Trend Filter
# ─────────────────────────────────────────────
def get_htf_bias(htf_candles: List[Candle]) -> str:
    """Simple HTF bias using EMA50 vs EMA200"""
    if len(htf_candles) < 50:
        return "neutral"

    closes = [c.close for c in htf_candles]

    def ema(data, period):
        k = 2 / (period + 1)
        e = data[0]
        for p in data[1:]:
            e = p * k + e * (1 - k)
        return e

    ema50 = ema(closes[-50:], 50)
    ema200 = ema(closes, min(200, len(closes)))

    last_close = closes[-1]

    if last_close > ema50 > ema200:
        return "bullish"
    elif last_close < ema50 < ema200:
        return "bearish"
    else:
        return "neutral"


# ─────────────────────────────────────────────
# Signal Generator
# ─────────────────────────────────────────────
def generate_signal(
    symbol: str,
    htf_candles: List[Dict],
    ltf_candles: List[Dict],
    timestamp: str,
) -> Optional[Dict]:
    """
    Core signal generation combining all SMC components.
    Returns signal dict or None if no valid setup.
    """
    htf = to_candles(htf_candles)
    ltf = to_candles(ltf_candles)

    if len(ltf) < 30:
        return None

    current_price = ltf[-1].close

    # 1. HTF Bias
    htf_bias = get_htf_bias(htf)

    # 2. Market Structure (on LTF)
    structure = detect_market_structure(ltf)

    # 3. Liquidity Sweep
    liq_sweep = detect_liquidity_sweep(ltf)

    # 4. Order Block
    ob = detect_order_blocks(ltf)

    # 5. FVG
    fvg = detect_fvg(ltf)

    # 6. RSI
    rsi_vals = calculate_rsi(ltf)
    current_rsi = rsi_vals[-1] if rsi_vals else 50.0

    # 7. Volume
    vol = detect_volume_spike(ltf)

    # 8. Rejection candle
    rejection = detect_rejection_candle(ltf)

    # ─── Signal Logic ───────────────────────────
    signal_dir = None
    probability = 0
    confirmations = []

    # --- LONG SETUP ---
    long_conditions = 0
    if htf_bias == "bullish":
        long_conditions += 1

    ltf_trend_bullish = structure["trend"] in ("bullish", "bullish_reversal")
    if ltf_trend_bullish:
        long_conditions += 1

    if liq_sweep.get("sweep_type") == "bullish":
        long_conditions += 1

    ob_bullish = ob.get("ob_type") == "bullish" and ob.get("price_in_ob")
    fvg_bullish = fvg.get("fvg_type") == "bullish" and fvg.get("price_in_fvg")
    if ob_bullish or fvg_bullish:
        long_conditions += 1

    rsi_long_ok = current_rsi < RSI_OVERBOUGHT
    if current_rsi < RSI_OVERSOLD:
        long_conditions += 1
        rsi_long_ok = True

    if vol.get("spike"):
        long_conditions += 1

    rejection_bullish = rejection.get("pattern") in ("bullish_engulfing", "hammer")
    if rejection_bullish:
        long_conditions += 1

    # --- SHORT SETUP ---
    short_conditions = 0
    if htf_bias == "bearish":
        short_conditions += 1

    ltf_trend_bearish = structure["trend"] in ("bearish", "bearish_reversal")
    if ltf_trend_bearish:
        short_conditions += 1

    if liq_sweep.get("sweep_type") == "bearish":
        short_conditions += 1

    ob_bearish = ob.get("ob_type") == "bearish" and ob.get("price_in_ob")
    fvg_bearish = fvg.get("fvg_type") == "bearish" and fvg.get("price_in_fvg")
    if ob_bearish or fvg_bearish:
        short_conditions += 1

    rsi_short_ok = current_rsi > RSI_OVERSOLD
    if current_rsi > RSI_OVERBOUGHT:
        short_conditions += 1
        rsi_short_ok = True

    if vol.get("spike"):
        short_conditions += 1

    rejection_bearish = rejection.get("pattern") in ("bearish_engulfing", "shooting_star")
    if rejection_bearish:
        short_conditions += 1

    # Choose direction — need at least 4 conditions
    if long_conditions >= 4 and long_conditions > short_conditions:
        signal_dir = "LONG"
        probability = min(50 + long_conditions * 7, 95)
    elif short_conditions >= 4 and short_conditions > long_conditions:
        signal_dir = "SHORT"
        probability = min(50 + short_conditions * 7, 95)
    else:
        return None  # Not enough confluence

    # ─── Build Confirmations List ───────────────
    confirmations.append(f"HTF 4H bias: {htf_bias.upper()}")
    confirmations.append(structure["structure_description"])

    if liq_sweep["sweep_detected"]:
        confirmations.append(liq_sweep["description"])
    else:
        confirmations.append("No major liquidity sweep (price action clean)")

    if ob["ob_detected"]:
        confirmations.append(ob["description"])
    elif fvg["fvg_detected"]:
        confirmations.append(fvg["description"])
    else:
        confirmations.append("No OB/FVG retest — momentum-based entry")

    confirmations.append(f"RSI({RSI_PERIOD}): {current_rsi:.1f} — {'oversold' if current_rsi < RSI_OVERSOLD else 'overbought' if current_rsi > RSI_OVERBOUGHT else 'neutral'}")
    confirmations.append(vol["description"])

    if rejection["detected"]:
        confirmations.append(rejection["description"])

    # ─── Risk Management ────────────────────────
    atr = _calculate_atr(ltf, 14)

    if signal_dir == "LONG":
        entry = round(current_price, _price_decimals(current_price))
        sl = round(entry - atr * 1.5, _price_decimals(current_price))
        if structure["last_low"]:
            sl = min(sl, round(structure["last_low"] * 0.999, _price_decimals(current_price)))
        risk = entry - sl
        tp1 = round(entry + risk * 2, _price_decimals(current_price))
        tp2 = round(entry + risk * 3.5, _price_decimals(current_price))
    else:
        entry = round(current_price, _price_decimals(current_price))
        sl = round(entry + atr * 1.5, _price_decimals(current_price))
        if structure["last_high"]:
            sl = max(sl, round(structure["last_high"] * 1.001, _price_decimals(current_price)))
        risk = sl - entry
        tp1 = round(entry - risk * 2, _price_decimals(current_price))
        tp2 = round(entry - risk * 3.5, _price_decimals(current_price))

    rr = abs(tp2 - entry) / abs(sl - entry) if abs(sl - entry) > 0 else 0
    if rr < MIN_RR_RATIO:
        return None

    # Risk level
    atr_pct = (atr / current_price) * 100
    risk_level = "Low" if atr_pct < 2 else "Medium" if atr_pct < 4 else "High"

    return {
        "pair": symbol,
        "signal": signal_dir,
        "entry": entry,
        "stop_loss": sl,
        "tp1": tp1,
        "tp2": tp2,
        "rr_ratio": round(rr, 2),
        "probability": probability,
        "risk_level": risk_level,
        "confirmations": confirmations,
        "timestamp": timestamp,
    }


def _calculate_atr(candles: List[Candle], period: int = 14) -> float:
    if len(candles) < period + 1:
        return candles[-1].range if candles else 0

    trs = []
    for i in range(1, len(candles)):
        tr = max(
            candles[i].high - candles[i].low,
            abs(candles[i].high - candles[i-1].close),
            abs(candles[i].low - candles[i-1].close),
        )
        trs.append(tr)

    return sum(trs[-period:]) / period


def _price_decimals(price: float) -> int:
    if price >= 1000:
        return 2
    elif price >= 10:
        return 3
    elif price >= 1:
        return 4
    else:
        return 6

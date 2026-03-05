"""
Live Signal Tracker
Monitors active signals every 30 seconds and fires alerts
when price hits TP1, TP2, SL, or crosses entry (position opened)
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# How often to check prices (seconds)
TRACKER_INTERVAL = 30


@dataclass
class TrackedSignal:
    pair: str
    signal: str          # LONG or SHORT
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    rr_ratio: float
    probability: int
    risk_level: str
    chat_id: int
    timestamp: str

    # State
    status: str = "WAITING"    # WAITING → ACTIVE → TP1_HIT / TP2_HIT / SL_HIT
    tp1_hit: bool = False
    tp2_hit: bool = False
    sl_hit: bool = False
    entry_hit: bool = False
    highest_price: float = 0.0   # for LONG trailing tracking
    lowest_price: float = 999999999.0  # for SHORT trailing tracking
    id: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = f"{self.pair}_{self.timestamp.replace(' ', '_').replace(':', '')}"


class SignalTracker:
    def __init__(self):
        # { signal_id: TrackedSignal }
        self._signals: Dict[str, TrackedSignal] = {}
        self._client = None  # injected after init
        self._bot = None     # injected after init
        self._running = False

    def inject(self, client, bot):
        """Inject BinanceClient and telegram Bot after construction"""
        self._client = client
        self._bot = bot

    def add_signal(self, signal: dict, chat_id: int) -> TrackedSignal:
        """Register a new signal — skips if same pair+direction already active for this chat"""
        pair      = signal["pair"]
        direction = signal["signal"]

        # Deduplicate: one active signal per pair per direction per chat
        for existing in self._signals.values():
            if existing.pair == pair and existing.signal == direction and existing.chat_id == chat_id:
                logger.info(f"⚠️  Duplicate skipped: {pair} {direction} already tracked for chat {chat_id}")
                return existing

        ts = TrackedSignal(
            pair=pair,
            signal=direction,
            entry=signal["entry"],
            stop_loss=signal["stop_loss"],
            tp1=signal["tp1"],
            tp2=signal["tp2"],
            rr_ratio=signal["rr_ratio"],
            probability=signal["probability"],
            risk_level=signal["risk_level"],
            chat_id=chat_id,
            timestamp=signal["timestamp"],
        )
        self._signals[ts.id] = ts
        logger.info(f"📡 Tracking signal: {ts.pair} {ts.signal} | ID={ts.id}")
        return ts

    def remove_signal(self, signal_id: str):
        self._signals.pop(signal_id, None)

    def get_active_signals(self, chat_id: int = None) -> List[TrackedSignal]:
        sigs = list(self._signals.values())
        if chat_id:
            sigs = [s for s in sigs if s.chat_id == chat_id]
        return sigs

    async def get_current_price(self, symbol: str) -> Optional[float]:
        try:
            data = await self._client.get(f"/fapi/v1/ticker/price", {"symbol": symbol})
            return float(data["price"])
        except Exception as e:
            logger.debug(f"Price fetch error {symbol}: {e}")
            return None

    async def check_all(self):
        """Check all tracked signals against current prices"""
        if not self._signals:
            return

        for sig_id, sig in list(self._signals.items()):
            try:
                price = await self.get_current_price(sig.pair)
                if price is None:
                    continue

                alerts = []

                # ── LONG logic ──────────────────────────────
                if sig.signal == "LONG":
                    sig.highest_price = max(sig.highest_price, price)

                    # Entry hit — mark active, no alert needed
                    if not sig.entry_hit and price >= sig.entry * 0.9995:
                        sig.entry_hit = True
                        sig.status = "ACTIVE"

                    if sig.entry_hit:
                        # SL hit — only if TP1 has NOT been hit yet
                        if not sig.sl_hit and not sig.tp1_hit and price <= sig.stop_loss:
                            sig.sl_hit = True
                            sig.status = "SL_HIT"
                            alerts.append(("sl", price))

                        # TP1 hit
                        elif not sig.tp1_hit and price >= sig.tp1:
                            sig.tp1_hit = True
                            alerts.append(("tp1", price))

                        # TP2 hit
                        if sig.tp1_hit and not sig.tp2_hit and price >= sig.tp2:
                            sig.tp2_hit = True
                            sig.status = "TP2_HIT"
                            alerts.append(("tp2", price))

                # ── SHORT logic ─────────────────────────────
                else:
                    sig.lowest_price = min(sig.lowest_price, price)

                    # Entry hit — mark active, no alert needed
                    if not sig.entry_hit and price <= sig.entry * 1.0005:
                        sig.entry_hit = True
                        sig.status = "ACTIVE"

                    if sig.entry_hit:
                        # SL hit — only if TP1 has NOT been hit yet
                        if not sig.sl_hit and not sig.tp1_hit and price >= sig.stop_loss:
                            sig.sl_hit = True
                            sig.status = "SL_HIT"
                            alerts.append(("sl", price))

                        # TP1 hit
                        elif not sig.tp1_hit and price <= sig.tp1:
                            sig.tp1_hit = True
                            alerts.append(("tp1", price))

                        # TP2 hit
                        if sig.tp1_hit and not sig.tp2_hit and price <= sig.tp2:
                            sig.tp2_hit = True
                            sig.status = "TP2_HIT"
                            alerts.append(("tp2", price))

                # Send alerts
                for alert_type, alert_price in alerts:
                    await self._send_alert(sig, alert_type, alert_price)

                # Remove signal if fully closed
                if sig.sl_hit or sig.tp2_hit:
                    logger.info(f"✅ Signal {sig_id} closed — removing from tracker")
                    self.remove_signal(sig_id)

            except Exception as e:
                logger.error(f"Tracker error for {sig_id}: {e}")

    async def _send_alert(self, sig: TrackedSignal, alert_type: str, price: float):
        direction_emoji = "🟢" if sig.signal == "LONG" else "🔴"

        pnl_pct = None
        if sig.entry > 0:
            if sig.signal == "LONG":
                pnl_pct = ((price - sig.entry) / sig.entry) * 100
            else:
                pnl_pct = ((sig.entry - price) / sig.entry) * 100

        pnl_str = f"`{pnl_pct:+.2f}%`" if pnl_pct is not None else ""

        # Pre-calculate level percentages
        sl_pct  = _level_pct(sig.entry, sig.stop_loss, sig.signal)
        tp1_pct = _level_pct(sig.entry, sig.tp1, sig.signal)
        tp2_pct = _level_pct(sig.entry, sig.tp2, sig.signal)

        if alert_type == "tp1":
            msg = (
                f"🎯 *TP1 HIT!*\n\n"
                f"{direction_emoji} *{sig.pair}* — {sig.signal}\n"
                f"✅ Price reached `{price}` — TP1 `{sig.tp1}` ({tp1_pct}) touched!\n"
                f"💵 P&L so far: {pnl_str}\n\n"
                f"⚡ Consider moving SL to breakeven\n"
                f"🏆 Riding to TP2: `{sig.tp2}` ({tp2_pct})\n"
                f"⏰ `{_now()}`"
            )

        elif alert_type == "tp2":
            msg = (
                f"🏆 *TP2 HIT — FULL TARGET REACHED!* 🎉\n\n"
                f"{direction_emoji} *{sig.pair}* — {sig.signal}\n"
                f"✅ Price reached `{price}` — TP2 `{sig.tp2}` ({tp2_pct}) hit!\n"
                f"💵 Total P&L: {pnl_str}\n"
                f"📐 RR achieved: `1:{sig.rr_ratio}`\n\n"
                f"🔒 Signal closed — great trade!\n"
                f"⏰ `{_now()}`"
            )

        elif alert_type == "sl":
            msg = (
                f"🛑 *STOP LOSS HIT*\n\n"
                f"{direction_emoji} *{sig.pair}* — {sig.signal}\n"
                f"❌ Price hit `{price}` — SL `{sig.stop_loss}` ({sl_pct}) triggered\n"
                f"💵 P&L: {pnl_str}\n\n"
                f"🔒 Signal closed — protect capital & move on\n"
                f"⏰ `{_now()}`"
            )
        else:
            return

        try:
            await self._bot.send_message(
                sig.chat_id,
                msg,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")

    async def run_loop(self):
        """Background loop that checks prices every TRACKER_INTERVAL seconds"""
        self._running = True
        logger.info("📡 Live tracker started")
        while self._running:
            try:
                await self.check_all()
            except Exception as e:
                logger.error(f"Tracker loop error: {e}")
            await asyncio.sleep(TRACKER_INTERVAL)

    def stop(self):
        self._running = False


def _level_pct(entry: float, target: float, direction: str) -> str:
    """Return formatted % distance from entry to a price level"""
    if entry == 0:
        return "0.00%"
    if direction == "LONG":
        pct = ((target - entry) / entry) * 100
    else:
        pct = ((entry - target) / entry) * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.2f}%"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

"""
Crypto Futures Signal Bot
Clean professional output — signals + TP/SL alerts only, zero noise
"""

import asyncio
import logging
from telegram import Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update
from config import TELEGRAM_BOT_TOKEN, SCAN_INTERVAL_MINUTES, TELEGRAM_CHAT_IDS
from scanner import MarketScanner
from tracker import SignalTracker

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

scanner = MarketScanner()
tracker = SignalTracker()
active_chats: set = set(TELEGRAM_CHAT_IDS)


# ─────────────────────────────────────────────
# /start  — silent registration, no spam
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    active_chats.add(chat_id)
    # Only reply to the person starting — not visible to channel followers
    await update.message.reply_text(
        f"✅ Bot active\\. Signals will appear automatically\\.\n"
        f"Your ID: `{chat_id}`",
        parse_mode='MarkdownV2'
    )


# ─────────────────────────────────────────────
# /myid  — admin only helper
# ─────────────────────────────────────────────
async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"`{chat_id}`", parse_mode='MarkdownV2')


# ─────────────────────────────────────────────
# /positions  — clean active signals list
# ─────────────────────────────────────────────
async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    sigs = tracker.get_active_signals(chat_id)

    if not sigs:
        await update.message.reply_text("No active signals right now\\.", parse_mode='MarkdownV2')
        return

    lines = []
    for s in sigs:
        d  = "🟢" if s.signal == "LONG" else "🔴"
        t1 = "✅" if s.tp1_hit else "⬜"
        t2 = "✅" if s.tp2_hit else "⬜"
        tp1_pct = _pct(s.entry, s.tp1, s.signal)
        tp2_pct = _pct(s.entry, s.tp2, s.signal)
        sl_pct  = _pct(s.entry, s.stop_loss, s.signal)
        lines.append(
            f"{d} *{s.pair}*  `{s.signal}`\n"
            f"  Entry  `{s.entry}`\n"
            f"  {t1} TP1  `{s.tp1}`  {tp1_pct}\n"
            f"  {t2} TP2  `{s.tp2}`  {tp2_pct}\n"
            f"  🛑 SL   `{s.stop_loss}`  {sl_pct}"
        )

    await update.message.reply_text(
        "\n\n".join(lines),
        parse_mode='Markdown'
    )


# ─────────────────────────────────────────────
# Core scan runner — SILENT, signals only
# ─────────────────────────────────────────────
async def run_scan(bot: Bot, chat_id: int):
    try:
        signals = await scanner.scan_all_pairs()
        # No message if nothing found — total silence
        for signal in signals:
            await bot.send_message(
                chat_id,
                format_signal(signal),
                parse_mode='Markdown'
            )
            tracker.add_signal(signal, chat_id)
            await asyncio.sleep(0.3)
    except Exception as e:
        logger.error(f"Scan error: {e}", exc_info=True)


# ─────────────────────────────────────────────
# Signal card — clean, professional, simple
# ─────────────────────────────────────────────
def format_signal(s: dict) -> str:
    is_long   = s['signal'] == "LONG"
    direction = "LONG 🟢" if is_long else "SHORT 🔴"
    entry     = s['entry']
    sl        = s['stop_loss']
    tp1       = s['tp1']
    tp2       = s['tp2']

    sl_pct  = _pct(entry, sl,  s['signal'])
    tp1_pct = _pct(entry, tp1, s['signal'])
    tp2_pct = _pct(entry, tp2, s['signal'])

    return (
        f"⚡ *{s['pair']}*\n"
        f"{'▲ ' if is_long else '▼ '}{direction}\n"
        f"─────────────────\n"
        f"*Entry*   `{entry}`\n"
        f"*TP 1*    `{tp1}`  {tp1_pct}\n"
        f"*TP 2*    `{tp2}`  {tp2_pct}\n"
        f"*SL*      `{sl}`  {sl_pct}\n"
        f"─────────────────\n"
        f"RR `1:{s['rr_ratio']:.1f}`  │  Score `{s['probability']}%`  │  {s['risk_level']} Risk"
    )


# ─────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────
def _pct(entry: float, target: float, direction: str) -> str:
    if entry == 0:
        return ""
    pct = ((target - entry) / entry * 100) if direction == "LONG" else ((entry - target) / entry * 100)
    sign = "+" if pct >= 0 else ""
    return f"`{sign}{pct:.2f}%`"


# ─────────────────────────────────────────────
# Scheduled jobs
# ─────────────────────────────────────────────
async def auto_scan_job(context: ContextTypes.DEFAULT_TYPE):
    if not active_chats:
        return
    logger.info(f"Auto-scan → {len(active_chats)} chat(s)")
    for chat_id in list(active_chats):
        try:
            await run_scan(context.bot, chat_id)
        except Exception as e:
            logger.error(f"Scan error {chat_id}: {e}")


async def tracker_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        await tracker.check_all()
    except Exception as e:
        logger.error(f"Tracker error: {e}")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    tracker.inject(client=scanner.client, bot=app.bot)

    app.add_handler(CommandHandler("start",     start))
    app.add_handler(CommandHandler("myid",      myid_command))
    app.add_handler(CommandHandler("positions", positions_command))

    # Auto scan
    app.job_queue.run_repeating(
        auto_scan_job,
        interval=SCAN_INTERVAL_MINUTES * 60,
        first=60  # first scan 1 min after startup
    )

    # Live tracker
    app.job_queue.run_repeating(
        tracker_job,
        interval=30,
        first=15
    )

    logger.info(f"Bot running — {len(active_chats)} chat(s) configured")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

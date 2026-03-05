"""
Telegram Crypto Futures Trading Signal Bot
Uses Binance public API (no key required)
Smart Money Concepts + Multi-Timeframe Analysis + Live Signal Tracking
"""

import asyncio
import logging
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram import Update
from config import TELEGRAM_BOT_TOKEN, SCAN_INTERVAL_MINUTES
from scanner import MarketScanner
from tracker import SignalTracker

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

scanner = MarketScanner()
tracker = SignalTracker()
active_chats = set()


# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    active_chats.add(chat_id)

    keyboard = [
        [InlineKeyboardButton("🔍 Scan Now", callback_data='scan_now')],
        [InlineKeyboardButton("📡 Active Signals", callback_data='active_signals')],
        [InlineKeyboardButton("📊 All Pairs", callback_data='top_pairs')],
        [InlineKeyboardButton("⚙️ Settings", callback_data='settings')],
    ]

    await update.message.reply_text(
        "🤖 *Smart Money Crypto Signal Bot*\n\n"
        "✅ Multi-Timeframe Analysis (4H + 15M)\n"
        "✅ BOS / CHOCH Market Structure\n"
        "✅ Liquidity Sweeps Detection\n"
        "✅ Order Blocks & Fair Value Gaps\n"
        "✅ RSI + Volume Confirmation\n"
        "✅ Auto Risk Management\n"
        "✅ 🔴 *Live TP / SL Alerts*\n\n"
        f"🔄 Auto-scan every *{SCAN_INTERVAL_MINUTES} minutes*\n"
        f"📡 Price checked every *30 seconds* for alerts\n\n"
        "Commands: /scan /positions /help",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ─────────────────────────────────────────────
# /scan
# ─────────────────────────────────────────────
async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    active_chats.add(chat_id)
    msg = await update.message.reply_text("🔍 Scanning ALL USDT futures pairs... ⏳")
    await run_scan(context.bot, chat_id)


# ─────────────────────────────────────────────
# /positions — show active tracked signals
# ─────────────────────────────────────────────
async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    sigs = tracker.get_active_signals(chat_id)

    if not sigs:
        await update.message.reply_text(
            "📡 *No active tracked signals.*\n\nRun /scan to find new setups.",
            parse_mode='Markdown'
        )
        return

    text = f"📡 *{len(sigs)} Active Signal(s) Being Tracked:*\n\n"
    for s in sigs:
        status_emoji = {
            "WAITING":  "⏳",
            "ACTIVE":   "🟢",
            "TP1_HIT":  "🎯",
            "TP2_HIT":  "🏆",
            "SL_HIT":   "🛑",
        }.get(s.status, "⚪")

        tp1_check = "✅" if s.tp1_hit else "⬜"
        tp2_check = "✅" if s.tp2_hit else "⬜"
        sl_check  = "✅" if s.sl_hit  else "⬜"
        dir_emoji = "🟢" if s.signal == "LONG" else "🔴"

        text += (
            f"{status_emoji} {dir_emoji} *{s.pair}* — {s.signal}\n"
            f"   💰 Entry: `{s.entry}`\n"
            f"   {tp1_check} TP1: `{s.tp1}`\n"
            f"   {tp2_check} TP2: `{s.tp2}`\n"
            f"   {sl_check} SL:  `{s.stop_loss}`\n"
            f"   Status: `{s.status}`\n\n"
        )

    await update.message.reply_text(text, parse_mode='Markdown')


# ─────────────────────────────────────────────
# Button handler
# ─────────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    if query.data == 'scan_now':
        await query.edit_message_text("🔍 Scanning ALL USDT futures pairs... ⏳")
        await run_scan(context.bot, chat_id)

    elif query.data == 'active_signals':
        sigs = tracker.get_active_signals(chat_id)
        if not sigs:
            await context.bot.send_message(
                chat_id,
                "📡 *No active tracked signals yet.*\nRun a scan first.",
                parse_mode='Markdown'
            )
        else:
            text = f"📡 *{len(sigs)} Active Tracked Signal(s):*\n\n"
            for s in sigs:
                dir_emoji = "🟢" if s.signal == "LONG" else "🔴"
                tp1_check = "✅" if s.tp1_hit else "⬜"
                tp2_check = "✅" if s.tp2_hit else "⬜"
                text += (
                    f"{dir_emoji} *{s.pair}* `{s.signal}` — `{s.status}`\n"
                    f"   {tp1_check} TP1 `{s.tp1}`  |  {tp2_check} TP2 `{s.tp2}`  |  SL `{s.stop_loss}`\n\n"
                )
            await context.bot.send_message(chat_id, text, parse_mode='Markdown')

    elif query.data == 'top_pairs':
        await query.edit_message_text("📊 Fetching all USDT futures pairs...")
        try:
            pairs = await scanner.get_top_usdt_pairs()
            text = f"📊 *All USDT Futures Pairs ({len(pairs)} total):*\n\n"
            for i, p in enumerate(pairs[:30], 1):
                text += f"{i}. `{p['symbol']}` — ${p['volume_usd']:,.0f}\n"
            if len(pairs) > 30:
                text += f"\n_...and {len(pairs)-30} more pairs_"
            await context.bot.send_message(chat_id, text, parse_mode='Markdown')
        except Exception as e:
            await context.bot.send_message(chat_id, f"❌ Error: {e}")

    elif query.data == 'settings':
        from config import SCAN_INTERVAL_MINUTES, MIN_PROBABILITY_SCORE, MIN_RR_RATIO, HIGHER_TF, LOWER_TF
        from tracker import TRACKER_INTERVAL
        text = (
            f"⚙️ *Current Settings:*\n\n"
            f"• Scan Interval: `{SCAN_INTERVAL_MINUTES} min`\n"
            f"• Price Check: every `30 sec`\n"
            f"• Higher TF: `{HIGHER_TF.upper()}`\n"
            f"• Lower TF: `{LOWER_TF.upper()}`\n"
            f"• Min RR Ratio: `1:{MIN_RR_RATIO}`\n"
            f"• Min Probability: `{MIN_PROBABILITY_SCORE}%`\n"
            f"• Pairs Scanned: ALL USDT futures\n"
        )
        await context.bot.send_message(chat_id, text, parse_mode='Markdown')


# ─────────────────────────────────────────────
# Core scan runner
# ─────────────────────────────────────────────
async def run_scan(bot: Bot, chat_id: int):
    try:
        signals = await scanner.scan_all_pairs()

        if not signals:
            await bot.send_message(
                chat_id,
                "🔍 *Scan Complete*\n\n"
                "⚠️ No high-probability signals found.\n"
                "Only signals with 60%+ confluence are reported.\n"
                "Market may be choppy — waiting for cleaner setups.",
                parse_mode='Markdown'
            )
            return

        await bot.send_message(
            chat_id,
            f"✅ *Scan Complete — {len(signals)} Signal(s) Found!*\n"
            f"📡 All signals are now being live tracked for TP/SL alerts.",
            parse_mode='Markdown'
        )

        for signal in signals:
            # Send the signal message
            msg = format_signal(signal)
            await bot.send_message(chat_id, msg, parse_mode='Markdown')

            # Register for live tracking
            tracker.add_signal(signal, chat_id)

            await asyncio.sleep(0.5)

    except Exception as e:
        logger.error(f"Scan error: {e}", exc_info=True)
        await bot.send_message(chat_id, f"❌ Scan error: {str(e)[:300]}")


# ─────────────────────────────────────────────
# Signal message formatter
# ─────────────────────────────────────────────
def format_signal(s: dict) -> str:
    direction = s['signal']
    emoji = "🟢 LONG" if direction == "LONG" else "🔴 SHORT"
    risk_emoji = {"Low": "🟢", "Medium": "🟡", "High": "🔴"}.get(s['risk_level'], "⚪")
    confirmations = "\n".join([f"   • {c}" for c in s['confirmations']])

    return (
        f"{'='*36}\n"
        f"📌 *{s['pair']}* — {emoji}\n"
        f"{'='*36}\n\n"
        f"💰 *Entry:* `{s['entry']}`\n"
        f"🛑 *Stop Loss:* `{s['stop_loss']}`\n"
        f"🎯 *TP1:* `{s['tp1']}`\n"
        f"🏆 *TP2:* `{s['tp2']}`\n\n"
        f"📐 *RR Ratio:* `1:{s['rr_ratio']:.1f}`\n"
        f"🎲 *Probability:* `{s['probability']}%`\n"
        f"{risk_emoji} *Risk Level:* `{s['risk_level']}`\n\n"
        f"📋 *Confirmations:*\n{confirmations}\n\n"
        f"📡 _Live tracking active — alerts will fire on TP/SL_\n"
        f"⏰ `{s['timestamp']}`\n"
        f"{'='*36}"
    )


# ─────────────────────────────────────────────
# Scheduled jobs
# ─────────────────────────────────────────────
async def auto_scan_job(context: ContextTypes.DEFAULT_TYPE):
    if not active_chats:
        return
    logger.info(f"⏰ Auto-scan triggered for {len(active_chats)} chat(s)")
    for chat_id in list(active_chats):
        try:
            await run_scan(context.bot, chat_id)
        except Exception as e:
            logger.error(f"Auto-scan error for {chat_id}: {e}")


async def tracker_job(context: ContextTypes.DEFAULT_TYPE):
    """Runs every 30 seconds to check prices and fire TP/SL alerts"""
    try:
        await tracker.check_all()
    except Exception as e:
        logger.error(f"Tracker job error: {e}")


# ─────────────────────────────────────────────
# /help
# ─────────────────────────────────────────────
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Bot Commands:*\n\n"
        "/start — Start bot & show menu\n"
        "/scan — Manual market scan (all USDT pairs)\n"
        "/positions — View all live tracked signals\n"
        "/help — This message\n\n"
        "📡 *Live Tracking Alerts:*\n"
        "After every scan, each signal is automatically tracked.\n"
        "You'll get instant alerts when:\n"
        "• 🚀 Entry price is filled\n"
        "• 🎯 TP1 is hit (move SL to breakeven)\n"
        "• 🏆 TP2 is hit (full target)\n"
        "• 🛑 SL is hit (position closed)\n\n"
        "🧠 *Strategy:* 4H trend + 15M entry\n"
        "BOS/CHOCH · Liquidity Sweeps · OB · FVG · RSI · Volume",
        parse_mode='Markdown'
    )


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Inject bot into tracker so it can send alerts
    tracker.inject(
        client=scanner.client,
        bot=app.bot
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan_command))
    app.add_handler(CommandHandler("positions", positions_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    # Auto scan job (every N minutes)
    app.job_queue.run_repeating(
        auto_scan_job,
        interval=SCAN_INTERVAL_MINUTES * 60,
        first=SCAN_INTERVAL_MINUTES * 60
    )

    # Live tracker job (every 30 seconds)
    app.job_queue.run_repeating(
        tracker_job,
        interval=30,
        first=15  # start 15s after bot launch
    )

    logger.info("🤖 Bot started with live signal tracking!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

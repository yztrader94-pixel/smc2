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
from config import TELEGRAM_BOT_TOKEN, SCAN_INTERVAL_MINUTES, TELEGRAM_CHAT_IDS
from scanner import MarketScanner
from tracker import SignalTracker

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

scanner = MarketScanner()
tracker = SignalTracker()

# Merged set: manual /start users + pre-configured IDs from config.py
active_chats: set = set(TELEGRAM_CHAT_IDS)


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
        "✅ 📡 *Live TP / SL Alerts*\n\n"
        f"🔄 Auto-scan every *{SCAN_INTERVAL_MINUTES} minutes*\n"
        f"📡 Price checked every *30 seconds* for alerts\n\n"
        f"🆔 Your chat ID: `{chat_id}`\n\n"
        "Commands: /scan /positions /myid /help",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ─────────────────────────────────────────────
# /myid — show chat ID (useful for config)
# ─────────────────────────────────────────────
async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    chat_title = update.effective_chat.title or "Personal Chat"
    await update.message.reply_text(
        f"🆔 *Chat Info*\n\n"
        f"• Type: `{chat_type}`\n"
        f"• Name: `{chat_title}`\n"
        f"• ID: `{chat_id}`\n\n"
        f"Add this ID to `TELEGRAM_CHAT_IDS` in `config.py` to receive auto-scan signals.",
        parse_mode='Markdown'
    )


# ─────────────────────────────────────────────
# /scan
# ─────────────────────────────────────────────
async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    active_chats.add(chat_id)
    await update.message.reply_text("🔍 Scanning ALL USDT futures pairs... ⏳")
    await run_scan(context.bot, chat_id)


# ─────────────────────────────────────────────
# /positions
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
            "WAITING": "⏳", "ACTIVE": "🟢",
            "TP1_HIT": "🎯", "TP2_HIT": "🏆", "SL_HIT": "🛑",
        }.get(s.status, "⚪")
        dir_emoji  = "🟢" if s.signal == "LONG" else "🔴"
        tp1_pct    = _pct(s.entry, s.tp1, s.signal)
        tp2_pct    = _pct(s.entry, s.tp2, s.signal)
        sl_pct     = _pct(s.entry, s.stop_loss, s.signal)
        tp1_check  = "✅" if s.tp1_hit else "⬜"
        tp2_check  = "✅" if s.tp2_hit else "⬜"
        sl_check   = "✅" if s.sl_hit  else "⬜"

        text += (
            f"{status_emoji} {dir_emoji} *{s.pair}* — {s.signal}\n"
            f"   💰 Entry: `{s.entry}`\n"
            f"   {tp1_check} TP1: `{s.tp1}` ({tp1_pct})\n"
            f"   {tp2_check} TP2: `{s.tp2}` ({tp2_pct})\n"
            f"   {sl_check} SL:  `{s.stop_loss}` ({sl_pct})\n"
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
                tp1_pct   = _pct(s.entry, s.tp1, s.signal)
                tp2_pct   = _pct(s.entry, s.tp2, s.signal)
                sl_pct    = _pct(s.entry, s.stop_loss, s.signal)
                tp1_check = "✅" if s.tp1_hit else "⬜"
                tp2_check = "✅" if s.tp2_hit else "⬜"
                text += (
                    f"{dir_emoji} *{s.pair}* `{s.signal}` — `{s.status}`\n"
                    f"   {tp1_check} TP1 `{s.tp1}` ({tp1_pct})\n"
                    f"   {tp2_check} TP2 `{s.tp2}` ({tp2_pct})\n"
                    f"   SL `{s.stop_loss}` ({sl_pct})\n\n"
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
                text += f"\n_...and {len(pairs)-30} more pairs being scanned_"
            await context.bot.send_message(chat_id, text, parse_mode='Markdown')
        except Exception as e:
            await context.bot.send_message(chat_id, f"❌ Error: {e}")

    elif query.data == 'settings':
        from config import MIN_PROBABILITY_SCORE, MIN_RR_RATIO, HIGHER_TF, LOWER_TF
        configured_ids = ", ".join(str(i) for i in TELEGRAM_CHAT_IDS) or "None (manual /start only)"
        text = (
            f"⚙️ *Current Settings:*\n\n"
            f"• Scan Interval: `{SCAN_INTERVAL_MINUTES} min`\n"
            f"• Price Check: every `30 sec`\n"
            f"• Higher TF: `{HIGHER_TF.upper()}`\n"
            f"• Lower TF: `{LOWER_TF.upper()}`\n"
            f"• Min RR Ratio: `1:{MIN_RR_RATIO}`\n"
            f"• Min Probability: `{MIN_PROBABILITY_SCORE}%`\n"
            f"• Pairs Scanned: ALL USDT futures\n\n"
            f"📨 *Configured Chat IDs:*\n`{configured_ids}`\n\n"
            f"📌 Use /myid to get any chat's ID"
        )
        await context.bot.send_message(chat_id, text, parse_mode='Markdown')


# ─────────────────────────────────────────────
# Core scan runner — sends to one chat
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
            f"📡 All signals are now live tracked for TP/SL alerts.",
            parse_mode='Markdown'
        )

        for signal in signals:
            await bot.send_message(chat_id, format_signal(signal), parse_mode='Markdown')
            tracker.add_signal(signal, chat_id)
            await asyncio.sleep(0.5)

    except Exception as e:
        logger.error(f"Scan error: {e}", exc_info=True)
        await bot.send_message(chat_id, f"❌ Scan error: {str(e)[:300]}")


# ─────────────────────────────────────────────
# Signal formatter — prices + percentages
# ─────────────────────────────────────────────
def format_signal(s: dict) -> str:
    direction  = s['signal']
    emoji      = "🟢 LONG" if direction == "LONG" else "🔴 SHORT"
    risk_emoji = {"Low": "🟢", "Medium": "🟡", "High": "🔴"}.get(s['risk_level'], "⚪")
    confirms   = "\n".join([f"   • {c}" for c in s['confirmations']])

    entry = s['entry']
    sl    = s['stop_loss']
    tp1   = s['tp1']
    tp2   = s['tp2']

    sl_pct  = _pct(entry, sl,  direction)
    tp1_pct = _pct(entry, tp1, direction)
    tp2_pct = _pct(entry, tp2, direction)

    return (
        f"{'='*36}\n"
        f"📌 *{s['pair']}* — {emoji}\n"
        f"{'='*36}\n\n"
        f"💰 *Entry:*     `{entry}`\n"
        f"🛑 *Stop Loss:* `{sl}` ({sl_pct})\n"
        f"🎯 *TP1:*       `{tp1}` ({tp1_pct})\n"
        f"🏆 *TP2:*       `{tp2}` ({tp2_pct})\n\n"
        f"📐 *RR Ratio:*  `1:{s['rr_ratio']:.1f}`\n"
        f"🎲 *Probability:* `{s['probability']}%`\n"
        f"{risk_emoji} *Risk Level:* `{s['risk_level']}`\n\n"
        f"📋 *Confirmations:*\n{confirms}\n\n"
        f"📡 _Live tracking active — TP/SL alerts enabled_\n"
        f"⏰ `{s['timestamp']}`\n"
        f"{'='*36}"
    )


# ─────────────────────────────────────────────
# Helper: price → percentage from entry
# ─────────────────────────────────────────────
def _pct(entry: float, target: float, direction: str) -> str:
    if entry == 0:
        return "0.00%"
    if direction == "LONG":
        pct = ((target - entry) / entry) * 100
    else:
        pct = ((entry - target) / entry) * 100
    sign = "+" if pct >= 0 else ""
    return f"`{sign}{pct:.2f}%`"


# ─────────────────────────────────────────────
# Scheduled jobs
# ─────────────────────────────────────────────
async def auto_scan_job(context: ContextTypes.DEFAULT_TYPE):
    if not active_chats:
        return
    logger.info(f"⏰ Auto-scan → {len(active_chats)} chat(s)")
    for chat_id in list(active_chats):
        try:
            await run_scan(context.bot, chat_id)
        except Exception as e:
            logger.error(f"Auto-scan error for {chat_id}: {e}")


async def tracker_job(context: ContextTypes.DEFAULT_TYPE):
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
        "/start     — Start bot & show menu\n"
        "/scan      — Manual scan (all USDT futures)\n"
        "/positions — View all live tracked signals\n"
        "/myid      — Show this chat's ID for config\n"
        "/help      — This message\n\n"
        "📡 *Live Tracking Alerts:*\n"
        "• 🚀 Entry filled\n"
        "• 🎯 TP1 hit → SL disabled, riding to TP2\n"
        "• 🏆 TP2 hit → full target, signal closed\n"
        "• 🛑 SL hit → only fires if TP1 not reached\n\n"
        "📨 *Add groups/channels:*\n"
        "Use /myid in the chat to get its ID,\n"
        "then add it to `TELEGRAM_CHAT_IDS` in `config.py`",
        parse_mode='Markdown'
    )


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    tracker.inject(client=scanner.client, bot=app.bot)

    app.add_handler(CommandHandler("start",     start))
    app.add_handler(CommandHandler("scan",      scan_command))
    app.add_handler(CommandHandler("positions", positions_command))
    app.add_handler(CommandHandler("myid",      myid_command))
    app.add_handler(CommandHandler("help",      help_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    # Auto market scan (every N minutes)
    app.job_queue.run_repeating(
        auto_scan_job,
        interval=SCAN_INTERVAL_MINUTES * 60,
        first=SCAN_INTERVAL_MINUTES * 60
    )

    # Live price tracker (every 30 seconds)
    app.job_queue.run_repeating(
        tracker_job,
        interval=30,
        first=15
    )

    logger.info(f"🤖 Bot started! Broadcasting to {len(active_chats)} pre-configured chat(s)")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

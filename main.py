"""
Telegram Crypto Futures Trading Signal Bot
Uses Binance public API (no key required)
Smart Money Concepts + Multi-Timeframe Analysis
"""

import asyncio
import logging
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram import Update
from config import TELEGRAM_BOT_TOKEN, SCAN_INTERVAL_MINUTES, TOP_PAIRS_LIMIT
from scanner import MarketScanner

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

scanner = MarketScanner()
active_chats = set()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    active_chats.add(chat_id)

    keyboard = [
        [InlineKeyboardButton("🔍 Scan Now", callback_data='scan_now')],
        [InlineKeyboardButton("📊 Top Pairs", callback_data='top_pairs')],
        [InlineKeyboardButton("⚙️ Settings", callback_data='settings')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🤖 *Smart Money Crypto Signal Bot*\n\n"
        "✅ Multi-Timeframe Analysis (4H + 15M)\n"
        "✅ Break of Structure (BOS/CHOCH)\n"
        "✅ Liquidity Sweeps Detection\n"
        "✅ Order Blocks & Fair Value Gaps\n"
        "✅ RSI + Volume Confirmation\n"
        "✅ Auto Risk Management\n\n"
        f"🔄 Auto-scan every *{SCAN_INTERVAL_MINUTES} minutes*\n"
        f"📈 Scanning top *{TOP_PAIRS_LIMIT}* USDT pairs\n\n"
        "Use /scan to trigger a manual scan",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    active_chats.add(chat_id)
    msg = await update.message.reply_text("🔍 Scanning markets... please wait ⏳")
    await run_scan(context.bot, chat_id, msg.message_id)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    if query.data == 'scan_now':
        await query.edit_message_text("🔍 Scanning markets... please wait ⏳")
        await run_scan(context.bot, chat_id, query.message.message_id)

    elif query.data == 'top_pairs':
        await query.edit_message_text("📊 Fetching top USDT pairs by volume...")
        try:
            pairs = await scanner.get_top_usdt_pairs()
            text = "📊 *Top USDT Futures Pairs by Volume:*\n\n"
            for i, p in enumerate(pairs[:20], 1):
                text += f"{i}. `{p['symbol']}` — Vol: ${p['volume_usd']:,.0f}\n"
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back')]]
            await context.bot.send_message(chat_id, text, parse_mode='Markdown',
                                           reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            await context.bot.send_message(chat_id, f"❌ Error: {e}")

    elif query.data == 'settings':
        text = (
            f"⚙️ *Current Settings:*\n\n"
            f"• Scan Interval: `{SCAN_INTERVAL_MINUTES} min`\n"
            f"• Pairs Scanned: `{TOP_PAIRS_LIMIT}`\n"
            f"• Higher TF: `4H`\n"
            f"• Lower TF: `15M`\n"
            f"• Min RR Ratio: `1:2`\n"
            f"• Min Probability: `60%`\n"
        )
        await context.bot.send_message(chat_id, text, parse_mode='Markdown')

    elif query.data == 'back':
        pass


async def run_scan(bot: Bot, chat_id: int, msg_id: int = None):
    try:
        signals = await scanner.scan_all_pairs()

        if not signals:
            await bot.send_message(
                chat_id,
                "🔍 Scan complete.\n\n⚠️ *No high-probability signals found.*\n"
                "The bot only sends signals with 60%+ probability score.\n"
                "Market conditions may be choppy — waiting for clearer setups.",
                parse_mode='Markdown'
            )
            return

        await bot.send_message(
            chat_id,
            f"✅ *Scan Complete — {len(signals)} Signal(s) Found!*",
            parse_mode='Markdown'
        )

        for signal in signals:
            msg = format_signal(signal)
            await bot.send_message(chat_id, msg, parse_mode='Markdown')
            await asyncio.sleep(0.5)

    except Exception as e:
        logger.error(f"Scan error: {e}", exc_info=True)
        await bot.send_message(chat_id, f"❌ Scan error: {str(e)[:200]}")


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
        f"⏰ `{s['timestamp']}`\n"
        f"{'='*36}"
    )


async def auto_scan_job(context: ContextTypes.DEFAULT_TYPE):
    if not active_chats:
        return
    logger.info(f"Auto-scan triggered for {len(active_chats)} chats")
    for chat_id in list(active_chats):
        try:
            await run_scan(context.bot, chat_id)
        except Exception as e:
            logger.error(f"Auto-scan error for {chat_id}: {e}")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Bot Commands:*\n\n"
        "/start — Start the bot & show menu\n"
        "/scan — Trigger manual market scan\n"
        "/help — Show this help message\n\n"
        "🧠 *Strategy Logic:*\n"
        "• 4H trend direction filter\n"
        "• 15M entry timeframe\n"
        "• BOS/CHOCH market structure\n"
        "• Liquidity sweep detection\n"
        "• Order blocks & FVG zones\n"
        "• RSI + Volume confirmation\n"
        "• Min 1:2 Risk-Reward ratio",
        parse_mode='Markdown'
    )


def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    # Auto scan job
    app.job_queue.run_repeating(
        auto_scan_job,
        interval=SCAN_INTERVAL_MINUTES * 60,
        first=SCAN_INTERVAL_MINUTES * 60
    )

    logger.info("🤖 Bot started!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

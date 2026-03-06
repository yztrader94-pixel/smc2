"""
Bot Configuration
"""

# =============================================
# REQUIRED: Set your Telegram Bot Token here
# Get it from @BotFather on Telegram
# =============================================
TELEGRAM_BOT_TOKEN = "7957028587:AAE7aSYtE4hCxxTIPkAs_1ULJ9e8alkY6Ic"

# =============================================
# TELEGRAM CHAT IDs — Who receives signals
# =============================================
# Add any mix of:
#   Personal user ID  → e.g. 123456789         (positive number)
#   Group chat ID     → e.g. -1001234567890    (groups are negative)
#   Channel ID        → e.g. -1009876543210    (channels are negative)
#
# How to find your ID:
#   Personal : message @userinfobot on Telegram
#   Group    : add @userinfobot to the group → it replies with the chat ID
#   Channel  : forward any channel message to @userinfobot
#
# Leave empty [] to only serve users who /start the bot manually
TELEGRAM_CHAT_IDS = [-1002442074724
    # 123456789,          # Your personal Telegram ID
    # -1001234567890,     # Your signals group
    # -1009876543210,     # Your VIP channel
]

# =============================================
# SCAN SETTINGS
# =============================================
SCAN_INTERVAL_MINUTES = 15       # How often to auto-scan (minutes)
TOP_PAIRS_LIMIT = 999            # Scan ALL USDT pairs (Binance has ~300+)
MIN_PROBABILITY_SCORE = 70       # Minimum signal probability to send (%)
MIN_RR_RATIO = 2.0               # Minimum risk-reward ratio

# =============================================
# TIMEFRAME SETTINGS
# =============================================
HIGHER_TF = "4h"                 # Higher timeframe for trend
LOWER_TF = "15m"                 # Lower timeframe for entry

# =============================================
# STRATEGY PARAMETERS
# =============================================
RSI_PERIOD = 14
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 65
VOLUME_SPIKE_MULTIPLIER = 1.5    # Volume must be X times average
CANDLES_TO_FETCH = 100           # Number of candles to analyze
MIN_VOLUME_USD = 0               # No volume filter — scan every USDT pair

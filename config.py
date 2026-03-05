"""
Bot Configuration
"""

# =============================================
# REQUIRED: Set your Telegram Bot Token here
# Get it from @BotFather on Telegram
# =============================================
TELEGRAM_BOT_TOKEN = "7732870721:AAEHG3QJdo31S9sA8xjJzf-cXj6Tn4mo2uo"

# =============================================
# SCAN SETTINGS
# =============================================
SCAN_INTERVAL_MINUTES = 30       # How often to auto-scan (minutes)
TOP_PAIRS_LIMIT = 50             # Number of top USDT pairs to scan
MIN_PROBABILITY_SCORE = 60       # Minimum signal probability to send (%)
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
MIN_VOLUME_USD = 10_000_000      # Min 24h volume in USD to include pair

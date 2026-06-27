import os

# ─── Hyperliquid Account ───
ACCOUNT_ADDRESS = os.environ.get("HL_ACCOUNT_ADDRESS", "0xYOUR_WALLET_ADDRESS")
PRIVATE_KEY = os.environ.get("HL_PRIVATE_KEY", "0xYOUR_PRIVATE_KEY")

# ─── Telegram ───
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")

# ─── Trading Symbols ───
SYMBOLS = ["SOL/USDC", "ETH/USDC", "BTC/USDC"]

# ─── Strategy Parameters ───
TIMEFRAME = "15m"
LOOP_INTERVAL_SECONDS = 15
CANDLE_LIMIT = 60

RISK_PER_TRADE = 0.01          # 1% per symbol

EMA_FAST = 3
EMA_SLOW = 9
ATR_PERIOD = 14
ADX_PERIOD = 14

ATR_SL_MULTIPLIER = 2.0        # Stop Loss = entry +/- 2*ATR
RISK_REWARD_RATIO = 3.0        # TP = entry +/- 6*ATR (3× SL)
SAR_ATR_MULTIPLIER = 1.2       # SAR threshold = entry +/- 1.2*ATR
ADX_THRESHOLD = 23.0           # Min ADX for entries and SAR

# ─── Reporting ───
PNL_LOOKBACK_DAYS = 30

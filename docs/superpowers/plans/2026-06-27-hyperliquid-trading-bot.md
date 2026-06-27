# Hyperliquid Multi-Symbol Trading Bot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Production-ready algorithmic trading bot operating on Hyperliquid testnet with SOL, ETH, and BTC perpetual swaps using EMA 3/9 crossover + ADX filter + SAR + ATR-based stops.

**Architecture:** 6 Python modules in a flat package. `main.py` orchestrates a 15-second loop: fetch candles per symbol → compute indicators (pandas) → evaluate exits/entries per symbol → execute market orders → hourly Telegram report → gc.collect(). All external calls wrapped in safe try-except handlers.

**Tech Stack:** Python 3, ccxt, pandas, numpy, requests (Telegram API)

## Global Constraints

- Hyperliquid Testnet via `exchange.set_sandbox_mode(True)`
- Symbols: SOL/USDC, ETH/USDC, BTC/USDC (3 linear perpetuals)
- Timeframe: 15 minutes, loop interval: 15 seconds
- Risk: 1% of account balance per symbol per trade
- Candle fetch limit: 60 per symbol (strict)
- ADX threshold: 23.0 (blocks entries and SAR when below)
- ATR SL multiplier: 2.0, R:R ratio: 3.0, SAR multiplier: 1.2
- EMA periods: fast=3, slow=9; ATR period: 14; ADX period: 14
- Stops evaluated in-loop (no limit orders placed on exchange)
- Memory: `del df; gc.collect()` after each symbol indicator calc and after report
- Single `fetch_my_trades` call per symbol per hour, 30-day window
- Telegram report every hour, exact Markdown format
- All API calls wrapped in try-except, bot never crashes
- Sandbox mode enabled, no real funds at risk

---

### Task 1: Project scaffold and configuration

**Files:**
- Create: `bot_hyperliquid/requirements.txt`
- Create: `bot_hyperliquid/config.py`

**Interfaces:**
- Produces: `config.py` — all constants importable by downstream modules

- [ ] **Step 1: Write requirements.txt**

```txt
ccxt>=4.0.0
pandas>=2.0.0
numpy>=1.24.0
requests>=2.31.0
```

- [ ] **Step 2: Write config.py**

```python
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
```

- [ ] **Step 3: Commit**

```bash
git add bot_hyperliquid/requirements.txt bot_hyperliquid/config.py
git commit -m "feat: add project scaffold and configuration"
```

---

### Task 2: Exchange module — CCXT Hyperliquid wrappers

**Files:**
- Create: `bot_hyperliquid/exchange.py`

**Interfaces:**
- Consumes: `config.ACCOUNT_ADDRESS`, `config.PRIVATE_KEY`, `config.SYMBOLS`
- Produces:
  - `create_exchange() -> ccxt.Exchange`
  - `fetch_ohlcv_safe(exchange, symbol, timeframe, limit) -> pd.DataFrame | None`
  - `fetch_positions_safe(exchange) -> dict[str, dict | None] | None`
  - `fetch_balance_safe(exchange) -> dict | None`
  - `create_market_order_safe(exchange, symbol, side, amount) -> dict | None`
  - `fetch_my_trades_safe(exchange, symbol, since_ms) -> list[dict] | None`

- [ ] **Step 1: Write exchange.py**

```python
import ccxt
import pandas as pd
import logging
from datetime import datetime
from config import ACCOUNT_ADDRESS, PRIVATE_KEY, SYMBOLS

logger = logging.getLogger(__name__)


def create_exchange():
    exchange = ccxt.hyperliquid({
        "apiKey": ACCOUNT_ADDRESS,
        "secret": PRIVATE_KEY,
        "options": {"defaultType": "swap"},
    })
    exchange.set_sandbox_mode(True)
    logger.info("Exchange initialized — sandbox mode ON")
    return exchange


def fetch_ohlcv_safe(exchange, symbol, timeframe="15m", limit=60):
    try:
        raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if not raw:
            logger.warning("fetch_ohlcv returned empty for %s", symbol)
            return None
        df = pd.DataFrame(
            raw, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df
    except Exception as e:
        logger.error("fetch_ohlcv failed for %s: %s", symbol, e)
        return None


def fetch_positions_safe(exchange):
    try:
        positions = exchange.fetch_positions(SYMBOLS)
        result = {}
        for sym in SYMBOLS:
            result[sym] = None
        if positions:
            for pos in positions:
                sym = pos.get("symbol", "")
                contracts = float(pos.get("contracts", 0) or 0)
                if contracts != 0:
                    result[sym] = {
                        "side": pos.get("side"),
                        "size": abs(contracts),
                        "entry_price": float(pos.get("entryPrice", 0) or 0),
                        "unrealized_pnl": float(pos.get("unrealizedPnl", 0) or 0),
                        "percentage": float(pos.get("percentage", 0) or 0),
                    }
        return result
    except Exception as e:
        logger.error("fetch_positions failed: %s", e)
        return None


def fetch_balance_safe(exchange):
    try:
        balance = exchange.fetch_balance()
        usdc = balance.get("USDC", {})
        return {"free": float(usdc.get("free", 0) or 0),
                "used": float(usdc.get("used", 0) or 0),
                "total": float(usdc.get("total", 0) or 0)}
    except Exception as e:
        logger.error("fetch_balance failed: %s", e)
        return None


def create_market_order_safe(exchange, symbol, side, amount):
    try:
        order = exchange.create_order(symbol, "market", side, amount)
        logger.info("ORDER | %s %s %.6f @ market | id=%s",
                     side.upper(), symbol, amount, order.get("id", "?"))
        return order
    except Exception as e:
        logger.error("create_order failed %s %s: %s", symbol, side, e)
        return None


def fetch_my_trades_safe(exchange, symbol, since_ms):
    try:
        trades = exchange.fetch_my_trades(symbol, since=since_ms, limit=None)
        return trades if trades else []
    except Exception as e:
        logger.error("fetch_my_trades failed for %s: %s", symbol, e)
        return None
```

- [ ] **Step 2: Commit**

```bash
git add bot_hyperliquid/exchange.py
git commit -m "feat: add CCXT exchange wrappers with safe error handling"
```

---

### Task 3: Indicators module — EMA, ATR, ADX

**Files:**
- Create: `bot_hyperliquid/indicators.py`

**Interfaces:**
- Consumes: `pd.DataFrame` (OHLCV from exchange.py)
- Produces:
  - `compute_all(df: pd.DataFrame) -> dict | None`

- [ ] **Step 1: Write indicators.py**

```python
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


def _compute_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def _compute_atr(df, period=14):
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.ewm(alpha=1.0 / period, adjust=False).mean()
    return atr


def _compute_adx(df, period=14):
    high, low, close = df["high"], df["low"], df["close"]
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    up_move = high - prev_high
    down_move = prev_low - low

    plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move

    atr_smooth = true_range.ewm(alpha=1.0 / period, adjust=False).mean()
    plus_dm_smooth = plus_dm.ewm(alpha=1.0 / period, adjust=False).mean()
    minus_dm_smooth = minus_dm.ewm(alpha=1.0 / period, adjust=False).mean()

    plus_di = 100.0 * (plus_dm_smooth / atr_smooth)
    minus_di = 100.0 * (minus_dm_smooth / atr_smooth)
    plus_di = plus_di.fillna(0)
    minus_di = minus_di.fillna(0)

    denom = plus_di + minus_di
    denom = denom.replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / denom
    dx = dx.fillna(0)

    adx = dx.ewm(alpha=1.0 / period, adjust=False).mean()
    return adx


def compute_all(df):
    if df is None or len(df) < 30:
        logger.warning("Insufficient data for indicators: %s rows",
                        len(df) if df is not None else 0)
        return None
    try:
        ema_fast = _compute_ema(df["close"], 3)
        ema_slow = _compute_ema(df["close"], 9)
        atr = _compute_atr(df, 14)
        adx = _compute_adx(df, 14)

        latest_fast = float(ema_fast.iloc[-1])
        latest_slow = float(ema_slow.iloc[-1])
        prev_fast = float(ema_fast.iloc[-2])
        prev_slow = float(ema_slow.iloc[-2])

        crossover_bull = (prev_fast <= prev_slow) and (latest_fast > latest_slow)
        crossover_bear = (prev_fast >= prev_slow) and (latest_fast < latest_slow)

        return {
            "ema_fast": latest_fast,
            "ema_slow": latest_slow,
            "ema_fast_prev": prev_fast,
            "ema_slow_prev": prev_slow,
            "atr": float(atr.iloc[-1]),
            "adx": float(adx.iloc[-1]),
            "close": float(df["close"].iloc[-1]),
            "crossover_bull": crossover_bull,
            "crossover_bear": crossover_bear,
        }
    except Exception as e:
        logger.error("Indicator computation failed: %s", e)
        return None
```

- [ ] **Step 2: Commit**

```bash
git add bot_hyperliquid/indicators.py
git commit -m "feat: add EMA, ATR, ADX indicator computation"
```

---

### Task 4: Risk manager — position sizing and trade decisions

**Files:**
- Create: `bot_hyperliquid/risk.py`

**Interfaces:**
- Consumes: `config.RISK_PER_TRADE`, `config.ATR_SL_MULTIPLIER`, `config.RISK_REWARD_RATIO`, `config.SAR_ATR_MULTIPLIER`, `config.ADX_THRESHOLD`
- Produces:
  - `calculate_position_size(balance: float, atr: float, price: float) -> float`
  - `evaluate_exits(position: dict | None, current_price: float, indicators: dict) -> str`
  - `evaluate_entry(indicators: dict) -> str | None`

- [ ] **Step 1: Write risk.py**

```python
import logging
from config import (
    RISK_PER_TRADE,
    ATR_SL_MULTIPLIER,
    RISK_REWARD_RATIO,
    SAR_ATR_MULTIPLIER,
    ADX_THRESHOLD,
)

logger = logging.getLogger(__name__)


def calculate_position_size(balance, atr, price):
    if atr <= 0 or price <= 0:
        return 0.0
    risk_amount = balance * RISK_PER_TRADE
    stop_distance = atr * ATR_SL_MULTIPLIER
    if stop_distance <= 0:
        return 0.0
    size = risk_amount / stop_distance
    return size


def evaluate_exits(position, current_price, indicators):
    if position is None:
        return "HOLD"

    side = position["side"]
    entry = position["entry_price"]
    atr = indicators["atr"]
    adx = indicators["adx"]

    if atr <= 0 or entry <= 0:
        return "HOLD"

    sl_distance = atr * ATR_SL_MULTIPLIER
    tp_distance = atr * ATR_SL_MULTIPLIER * RISK_REWARD_RATIO
    sar_distance = atr * SAR_ATR_MULTIPLIER

    if side == "long":
        sl_price = entry - sl_distance
        tp_price = entry + tp_distance
        sar_price = entry - sar_distance

        if current_price <= sl_price:
            logger.info("STOP LOSS triggered for LONG | entry=%.4f sl=%.4f price=%.4f",
                        entry, sl_price, current_price)
            return "STOP_LOSS"
        if current_price >= tp_price:
            logger.info("TAKE PROFIT triggered for LONG | entry=%.4f tp=%.4f price=%.4f",
                        entry, tp_price, current_price)
            return "TAKE_PROFIT"
        if current_price <= sar_price and adx >= ADX_THRESHOLD:
            logger.info("SAR triggered for LONG → SHORT | entry=%.4f sar=%.4f price=%.4f",
                        entry, sar_price, current_price)
            return "SAR_SHORT"

    elif side == "short":
        sl_price = entry + sl_distance
        tp_price = entry - tp_distance
        sar_price = entry + sar_distance

        if current_price >= sl_price:
            logger.info("STOP LOSS triggered for SHORT | entry=%.4f sl=%.4f price=%.4f",
                        entry, sl_price, current_price)
            return "STOP_LOSS"
        if current_price <= tp_price:
            logger.info("TAKE PROFIT triggered for SHORT | entry=%.4f tp=%.4f price=%.4f",
                        entry, tp_price, current_price)
            return "TAKE_PROFIT"
        if current_price >= sar_price and adx >= ADX_THRESHOLD:
            logger.info("SAR triggered for SHORT → LONG | entry=%.4f sar=%.4f price=%.4f",
                        entry, sar_price, current_price)
            return "SAR_LONG"

    return "HOLD"


def evaluate_entry(indicators):
    if indicators is None:
        return None
    if indicators["adx"] < ADX_THRESHOLD:
        return None
    if indicators["crossover_bull"]:
        return "BUY"
    if indicators["crossover_bear"]:
        return "SELL"
    return None
```

- [ ] **Step 2: Commit**

```bash
git add bot_hyperliquid/risk.py
git commit -m "feat: add risk manager with position sizing and SL/TP/SAR logic"
```

---

### Task 5: Telegram reporter — hourly reports and PnL tracking

**Files:**
- Create: `bot_hyperliquid/telegram_reporter.py`

**Interfaces:**
- Consumes: `config.TELEGRAM_TOKEN`, `config.TELEGRAM_CHAT_ID`, `config.SYMBOLS`, `config.PNL_LOOKBACK_DAYS`
- Produces:
  - `send_telegram(message: str) -> bool`
  - `fetch_and_calculate_pnl(exchange, since_ms: int) -> dict[str, float]`
  - `send_hourly_report(exchange, positions: dict, balance: dict, indicators: dict[str, dict]) -> None`

- [ ] **Step 1: Write telegram_reporter.py**

```python
import logging
import requests
from datetime import datetime, timedelta, timezone
from collections import deque
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, SYMBOLS, PNL_LOOKBACK_DAYS

logger = logging.getLogger(__name__)

TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

LONG_ICON = "\U0001F7E2"   # 🟢
SHORT_ICON = "\U0001F534"  # 🔴
NO_POS_ICON = "\u26AA"     # ⚪


def send_telegram(message):
    try:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
        }
        resp = requests.post(TELEGRAM_URL, json=payload, timeout=15)
        if resp.status_code == 200:
            logger.info("Telegram report sent successfully")
            return True
        else:
            logger.error("Telegram API error %s: %s", resp.status_code, resp.text)
            return False
    except Exception as e:
        logger.error("Telegram send failed: %s", e)
        return False


def _fifo_pnl(trades):
    buys = deque()
    realized_pnl = 0.0
    for t in sorted(trades, key=lambda x: x.get("timestamp", 0)):
        side = t.get("side", "")
        amount = float(t.get("amount", 0) or 0)
        price = float(t.get("price", 0) or 0)
        fee = float(t.get("fee", {}).get("cost", 0) or 0)
        if side == "buy":
            buys.append((price, amount))
        elif side == "sell":
            remaining = amount
            while remaining > 0 and buys:
                buy_price, buy_amount = buys.popleft()
                matched = min(remaining, buy_amount)
                realized_pnl += (price - buy_price) * matched
                remaining -= matched
                if buy_amount > matched:
                    buys.appendleft((buy_price, buy_amount - matched))
        realized_pnl -= fee
    return realized_pnl


def fetch_and_calculate_pnl(exchange, since_ms):
    now = datetime.now(timezone.utc)
    windows = {"7d": 7, "15d": 15, "30d": PNL_LOOKBACK_DAYS}
    result = {}
    for key, days in windows.items():
        result[key] = 0.0

    all_trades = []
    for sym in SYMBOLS:
        try:
            trades = exchange.fetch_my_trades(sym, since=since_ms, limit=None)
            if trades:
                all_trades.extend(trades)
        except Exception as e:
            logger.error("fetch_my_trades failed for %s in PnL calc: %s", sym, e)

    if not all_trades:
        return result

    for key, days in windows.items():
        cutoff = int((now - timedelta(days=days)).timestamp() * 1000)
        window_trades = [t for t in all_trades
                         if (t.get("timestamp", 0) or 0) >= cutoff]
        result[key] = _fifo_pnl(window_trades)

    return result


def send_hourly_report(exchange, positions, balance, indicators_dict):
    try:
        pnls = fetch_and_calculate_pnl(
            exchange,
            int((datetime.now(timezone.utc) - timedelta(days=PNL_LOOKBACK_DAYS)).timestamp() * 1000),
        )
    except Exception as e:
        logger.error("PnL calculation failed: %s", e)
        pnls = {"7d": 0.0, "15d": 0.0, "30d": 0.0}

    total_balance = balance.get("total", 0) if balance else 0

    has_any_position = False
    position_lines = ""
    adx_parts = []

    for sym in SYMBOLS:
        pos = positions.get(sym) if positions else None
        ind = indicators_dict.get(sym, {})
        adx_val = ind.get("adx", 0) if ind else 0
        adx_parts.append(f"{sym.split('/')[0]} {adx_val:.1f}")

        if pos:
            has_any_position = True
            icon = LONG_ICON if pos["side"] == "long" else SHORT_ICON
            side_label = "LONG" if pos["side"] == "long" else "SHORT"
            pnl_pct = pos.get("percentage", 0)
            pnl_str = f"+{pnl_pct:.2f}" if pnl_pct >= 0 else f"{pnl_pct:.2f}"
            position_lines += f"{icon} {side_label} en {sym} — *Rendimiento:* {pnl_str}%\n"
        else:
            position_lines += f"{NO_POS_ICON} {sym} — Sin posici\u00f3n\n"

    if not has_any_position:
        position_lines = (
            f"{NO_POS_ICON} Sin posiciones abiertas \\(En Liquidez\\)\n"
        )

    def _format_pnl(val):
        sign = "+" if val >= 0 else "-"
        return f"{sign}${abs(val):.2f}"

    message = (
        "\U0001F4CA *REPORTE DE OPERACIONES*\n\n"
        f"\U0001F4B0 *Balance total:* ${total_balance:.2f} USDC\n\n"
        f"\U0001F4BC *Posiciones abiertas:*\n"
        f"{position_lines}\n"
        f"\U0001F4C8 *PnL de 7 d\u00edas:* {_format_pnl(pnls['7d'])} USDC\n"
        f"\U0001F4CA *PnL de 15 d\u00edas:* {_format_pnl(pnls['15d'])} USDC\n"
        f"\U0001F4C9 *PnL de 30 d\u00edas:* {_format_pnl(pnls['30d'])} USDC\n\n"
        f"\U0001F9ED *ADX:* {' | '.join(adx_parts)}"
    )

    send_telegram(message)
```

- [ ] **Step 2: Commit**

```bash
git add bot_hyperliquid/telegram_reporter.py
git commit -m "feat: add Telegram reporter with hourly PnL and per-symbol ADX"
```

---

### Task 6: Main loop — orchestration

**Files:**
- Create: `bot_hyperliquid/main.py`

**Interfaces:**
- Consumes: all modules above
- Produces: entry point `main()`

- [ ] **Step 1: Write main.py**

```python
import gc
import time
import logging
import traceback
from datetime import datetime, timezone

from config import SYMBOLS, TIMEFRAME, CANDLE_LIMIT, LOOP_INTERVAL_SECONDS
from exchange import (
    create_exchange,
    fetch_ohlcv_safe,
    fetch_positions_safe,
    fetch_balance_safe,
    create_market_order_safe,
)
from indicators import compute_all
from risk import calculate_position_size, evaluate_exits, evaluate_entry
from telegram_reporter import send_hourly_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")


def _close_position(exchange, symbol, position):
    side = position["side"]
    close_side = "sell" if side == "long" else "buy"
    amount = position["size"]
    logger.info("Closing %s %s | size=%.6f", side.upper(), symbol, amount)
    return create_market_order_safe(exchange, symbol, close_side, amount)


def main():
    logger.info("=== Hyperliquid Trading Bot Starting ===")
    exchange = create_exchange()
    last_report_hour = None
    cycle_count = 0

    while True:
        cycle_start = time.time()
        cycle_count += 1

        try:
            # ── 1. Fetch candles + compute indicators per symbol ──
            indicators_dict = {}
            for sym in SYMBOLS:
                df = fetch_ohlcv_safe(exchange, sym, TIMEFRAME, CANDLE_LIMIT)
                indicators_dict[sym] = compute_all(df)
                if df is not None:
                    del df
                gc.collect()

            # ── 2. Fetch positions and balance ──
            positions = fetch_positions_safe(exchange)
            balance = fetch_balance_safe(exchange)

            if positions is None or balance is None:
                logger.warning("Skipping cycle — positions or balance unavailable")
            else:
                # ── 3. Evaluate and execute per symbol ──
                for sym in SYMBOLS:
                    ind = indicators_dict.get(sym)
                    pos = positions.get(sym)
                    if ind is None:
                        continue

                    current_price = ind["close"]
                    atr = ind["atr"]

                    if pos:
                        # Has open position — evaluate exits
                        action = evaluate_exits(pos, current_price, ind)
                        if action == "HOLD":
                            continue

                        if action in ("STOP_LOSS", "TAKE_PROFIT"):
                            _close_position(exchange, sym, pos)

                        elif action == "SAR_SHORT":
                            if _close_position(exchange, sym, pos):
                                size = calculate_position_size(
                                    balance["total"], atr, current_price
                                )
                                if size > 0:
                                    create_market_order_safe(exchange, sym, "sell", size)

                        elif action == "SAR_LONG":
                            if _close_position(exchange, sym, pos):
                                size = calculate_position_size(
                                    balance["total"], atr, current_price
                                )
                                if size > 0:
                                    create_market_order_safe(exchange, sym, "buy", size)

                    else:
                        # No position — evaluate entry
                        entry = evaluate_entry(ind)
                        if entry is None:
                            continue

                        size = calculate_position_size(
                            balance["total"], atr, current_price
                        )
                        if size <= 0:
                            logger.warning("Position size too small for %s: %.6f", sym, size)
                            continue

                        side = "buy" if entry == "BUY" else "sell"
                        create_market_order_safe(exchange, sym, side, size)

                # ── 4. Hourly Telegram report ──
                now_utc = datetime.now(timezone.utc)
                current_hour = now_utc.hour
                if last_report_hour is None or current_hour != last_report_hour:
                    try:
                        send_hourly_report(exchange, positions, balance, indicators_dict)
                    except Exception as e:
                        logger.error("Hourly report generation failed: %s", e)
                    last_report_hour = current_hour
                    gc.collect()

            # ── 5. Memory cleanup ──
            gc.collect()

        except Exception as e:
            logger.error("Cycle %d crashed: %s\n%s", cycle_count, e, traceback.format_exc())

        # ── 6. Sleep until next 15-second mark ──
        elapsed = time.time() - cycle_start
        sleep_time = max(0, LOOP_INTERVAL_SECONDS - elapsed)
        if sleep_time > 0:
            time.sleep(sleep_time)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add bot_hyperliquid/main.py
git commit -m "feat: add main loop — multi-symbol orchestration with hourly Telegram reports"
```

---

### Task 7: Verify — syntax check and import validation

**Files:**
- No changes

- [ ] **Step 1: Install dependencies**

```bash
cd bot_hyperliquid
pip install -r requirements.txt
```

- [ ] **Step 2: Syntax check all modules**

```bash
python -m py_compile config.py && echo "config.py OK"
python -m py_compile exchange.py && echo "exchange.py OK"
python -m py_compile indicators.py && echo "indicators.py OK"
python -m py_compile risk.py && echo "risk.py OK"
python -m py_compile telegram_reporter.py && echo "telegram_reporter.py OK"
python -m py_compile main.py && echo "main.py OK"
```

- [ ] **Step 3: Verify imports resolve**

```bash
python -c "from config import SYMBOLS, ADX_THRESHOLD; print(f'Symbols: {SYMBOLS}, ADX threshold: {ADX_THRESHOLD}')"
python -c "from exchange import create_exchange; print('exchange imports OK')"
python -c "from indicators import compute_all; print('indicators imports OK')"
python -c "from risk import calculate_position_size, evaluate_exits, evaluate_entry; print('risk imports OK')"
python -c "from telegram_reporter import send_telegram, send_hourly_report; print('telegram imports OK')"
```

- [ ] **Step 4: Commit if fixes needed**

```bash
git add -A
git commit -m "fix: resolve any import or syntax issues found during verification"
```

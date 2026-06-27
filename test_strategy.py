import sys
import numpy as np
import pandas as pd
from indicators import compute_all
from risk import calculate_position_size, evaluate_exits, evaluate_entry
from telegram_reporter import _fifo_pnl

PASS = 0
FAIL = 0


def check(label, condition):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}")


def generate_uptrend_candles(n=60):
    np.random.seed(42)
    close = 100 + np.cumsum(np.random.randn(n) * 0.5 + 0.3)
    high = close + np.abs(np.random.randn(n) * 0.3)
    low = close - np.abs(np.random.randn(n) * 0.3)
    open_ = close - np.random.randn(n) * 0.2
    dates = pd.date_range("2026-06-01", periods=n, freq="15min")
    return pd.DataFrame({"timestamp": dates, "open": open_, "high": high, "low": low, "close": close, "volume": np.random.rand(n) * 100})


def generate_downtrend_candles(n=60):
    np.random.seed(99)
    close = 200 - np.cumsum(np.random.randn(n) * 0.5 + 0.3)
    high = close + np.abs(np.random.randn(n) * 0.3)
    low = close - np.abs(np.random.randn(n) * 0.3)
    open_ = close - np.random.randn(n) * 0.2
    dates = pd.date_range("2026-06-01", periods=n, freq="15min")
    return pd.DataFrame({"timestamp": dates, "open": open_, "high": high, "low": low, "close": close, "volume": np.random.rand(n) * 100})


def generate_choppy_candles(n=60):
    np.random.seed(7)
    close = 100 + np.cumsum(np.random.randn(n) * 0.15)
    high = close + np.abs(np.random.randn(n) * 0.3)
    low = close - np.abs(np.random.randn(n) * 0.3)
    open_ = close - np.random.randn(n) * 0.2
    dates = pd.date_range("2026-06-01", periods=n, freq="15min")
    return pd.DataFrame({"timestamp": dates, "open": open_, "high": high, "low": low, "close": close, "volume": np.random.rand(n) * 100})


print("=" * 60)
print("STRATEGY TEST -- Hyperliquid Trading Bot")
print("=" * 60)

# ── 1. Indicators ──
print("\n[1] Indicators on uptrend data")
df_up = generate_uptrend_candles(60)
ind = compute_all(df_up)
check("compute_all returns dict", ind is not None)
check("ema_fast > ema_slow (uptrend)", ind["ema_fast"] > ind["ema_slow"])
check("ADX > 0", ind["adx"] > 0)
check("ATR > 0", ind["atr"] > 0)
check("close present", ind["close"] > 0)

print("\n[2] Crossover detection")
check("crossover_bull is bool", isinstance(ind["crossover_bull"], bool))
check("crossover_bear is bool", isinstance(ind["crossover_bear"], bool))

print("\n[3] Insufficient data guard")
df_short = generate_uptrend_candles(10)
ind_none = compute_all(df_short)
check("returns None for < 30 candles", ind_none is None)
check("returns None for None input", compute_all(None) is None)

# ── 2. Position sizing ──
print("\n[4] Position sizing")
size = calculate_position_size(balance=100.0, atr=2.5)
check("balance=100, atr=2.5 => size=0.2", abs(size - 0.2) < 0.001)
check("atr=0 returns 0", calculate_position_size(100.0, 0.0) == 0.0)

# ── 3. Entry logic ──
print("\n[5] Entry signals")
ind_bull = {**ind, "crossover_bull": True, "crossover_bear": False}
ind_bear = {**ind, "crossover_bull": False, "crossover_bear": True}
ind_low_adx = {**ind, "adx": 15.0, "crossover_bull": True}

check("BUY signal with ADX >= 23 + bull crossover", evaluate_entry(ind_bull) == "BUY")
check("SELL signal with ADX >= 23 + bear crossover", evaluate_entry(ind_bear) == "SELL")
check("None with ADX >= 23 but no crossover", evaluate_entry(ind) is None)
check("None with ADX < 23 even with crossover", evaluate_entry(ind_low_adx) is None)
check("None with None indicators", evaluate_entry(None) is None)

# ── 4. Exit logic ──
print("\n[6] Stop Loss")
pos_long = {"side": "long", "entry_price": 100.0, "size": 0.5}
check("Long SL triggered (price below entry-2*ATR)",
      evaluate_exits(pos_long, 95.0, {"atr": 2.0, "adx": 30.0}) == "STOP_LOSS")
check("Long HOLD (price between SAR and entry, no SL)",
      evaluate_exits(pos_long, 98.0, {"atr": 2.0, "adx": 30.0}) == "HOLD")

pos_short = {"side": "short", "entry_price": 100.0, "size": 0.5}
check("Short SL triggered (price above entry+2*ATR)",
      evaluate_exits(pos_short, 105.0, {"atr": 2.0, "adx": 30.0}) == "STOP_LOSS")

print("\n[7] Take Profit")
check("Long TP triggered (price above entry+6*ATR)",
      evaluate_exits(pos_long, 113.0, {"atr": 2.0, "adx": 30.0}) == "TAKE_PROFIT")
check("Short TP triggered (price below entry-6*ATR)",
      evaluate_exits(pos_short, 87.0, {"atr": 2.0, "adx": 30.0}) == "TAKE_PROFIT")

print("\n[8] SAR (Stop and Reverse)")
check("Long SAR -> SHORT (ADX=30, price below entry-1.2*ATR)",
      evaluate_exits(pos_long, 97.0, {"atr": 2.0, "adx": 30.0}) == "SAR_SHORT")
check("Long SAR blocked (ADX=15, price below entry-1.2*ATR)",
      evaluate_exits(pos_long, 97.0, {"atr": 2.0, "adx": 15.0}) == "HOLD")
check("Short SAR -> LONG (ADX=30, price above entry+1.2*ATR)",
      evaluate_exits(pos_short, 103.0, {"atr": 2.0, "adx": 30.0}) == "SAR_LONG")

print("\n[9] SL takes priority over SAR")
check("SL fires before SAR (Long, price hits SL first)",
      evaluate_exits(pos_long, 93.0, {"atr": 2.0, "adx": 30.0}) == "STOP_LOSS")
check("SL fires before SAR (Short, price hits SL first)",
      evaluate_exits(pos_short, 107.0, {"atr": 2.0, "adx": 30.0}) == "STOP_LOSS")

print("\n[10] HOLD on None position")
check("evaluate_exits returns HOLD for None position",
      evaluate_exits(None, 100.0, {"atr": 2.0, "adx": 30.0}) == "HOLD")

# ── 5. FIFO PnL ──
print("\n[11] FIFO PnL -- long trade")
trades_long = [
    {"timestamp": 1000, "side": "buy",  "amount": 1.0, "price": 100.0, "fee": {"cost": 0.1}},
    {"timestamp": 2000, "side": "sell", "amount": 1.0, "price": 110.0, "fee": {"cost": 0.1}},
]
pnl_long = _fifo_pnl(trades_long)
check("Long PnL: buy@100 sell@110 fee=0.2 => 9.80", abs(pnl_long - 9.80) < 0.01)

print("\n[12] FIFO PnL -- short trade")
trades_short = [
    {"timestamp": 1000, "side": "sell", "amount": 1.0, "price": 110.0, "fee": {"cost": 0.1}},
    {"timestamp": 2000, "side": "buy",  "amount": 1.0, "price": 100.0, "fee": {"cost": 0.1}},
]
pnl_short = _fifo_pnl(trades_short)
check("Short PnL: sell@110 buy@100 fee=0.2 => 9.80", abs(pnl_short - 9.80) < 0.01)

print("\n[13] FIFO PnL -- mixed trades")
trades_mixed = [
    {"timestamp": 1000, "side": "buy",  "amount": 1.0, "price": 100.0, "fee": {"cost": 0.05}},
    {"timestamp": 2000, "side": "sell", "amount": 0.5, "price": 105.0, "fee": {"cost": 0.05}},
    {"timestamp": 3000, "side": "sell", "amount": 0.5, "price": 108.0, "fee": {"cost": 0.05}},
]
pnl_mixed = _fifo_pnl(trades_mixed)
check("Mixed PnL: partial closes => ~6.35", abs(pnl_mixed - 6.35) < 0.05)

print("\n[14] FIFO PnL -- empty trades")
check("Empty trades => 0.0", _fifo_pnl([]) == 0.0)

# ── 6. ADX filter on choppy market ──
print("\n[15] ADX anti-chop filter")
df_choppy = generate_choppy_candles(60)
ind_choppy = compute_all(df_choppy)
adx_val = ind_choppy["adx"]
print(f"   ADX value on choppy data: {adx_val:.2f}")
ind_chop_bull = {**ind_choppy, "crossover_bull": True}
result = evaluate_entry(ind_chop_bull)
check(f"ADX={adx_val:.1f}: entry {'blocked' if result is None else 'ALLOWED'}",
      (adx_val < 23 and result is None) or (adx_val >= 23 and result is not None))

# ── 7. Summary ──
print("\n" + "=" * 60)
total = PASS + FAIL
print(f"RESULTS: {PASS}/{total} passed ({FAIL} failed)")
if FAIL == 0:
    print("ALL TESTS PASSED -- Strategy logic verified")
else:
    print(f"{FAIL} FAILURES -- Review above")
print("=" * 60)
sys.exit(0 if FAIL == 0 else 1)

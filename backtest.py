"""
Backtest simulation: 100 USDC account, real mainnet data, walk-forward.
Reads live OHLCV from Hyperliquid mainnet (public, no auth needed).
Simulates the exact strategy logic from indicators.py + risk.py.
"""
import sys
import time
import numpy as np
import pandas as pd
import ccxt
from datetime import datetime

# Import strategy modules
from indicators import compute_all
from risk import calculate_position_size, evaluate_exits, evaluate_entry

SYMBOLS = ["SOL/USDC", "ETH/USDC", "BTC/USDC"]
TIMEFRAME = "15m"
CANDLE_LIMIT = 500
INITIAL_BALANCE = 100.0
ADX_THRESHOLD = 23.0


def fetch_data():
    ex = ccxt.hyperliquid()
    data = {}
    for sym in SYMBOLS:
        print(f"  Fetching {sym}...")
        raw = ex.fetch_ohlcv(sym, TIMEFRAME, limit=CANDLE_LIMIT)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        data[sym] = df
        time.sleep(1)
    return data


def simulate(data, balance):
    min_len = min(len(data[sym]) for sym in SYMBOLS)
    start_idx = 60  # need warmup for indicators

    trades = []
    positions = {sym: None for sym in SYMBOLS}
    equity_curve = [balance]

    for i in range(start_idx, min_len):
        for sym in SYMBOLS:
            df_slice = data[sym].iloc[:i + 1].copy()
            ind = compute_all(df_slice)
            if ind is None:
                continue

            pos = positions[sym]
            price = ind["close"]

            if pos:
                action = evaluate_exits(pos, price, ind)
                if action == "HOLD":
                    continue

                if action in ("STOP_LOSS", "TAKE_PROFIT"):
                    pnl = (price - pos["entry_price"]) * pos["size"]
                    if pos["side"] == "short":
                        pnl = -pnl
                    balance += pnl
                    trades.append({
                        "symbol": sym, "side": pos["side"], "action": action,
                        "entry": pos["entry_price"], "exit": price,
                        "size": pos["size"], "pnl": pnl,
                        "date": df_slice["timestamp"].iloc[-1]
                    })
                    positions[sym] = None

                elif action in ("SAR_SHORT", "SAR_LONG"):
                    pnl = (price - pos["entry_price"]) * pos["size"]
                    if pos["side"] == "short":
                        pnl = -pnl
                    balance += pnl
                    trades.append({
                        "symbol": sym, "side": pos["side"], "action": "SAR",
                        "entry": pos["entry_price"], "exit": price,
                        "size": pos["size"], "pnl": pnl,
                        "date": df_slice["timestamp"].iloc[-1]
                    })

                    new_side = "short" if action == "SAR_SHORT" else "long"
                    size = calculate_position_size(balance, ind["atr"])
                    if size > 0:
                        positions[sym] = {"side": new_side, "entry_price": price, "size": size}

            else:
                entry = evaluate_entry(ind)
                if entry is None:
                    continue

                size = calculate_position_size(balance, ind["atr"])
                if size <= 0:
                    continue

                side = "long" if entry == "BUY" else "short"
                positions[sym] = {"side": side, "entry_price": price, "size": size}
                trades.append({
                    "symbol": sym, "side": side, "action": "ENTRY",
                    "entry": price, "exit": None,
                    "size": size, "pnl": 0.0,
                    "date": df_slice["timestamp"].iloc[-1]
                })

        # Close any remaining position at last candle for equity calculation
        eq = balance
        for sym in SYMBOLS:
            p = positions[sym]
            if p:
                last_price = data[sym]["close"].iloc[i]
                unrealized = (last_price - p["entry_price"]) * p["size"]
                if p["side"] == "short":
                    unrealized = -unrealized
                eq += unrealized
        equity_curve.append(eq)

    return trades, equity_curve


def report(trades, equity_curve, data):
    print()
    print("=" * 60)
    print("  BACKTEST RESULTS — 100 USDC Account")
    print("=" * 60)

    closed = [t for t in trades if t["pnl"] != 0 or t["action"] == "ENTRY"]
    winners = [t for t in closed if t["pnl"] > 0]
    losers = [t for t in closed if t["pnl"] < 0]

    final_balance = equity_curve[-1]
    pnl_total = final_balance - INITIAL_BALANCE
    pnl_pct = (pnl_total / INITIAL_BALANCE) * 100

    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    win_rate = (len(winners) / len(closed) * 100) if closed else 0
    avg_win = np.mean([t["pnl"] for t in winners]) if winners else 0
    avg_loss = np.mean([t["pnl"] for t in losers]) if losers else 0

    print(f"  Period:         {data[SYMBOLS[0]]['timestamp'].iloc[60]} -> {data[SYMBOLS[0]]['timestamp'].iloc[-1]}")
    print(f"  Initial:        ${INITIAL_BALANCE:.2f} USDC")
    print(f"  Final:          ${final_balance:.2f} USDC")
    print(f"  PnL:            ${pnl_total:+.2f} ({pnl_pct:+.1f}%)")
    print(f"  Max Drawdown:   {max_dd:.1f}%")
    print(f"  Total Trades:   {len(closed)}")
    print(f"  Winners:        {len(winners)} ({win_rate:.0f}%)")
    print(f"  Avg Win:        ${avg_win:+.2f}")
    print(f"  Avg Loss:       ${avg_loss:+.2f}")
    if avg_loss != 0:
        print(f"  Profit Factor:  {abs(sum(t['pnl'] for t in winners) / sum(t['pnl'] for t in losers)):.2f}" if losers else "")

    print()
    print("  Last 10 trades:")
    for t in trades[-10:]:
        icon = "LONG " if t["side"] == "long" else "SHORT"
        pnl_str = f"${t['pnl']:+.2f}" if t["pnl"] != 0 else "OPEN"
        print(f"    {str(t['date'])[:16]} {t['symbol']:>12} {icon} {t['action']:>6} @ {t['entry']:.2f}  {pnl_str}")

    print()
    print("=" * 60)


if __name__ == "__main__":
    print("Hyperliquid Strategy Backtest — 100 USDC")
    print("=" * 60)
    print()
    print("[1/2] Fetching real mainnet data...")
    data = fetch_data()
    print(f"  Got {min(len(d) for d in data.values())} candles per symbol")
    print()
    print("[2/2] Running walk-forward simulation...")
    trades, equity = simulate(data, INITIAL_BALANCE)
    report(trades, equity, data)

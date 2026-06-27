"""
Multi-period backtest: Binance 15m data, SOL/ETH/BTC.
Pre-computes indicators once (vectorized), then runs fast walk-forward.
"""
import time, sys
import numpy as np
import pandas as pd
import ccxt
from datetime import datetime, timedelta, timezone
from indicators import _compute_ema, _compute_atr, _compute_adx
from risk import calculate_position_size
from config import ADX_THRESHOLD, ATR_SL_MULTIPLIER, RISK_REWARD_RATIO, SAR_ATR_MULTIPLIER, EMA_FAST, EMA_SLOW, ATR_PERIOD, ADX_PERIOD

SYMBOLS = ["SOL/USDT", "ETH/USDT", "BTC/USDT"]
INITIAL_BALANCE = 100.0
WARMUP = 60

def fetch_all(exchange, symbol, since_ms):
    rows, cur = [], since_ms
    while True:
        r = exchange.fetch_ohlcv(symbol, "15m", since=cur, limit=1000)
        if not r: break
        rows.extend(r)
        if len(r) < 1000: break
        cur = r[-1][0] + 1; time.sleep(0.3)
    if not rows: return None
    df = pd.DataFrame(rows, columns=["ts","o","h","l","c","v"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    return df

def precompute_indicators(df):
    """Compute all indicators once, return DataFrame with indicator columns."""
    close = df["c"]
    high, low = df["h"], df["l"]
    ema_f = _compute_ema(close, EMA_FAST)
    ema_s = _compute_ema(close, EMA_SLOW)
    atr = _compute_atr(df.rename(columns={"c":"close","h":"high","l":"low","o":"open","v":"volume"}), ATR_PERIOD)
    adx = _compute_adx(df.rename(columns={"c":"close","h":"high","l":"low","o":"open","v":"volume"}), ADX_PERIOD)
    df["ema_f"] = ema_f
    df["ema_s"] = ema_s
    df["atr"] = atr
    df["adx"] = adx
    # crossover
    df["ema_f_prev"] = ema_f.shift(1)
    df["ema_s_prev"] = ema_s.shift(1)
    df["bull"] = (df["ema_f_prev"] <= df["ema_s_prev"]) & (df["ema_f"] > df["ema_s"])
    df["bear"] = (df["ema_f_prev"] >= df["ema_s_prev"]) & (df["ema_f"] < df["ema_s"])
    return df

def evaluate_entry_fast(row):
    if row["adx"] < ADX_THRESHOLD: return None
    if row["bull"]: return "BUY"
    if row["bear"]: return "SELL"
    return None

def evaluate_exits_fast(pos, price, atr_val, adx_val):
    if pos is None: return "HOLD"
    side, entry = pos["side"], pos["entry_price"]
    if atr_val <= 0 or entry <= 0: return "HOLD"
    sd = atr_val * ATR_SL_MULTIPLIER
    td = atr_val * ATR_SL_MULTIPLIER * RISK_REWARD_RATIO
    sad = atr_val * SAR_ATR_MULTIPLIER
    if side == "long":
        if price <= entry - sd: return "STOP_LOSS"
        if price >= entry + td: return "TAKE_PROFIT"
        if price <= entry - sad and adx_val >= ADX_THRESHOLD: return "SAR_SHORT"
    else:
        if price >= entry + sd: return "STOP_LOSS"
        if price <= entry - td: return "TAKE_PROFIT"
        if price >= entry + sad and adx_val >= ADX_THRESHOLD: return "SAR_LONG"
    return "HOLD"

def simulate(data):
    min_len = min(len(d) for d in data.values())
    balance = INITIAL_BALANCE
    positions = {s: None for s in SYMBOLS}
    trades = []
    equity = [balance]
    dates = [data[SYMBOLS[0]]["ts"].iloc[WARMUP-1]]

    for i in range(WARMUP, min_len):
        for sym in SYMBOLS:
            row = data[sym].iloc[i]
            price = row["c"]
            atr_v = row["atr"]
            adx_v = row["adx"]
            pos = positions[sym]

            if pos:
                action = evaluate_exits_fast(pos, price, atr_v, adx_v)
                if action == "HOLD": continue
                pnl = (price - pos["entry_price"]) * pos["size"]
                if pos["side"] == "short": pnl = -pnl
                balance += pnl
                trades.append({"s": sym, "side": pos["side"], "pnl": pnl, "date": row["ts"]})
                positions[sym] = None
                if action in ("SAR_SHORT","SAR_LONG"):
                    ns = "short" if action=="SAR_SHORT" else "long"
                    sz = calculate_position_size(balance, atr_v)
                    if sz > 0:
                        positions[sym] = {"side": ns, "entry_price": price, "size": sz}
            else:
                entry = evaluate_entry_fast(row)
                if entry is None: continue
                sz = calculate_position_size(balance, atr_v)
                if sz <= 0: continue
                side = "long" if entry=="BUY" else "short"
                positions[sym] = {"side": side, "entry_price": price, "size": sz}

        eq = balance
        for sym in SYMBOLS:
            p = positions[sym]
            if p:
                lp = data[sym]["c"].iloc[i]
                u = (lp - p["entry_price"]) * p["size"]
                if p["side"] == "short": u = -u
                eq += u
        equity.append(eq)
        dates.append(data[SYMBOLS[0]]["ts"].iloc[i])

    return trades, equity, dates

if __name__ == "__main__":
    print("=" * 70)
    print("  MULTI-PERIOD BACKTEST — 100 USDC")
    print("  SOL/ETH/BTC (Binance 15m) | EMA3/9+ADX23+ATR+SAR")
    print("=" * 70)
    ex = ccxt.binance()
    max_d = 3*365+60
    since_ms = int((datetime.now(timezone.utc)-timedelta(days=max_d)).timestamp()*1000)
    print()
    print("[1/4] Fetching data (up to 3y)...")
    data = {}
    for sym in SYMBOLS:
        print(f"  {sym}...", end=" ", flush=True)
        data[sym] = fetch_all(ex, sym, since_ms)
        print(f"{len(data[sym])} candles" if data[sym] is not None else "FAIL")
    mc = min(len(d) for d in data.values()); sd = data[SYMBOLS[0]]["ts"].iloc[0]; ed = data[SYMBOLS[0]]["ts"].iloc[-1]
    ad = (ed-sd).days
    print(f"  Range: {sd} -> {ed}  ({ad}d, {mc}c)")
    print()
    print("[2/4] Pre-computing indicators (vectorized)...")
    t0=time.time()
    for sym in SYMBOLS:
        data[sym] = precompute_indicators(data[sym])
    print(f"  Done in {time.time()-t0:.1f}s")
    print()
    print("[3/4] Walk-forward simulation...")
    t0=time.time()
    trades, equity, dates = simulate(data)
    print(f"  {len(trades)} trades in {time.time()-t0:.1f}s")
    print()
    print("[4/4] Period results:")
    periods = [("7d",7),("15d",15),("30d",30),("90d",90),("180d",180),("1y",365),("3y",1095)]
    end_dt = dates[-1].to_pydatetime()
    print(f"  {'Period':<8} {'PnL':>10} {'%':>8} {'Trades':>7} {'Win%':>7} {'PF':>6} {'MaxDD':>7}")
    print(f"  {'-'*8} {'-'*10} {'-'*8} {'-'*7} {'-'*7} {'-'*6} {'-'*7}")
    for label, days in periods:
        if days > ad: continue
        cutoff = end_dt - timedelta(days=days)
        idx = 0
        for j,d in enumerate(dates):
            if d.to_pydatetime() >= cutoff: idx=j; break
        eq_s = equity[idx:]
        peak = eq_s[0]; mdd = 0.0
        for v in eq_s:
            peak = max(peak,v)
            dd = (peak-v)/peak*100 if peak>0 else 0
            mdd = max(mdd,dd)
        start_b = INITIAL_BALANCE if idx==0 else equity[max(0,idx-1)]
        t = [x for x in trades if x["date"].to_pydatetime()>=cutoff]
        cl = [x for x in t if x["pnl"]!=0]
        w = [x for x in cl if x["pnl"]>0]; l_ = [x for x in cl if x["pnl"]<0]
        pnl = equity[-1]-start_b; pct = (pnl/start_b*100) if start_b>0 else 0
        n = len(cl); wr = len(w)/n*100 if n else 0
        pf = sum(x["pnl"] for x in w)/abs(sum(x["pnl"] for x in l_)) if l_ else float("inf")
        pf_s = f"{pf:.2f}" if pf!=float("inf") else "inf"
        print(f"  {label:<8} ${pnl:>+8.2f} {pct:>+7.1f}% {n:>7} {wr:>6.0f}% {pf_s:>6} {mdd:>6.1f}%")
    print()
    print(f"  Data: {ad} days ({mc} candles)")
    sign = "+" if equity[-1] >= INITIAL_BALANCE else "-"
    print(f"  Start: ${INITIAL_BALANCE:.2f}  End: ${equity[-1]:.2f}  ({sign}${abs(equity[-1]-INITIAL_BALANCE):.2f})")
    print("=" * 70)

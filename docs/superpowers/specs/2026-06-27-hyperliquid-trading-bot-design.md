# Hyperliquid Algorithmic Trading Bot — Design Spec

**Date:** 2026-06-27
**Environment:** WSL/Debian 13, 1 CPU core, 2 GB RAM
**Exchange:** Hyperliquid Testnet (sandbox)
**Language:** Python 3 + CCXT

---

## 1. Strategy Specification

| Parameter | Value |
|-----------|-------|
| Symbols | SOL/USDC, ETH/USDC, BTC/USDC (3 linear perpetuals) |
| Timeframe | 15 minutes |
| Loop interval | 15 seconds |
| Risk per trade | 1% of account balance **per symbol** (up to 3% total if all 3 have positions) |
| Candle fetch limit | 60 per symbol (maximum) |

### Indicators (same params for all 3 symbols)
| Indicator | Period | Role |
|-----------|--------|------|
| EMA Fast | 3 | Crossover entry signal |
| EMA Slow | 9 | Crossover entry signal |
| ATR | 14 | Stop loss distance, position sizing, SAR threshold |
| ADX | 14 | Trend filter (threshold: 23.0) |

### Entry Logic (per symbol, independently)
- Long: EMA 3 crosses ABOVE EMA 9 AND ADX >= 23
- Short: EMA 3 crosses BELOW EMA 9 AND ADX >= 23
- If ADX < 23: ALL new entries for that symbol blocked (anti-chop filter)

### Exit & Risk Management (per symbol)
- **Stop Loss:** Entry price +/- (2.0 × ATR). Market close.
- **Take Profit:** Entry price +/- (6.0 × ATR) [R:R = 3.0, SL = 2×ATR]. Market close.
- **SAR (Stop and Reverse):** If price crosses Entry price +/- (1.2 × ATR):
  - Close current position via market order
  - Immediately open opposite position
  - ONLY if ADX >= 23 at time of signal
  - If ADX < 23: SAR ignored, position stays (protected by normal SL)

### Position Sizing (per symbol)
```
risk_amount = balance × 0.01
stop_distance = ATR × 2.0
position_size = risk_amount / stop_distance  (rounded down to exchange precision)
```

---

## 2. Architecture

### File Structure
```
bot_hyperliquid/
├── config.py              # All constants: credentials, strategy params
├── exchange.py            # CCXT Hyperliquid setup + safe API wrappers
├── indicators.py          # EMA, ATR, ADX computation (pandas + numpy)
├── risk.py                # Position sizing, SL/TP/SAR evaluation, action decisions
├── telegram_reporter.py   # Hourly Telegram report + PnL calculation (FIFO)
├── main.py                # Main loop, orchestration
└── requirements.txt       # ccxt, pandas, numpy, requests
```

### Module Responsibilities

#### `config.py`
- `ACCOUNT_ADDRESS`, `PRIVATE_KEY`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`
- All strategy parameters (EMA periods, ATR params, ADX threshold, risk %, loop interval, candle limit)
- No logic, pure constants

#### `exchange.py`
- `create_exchange()`: Initialize `ccxt.hyperliquid()`, set auth, `set_sandbox_mode(True)`
- `fetch_ohlcv_safe(exchange, symbol, timeframe, limit)`: Returns DataFrame or None
- `fetch_positions_safe(exchange, symbols)`: Returns positions list or None
- `fetch_balance_safe(exchange)`: Returns balance dict or None
- `create_market_order_safe(exchange, symbol, side, amount)`: Returns order or None
- `fetch_my_trades_safe(exchange, symbol, since)`: Returns trades list or None
- Every function wrapped in try-except, logs errors, never raises

#### `indicators.py`
- `compute_all(df)`: Accepts OHLCV DataFrame, returns dict:
  ```python
  {
      'ema_fast': float,      # latest EMA-3
      'ema_slow': float,      # latest EMA-9
      'ema_fast_prev': float, # EMA-3 from previous candle
      'ema_slow_prev': float, # EMA-9 from previous candle
      'atr': float,           # latest ATR-14
      'adx': float,           # latest ADX-14
      'crossover_bull': bool, # EMA-3 crossed above EMA-9 this candle
      'crossover_bear': bool, # EMA-3 crossed below EMA-9 this candle
  }
  ```

#### `risk.py`
- `calculate_position_size(balance, atr, price)` → `float` (amount)
- `evaluate_exits(position, current_price, indicators)` → `str` action:
  - `'HOLD'`, `'STOP_LOSS'`, `'TAKE_PROFIT'`, `'SAR_LONG'`, `'SAR_SHORT'`
- `evaluate_entry(indicators, adx)` → `str | None`: `'BUY'`, `'SELL'`, `None`
- Uses ADX threshold (23.0) consistently for both entry and SAR

#### `telegram_reporter.py`
- `send_telegram(token, chat_id, message)`: POST to Telegram API, try-except
- `calculate_pnl_periods(trades)`: FIFO PnL for 7/15/30 day windows
- `format_report(...)`: Renders exact Markdown template specified in requirements
- `send_hourly_report(exchange, ...)`: Orchestrates full report cycle

#### `main.py`
- `main()`: Entry point with global try-except
- Loop: `time.sleep(15)` between cycles
- Per cycle:
  1. Fetch OHLCV → compute indicators → `del df; gc.collect()`
  2. Fetch positions + balance
  3. If position open: evaluate exits (SL → TP → SAR)
  4. If no position: evaluate entry
  5. Execute action (market order)
  6. Check if hour changed → send Telegram report
  7. `gc.collect()`

---

## 3. Data Flow (per 15-second cycle)

```
FOR EACH symbol in [SOL/USDC, ETH/USDC, BTC/USDC]:
  fetch_ohlcv(symbol, 60 candles)
    → pandas DataFrame
    → compute_all(df)
    → store indicators dict for this symbol
    → del df; gc.collect()

fetch_positions(all 3 symbols)
  → dict: {symbol: position_data or None}

fetch_balance()
  → free USDC balance (shared across all symbols)

FOR EACH symbol:
  position = positions[symbol]
  IF position exists:
    evaluate_exits(position, close[-1], indicators[symbol])
    → action string
    IF action != 'HOLD':
      create_market_order(action)  # close or close+reverse
  ELSE (no position for this symbol):
    IF indicators[symbol]['adx'] >= 23.0:
      IF indicators[symbol]['crossover_bull']:
        size = calculate_position_size(balance, atr, close)
        create_market_order('buy', size)
      ELIF indicators[symbol]['crossover_bear']:
        size = calculate_position_size(balance, atr, close)
        create_market_order('sell', size)

IF datetime.utcnow().hour != last_report_hour:
  FOR EACH symbol: trades += fetch_my_trades(symbol, since=30_days_ago)
  pnls = calculate_pnl_periods(all_trades)
  send_hourly_report(...)  # includes per-symbol position lines + individual ADX
  last_report_hour = current_hour
  del trades; gc.collect()
```

---

## 4. Error Handling

| Layer | Strategy |
|-------|----------|
| API calls (exchange.py) | Every call in try-except, returns None on failure, logs warning |
| Main loop (main.py) | Global try-except around full cycle, logs traceback, continues |
| Telegram | Isolated try-except, failure logged but never blocks trading |
| fetch_my_trades | Failure → PnL values show "N/D", bot continues |
| Order placement | Failure → logged, position state re-evaluated next cycle |

---

## 5. Memory Management (2 GB RAM constraint)

- Candle limit: 60 rows per symbol (strict). 3 DataFrames × ~5 KB = ~15 KB total.
- `del df; gc.collect()` after indicator computation for each symbol
- `del df; gc.collect()` after Telegram report generation
- 3 `fetch_my_trades` calls per hour (one per symbol), results aggregated, deleted after use
- No global accumulators, no growing caches
- pandas import is module-level (loaded once, not re-imported)

---

## 6. Dependencies

```
ccxt>=4.0.0
pandas>=2.0.0
numpy>=1.24.0
requests>=2.31.0
```

---

## 7. Telegram Report Format (exact)

```markdown
📊 *REPORTE DE OPERACIONES*

💰 *Balance total:* $1234.56 USDC

💼 *Posiciones abiertas:*
🟢 LONG en SOL/USDC:USDC — *Rendimiento:* +2.50%
🔴 SHORT en ETH/USDC:USDC — *Rendimiento:* -1.20%
⚪ BTC/USDC:USDC — Sin posición
(O si ninguna posición: ⚪ Sin posiciones abiertas \(En Liquidez\))

📈 *PnL de 7 días:* +$50.00 USDC
📊 *PnL de 15 días:* +$120.00 USDC
📉 *PnL de 30 días:* +$200.00 USDC

🧭 *ADX:* SOL 28.5 | ETH 19.2 | BTC 32.1
```

---

## 8. Symbols and Icons

- Long position: 🟢
- Short position: 🔴
- No position: ⚪
- PnL positive: `+$` prefix
- PnL negative: `-$` prefix

# Hyperliquid Trading Bot — Handoff

## Overview

Algorithmic trading bot for Hyperliquid Testnet. Trades **SOL/USDC, ETH/USDC, BTC/USDC** linear perpetuals on 15-minute candles with EMA 3/9 crossover + ADX trend filter + ATR-based risk management + Stop-and-Reverse (SAR). Sends hourly Telegram reports with Markdown formatting.

## Quick Start

**One-script install (Ubuntu 26.04 LTS):**
```bash
curl -fsSL https://raw.githubusercontent.com/juancito8812/hyperliquid-tradingbot/master/install.sh | bash
# Edit .env, then: sudo systemctl start hyperliquid-bot
```

**Manual:**
```bash
chmod +x run.sh && cp .env.example .env && nano .env && ./run.sh
```

**Manual:**
```bash
cd bot_hyperliquid
pip install -r requirements.txt
export HL_ACCOUNT_ADDRESS="0xYOUR_WALLET"
export HL_PRIVATE_KEY="0xYOUR_PRIVATE_KEY"
export TELEGRAM_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"
export LOG_FILE="./logs/bot.log"  # optional, enables file logging with rotation
python main.py
```

Runs indefinitely — Ctrl+C to stop.

## Ubuntu 26.04 LTS Deployment

`install.sh` does everything: clone, venv, deps, systemd unit, auto-start on boot.
```bash
curl -fsSL https://raw.githubusercontent.com/juancito8812/hyperliquid-tradingbot/master/install.sh | bash -s /opt/hyperliquid-bot
# Or: bash install.sh /custom/path
```

**Manual install:**
```bash
git clone https://github.com/juancito8812/hyperliquid-tradingbot.git /opt/hyperliquid-bot
cd /opt/hyperliquid-bot
cp .env.example .env && nano .env
chmod +x run.sh && ./run.sh           # test run
sudo cp hyperliquid-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hyperliquid-bot
sudo journalctl -u hyperliquid-bot -f # tail logs
```
- Systemd: auto-restart, MemoryMax=1.5G, CPUQuota=80%, hardened sandbox
- File logging: RotatingFileHandler (10 MB x 7) when LOG_FILE env var set

## Strategy Summary

| Parameter | Value |
|-----------|-------|
| Risk per trade | 1% per symbol |
| Stop Loss | 2.0 × ATR(14) |
| Take Profit | 6.0 × ATR(14) [R:R = 3:1] |
| SAR threshold | 1.2 × ATR(14) |
| ADX filter | Must be ≥ 23 for entries and SAR |

**Entry:** EMA(3) crosses EMA(9) + ADX ≥ 23  
**Exit:** SL hit → market close | TP hit → market close  
**SAR:** Price crosses entry ± 1.2×ATR → close + reverse (if ADX ≥ 23)

## File Structure

```
bot_hyperliquid/
├── config.py               # All constants, credentials from env vars
├── exchange.py             # CCXT Hyperliquid sandbox + safe API wrappers
├── indicators.py           # EMA, ATR (Wilder), ADX (Wilder) — pandas/numpy
├── risk.py                 # Position sizing, SL/TP/SAR exit evaluation
├── telegram_reporter.py    # Hourly Markdown reports, FIFO PnL (long + short)
├── main.py                 # 15-second loop, orchestration, gc.collect(), file logging
├── backtest.py             # Multi-period backtest (Binance 15m, vectorized)
├── test_strategy.py        # Unit tests — 32 checks (indicators, sizing, exits, FIFO)
├── requirements.txt        # ccxt, pandas, numpy, requests
├── run.sh                  # Bootstrap: venv + deps + .env + launch
├── install.sh              # One-script installer (interactive, systemd)
├── hyperliquid-bot.service # systemd unit (Ubuntu 26.04 LTS)
├── .env.example            # Environment variable template
└── .gitignore
```

## Key Design Decisions

- **No limit orders on exchange** — SL/TP/SAR evaluated each cycle (15s) against current price, closed via market orders.
- **Memory management** — `del df; gc.collect()` after every symbol's indicator calc and after hourly report. 60 candle limit per symbol.
- **Error isolation** — Every CCXT call wrapped in try-except (exchange.py), global try-except around each cycle (main.py), Telegram failures never block trading.
- **FIFO PnL** — Two-deque system handles both long and short trade matching for accurate realized PnL across 7/15/30 day windows.
- **Indicator fallback** — If OHLCV fetch fails but position exists, fetches bare ticker price as fallback for exit evaluation.
- **Config constants flow** — `indicators.py` imports `EMA_FAST`, `EMA_SLOW`, `ATR_PERIOD`, `ADX_PERIOD` from config so strategy params stay centralized.

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `HL_ACCOUNT_ADDRESS` | Hyperliquid wallet address (0x...) |
| `HL_PRIVATE_KEY` | Wallet private key |
| `TELEGRAM_TOKEN` | Telegram Bot API token |
| `TELEGRAM_CHAT_ID` | Target chat/group ID |
| `LOG_FILE` | Path for file logging with rotation (optional, stdout if unset) |

## Requirements

- Python 3.12+ (Ubuntu 26.04 LTS)
- 1 CPU core, 2 GB RAM minimum
- `ccxt>=4.0.0`, `pandas>=2.0.0`, `numpy>=1.24.0`, `requests>=2.31.0`

## Repo

https://github.com/juancito8812/hyperliquid-tradingbot

## Backtest Results (Binance 15m, 100 USDC, 3.16 years)

| Period | PnL | % | Trades | Win% | PF | MaxDD |
|--------|-----|---|--------|------|-----|-------|
| 7 days | +$159.69 | +39.2% | 55 | 29% | 1.79 | 11.4% |
| 15 days | +$121.89 | +27.4% | 112 | 24% | 1.25 | 33.0% |
| 30 days | +$115.45 | +25.5% | 221 | 20% | 1.11 | 33.0% |
| 90 days | -$294.94 | -34.2% | 698 | 19% | 0.90 | 58.7% |
| 180 days | -$294.71 | -34.2% | 1,328 | 21% | 0.95 | 66.6% |
| 1 year | +$80.81 | +16.6% | 2,633 | 22% | 1.01 | 66.6% |
| 3 years | +$217.43 | +62.1% | 7,668 | 22% | 1.01 | 82.7% |

**Final balance: $317.43** (from $100). Run with `python backtest.py`.
Strategy profitable long-term (3y: +62.1%) with trend-following profile:
low win rate (~22%), profit factor >1, but large drawdowns (83% max).

## Design Docs

- Spec: `docs/superpowers/specs/2026-06-27-hyperliquid-trading-bot-design.md`
- Plan: `docs/superpowers/plans/2026-06-27-hyperliquid-trading-bot.md`

# Hyperliquid Trading Bot — Handoff

## Overview

Algorithmic trading bot for Hyperliquid Testnet. Trades **SOL/USDC, ETH/USDC, BTC/USDC** linear perpetuals on 15-minute candles with EMA 3/9 crossover + ADX trend filter + ATR-based risk management + Stop-and-Reverse (SAR). Sends hourly Telegram reports with Markdown formatting.

## Quick Start

**One-liner (Ubuntu 26.04 LTS):**
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

## Ubuntu 26.04 LTS Deployment (systemd)

```bash
git clone https://github.com/juancito8812/hyperliquid-tradingbot.git /opt/hyperliquid-bot
cd /opt/hyperliquid-bot
cp .env.example .env && nano .env    # fill credentials
chmod +x run.sh && ./run.sh           # bootstrap venv + deps + test run
sudo cp hyperliquid-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hyperliquid-bot
sudo systemctl status hyperliquid-bot  # verify running
sudo journalctl -u hyperliquid-bot -f # tail logs
```

**Service features:**
- Auto-restart on crash (RestartSec=15s)
- Memory cap: 1.5 GB (MemoryMax)
- CPU cap: 80% of one core (CPUQuota)
- Hardened: no new privileges, read-only filesystem except logs
- File logging with rotation: 10 MB × 7 backups (`LOG_FILE` env var)

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
├── requirements.txt        # ccxt, pandas, numpy, requests
├── run.sh                  # Bootstrap: venv + deps + .env + launch
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

## Design Docs

- Spec: `docs/superpowers/specs/2026-06-27-hyperliquid-trading-bot-design.md`
- Plan: `docs/superpowers/plans/2026-06-27-hyperliquid-trading-bot.md`

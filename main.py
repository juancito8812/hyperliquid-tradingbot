import gc
import os
import time
import logging
import traceback
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone

from config import SYMBOLS, TIMEFRAME, CANDLE_LIMIT, LOOP_INTERVAL_SECONDS
from exchange import (
    create_exchange,
    fetch_ohlcv_safe,
    fetch_positions_safe,
    fetch_balance_safe,
    create_market_order_safe,
    fetch_ticker_safe,
)
from indicators import compute_all
from risk import calculate_position_size, evaluate_exits, evaluate_entry
from telegram_reporter import send_hourly_report

_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_datefmt = "%Y-%m-%d %H:%M:%S"

log_file = os.environ.get("LOG_FILE", "")
if log_file:
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=7)
    handler.setFormatter(logging.Formatter(_format, _datefmt))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
else:
    logging.basicConfig(level=logging.INFO, format=_format, datefmt=_datefmt)

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
                        if pos:
                            logger.warning("Indicators unavailable for %s, using solo price check", sym)
                            price = fetch_ticker_safe(exchange, sym)
                            if price is None:
                                continue
                            ind = {"close": price, "atr": 0.0, "adx": 0.0}
                        else:
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
                                    balance["total"], atr
                                )
                                if size > 0:
                                    create_market_order_safe(exchange, sym, "sell", size)

                        elif action == "SAR_LONG":
                            if _close_position(exchange, sym, pos):
                                size = calculate_position_size(
                                    balance["total"], atr
                                )
                                if size > 0:
                                    create_market_order_safe(exchange, sym, "buy", size)

                    else:
                        # No position — evaluate entry
                        entry = evaluate_entry(ind)
                        if entry is None:
                            continue

                        size = calculate_position_size(
                            balance["total"], atr
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

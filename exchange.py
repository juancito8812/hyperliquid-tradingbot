import ccxt
import pandas as pd
import logging
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


def fetch_ticker_safe(exchange, symbol):
    try:
        ticker = exchange.fetch_ticker(symbol)
        return float(ticker.get("last", 0) or 0)
    except Exception as e:
        logger.error("fetch_ticker failed for %s: %s", symbol, e)
        return None

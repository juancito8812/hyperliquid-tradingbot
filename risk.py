import logging
from config import (
    RISK_PER_TRADE,
    ATR_SL_MULTIPLIER,
    RISK_REWARD_RATIO,
    SAR_ATR_MULTIPLIER,
    ADX_THRESHOLD,
)

logger = logging.getLogger(__name__)


def calculate_position_size(balance, atr):
    if atr <= 0:
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

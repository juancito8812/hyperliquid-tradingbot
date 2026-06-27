import pandas as pd
import numpy as np
import logging
from config import EMA_FAST, EMA_SLOW, ATR_PERIOD, ADX_PERIOD

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
        ema_fast = _compute_ema(df["close"], EMA_FAST)
        ema_slow = _compute_ema(df["close"], EMA_SLOW)
        atr = _compute_atr(df, ATR_PERIOD)
        adx = _compute_adx(df, ADX_PERIOD)

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

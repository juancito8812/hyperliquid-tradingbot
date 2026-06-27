import logging
import requests
from datetime import datetime, timedelta, timezone
from collections import deque
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, SYMBOLS, PNL_LOOKBACK_DAYS
from exchange import fetch_my_trades_safe

logger = logging.getLogger(__name__)

TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

LONG_ICON = "\U0001F7E2"   # 🟢
SHORT_ICON = "\U0001F534"  # 🔴
NO_POS_ICON = "\u26AA"     # ⚪


def send_telegram(message):
    try:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
        }
        resp = requests.post(TELEGRAM_URL, json=payload, timeout=15)
        if resp.status_code == 200:
            logger.info("Telegram report sent successfully")
            return True
        else:
            logger.error("Telegram API error %s: %s", resp.status_code, resp.text)
            return False
    except Exception as e:
        logger.error("Telegram send failed: %s", e)
        return False


def _fifo_pnl(trades):
    long_entries = deque()
    short_entries = deque()
    realized_pnl = 0.0

    for t in sorted(trades, key=lambda x: x.get("timestamp", 0)):
        side = t.get("side", "")
        amount = float(t.get("amount", 0) or 0)
        price = float(t.get("price", 0) or 0)
        fee = float(t.get("fee", {}).get("cost", 0) or 0)

        if side == "buy":
            remaining = amount
            while remaining > 0 and short_entries:
                entry_price, entry_amount = short_entries.popleft()
                matched = min(remaining, entry_amount)
                realized_pnl += (entry_price - price) * matched
                remaining -= matched
                if entry_amount > matched:
                    short_entries.appendleft((entry_price, entry_amount - matched))
            if remaining > 0:
                long_entries.append((price, remaining))
        elif side == "sell":
            remaining = amount
            while remaining > 0 and long_entries:
                entry_price, entry_amount = long_entries.popleft()
                matched = min(remaining, entry_amount)
                realized_pnl += (price - entry_price) * matched
                remaining -= matched
                if entry_amount > matched:
                    long_entries.appendleft((entry_price, entry_amount - matched))
            if remaining > 0:
                short_entries.append((price, remaining))
        realized_pnl -= fee

    return realized_pnl


def fetch_and_calculate_pnl(exchange, since_ms):
    now = datetime.now(timezone.utc)
    windows = {"7d": 7, "15d": 15, "30d": PNL_LOOKBACK_DAYS}
    result = {}
    for key, days in windows.items():
        result[key] = 0.0

    all_trades = []
    for sym in SYMBOLS:
        try:
            trades = fetch_my_trades_safe(exchange, sym, since_ms)
            if trades:
                all_trades.extend(trades)
        except Exception as e:
            logger.error("fetch_my_trades failed for %s in PnL calc: %s", sym, e)

    if not all_trades:
        return result

    for key, days in windows.items():
        cutoff = int((now - timedelta(days=days)).timestamp() * 1000)
        window_trades = [t for t in all_trades
                         if (t.get("timestamp", 0) or 0) >= cutoff]
        result[key] = _fifo_pnl(window_trades)

    return result


def send_hourly_report(exchange, positions, balance, indicators_dict):
    try:
        pnls = fetch_and_calculate_pnl(
            exchange,
            int((datetime.now(timezone.utc) - timedelta(days=PNL_LOOKBACK_DAYS)).timestamp() * 1000),
        )
    except Exception as e:
        logger.error("PnL calculation failed: %s", e)
        pnls = {"7d": 0.0, "15d": 0.0, "30d": 0.0}

    total_balance = balance.get("total", 0) if balance else 0

    has_any_position = False
    position_lines = ""
    adx_parts = []

    for sym in SYMBOLS:
        pos = positions.get(sym) if positions else None
        ind = indicators_dict.get(sym, {})
        adx_val = ind.get("adx", 0) if ind else 0
        adx_parts.append(f"{sym.split('/')[0]} {adx_val:.1f}")

        if pos:
            has_any_position = True
            icon = LONG_ICON if pos["side"] == "long" else SHORT_ICON
            side_label = "LONG" if pos["side"] == "long" else "SHORT"
            pnl_pct = pos.get("percentage", 0)
            pnl_str = f"+{pnl_pct:.2f}" if pnl_pct >= 0 else f"{pnl_pct:.2f}"
            position_lines += f"{icon} {side_label} en {sym} — *Rendimiento:* {pnl_str}%\n"
        else:
            position_lines += f"{NO_POS_ICON} {sym} — Sin posici\u00f3n\n"

    if not has_any_position:
        position_lines = (
            f"{NO_POS_ICON} Sin posiciones abiertas \\(En Liquidez\\)\n"
        )

    def _format_pnl(val):
        sign = "+" if val >= 0 else "-"
        return f"{sign}${abs(val):.2f}"

    message = (
        "\U0001F4CA *REPORTE DE OPERACIONES*\n\n"
        f"\U0001F4B0 *Balance total:* ${total_balance:.2f} USDC\n\n"
        f"\U0001F4BC *Posiciones abiertas:*\n"
        f"{position_lines}\n"
        f"\U0001F4C8 *PnL de 7 d\u00edas:* {_format_pnl(pnls['7d'])} USDC\n"
        f"\U0001F4CA *PnL de 15 d\u00edas:* {_format_pnl(pnls['15d'])} USDC\n"
        f"\U0001F4C9 *PnL de 30 d\u00edas:* {_format_pnl(pnls['30d'])} USDC\n\n"
        f"\U0001F9ED *ADX:* {' | '.join(adx_parts)}"
    )

    send_telegram(message)

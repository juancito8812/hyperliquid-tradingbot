#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/juancito8812/hyperliquid-tradingbot.git"
INSTALL_DIR="${1:-/opt/hyperliquid-bot}"

echo "=== Hyperliquid Trading Bot — Ubuntu 26.04 LTS Installer ==="
echo ""

# ── Clone or use existing ──
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "[1/6] Repo exists at $INSTALL_DIR, pulling latest..."
    cd "$INSTALL_DIR"
    git pull
else
    echo "[1/6] Cloning repo to $INSTALL_DIR..."
    sudo mkdir -p "$(dirname "$INSTALL_DIR")"
    sudo chown "$USER:$USER" "$(dirname "$INSTALL_DIR")"
    git clone "$REPO" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# ── Python venv ──
echo "[2/6] Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

# ── Environment config ──
echo "[3/6] Configuring environment..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "  >>> Edit .env with your credentials before starting:"
    echo "  >>>   nano $INSTALL_DIR/.env"
    echo ""
fi

# ── Log directory ──
mkdir -p logs

# ── systemd unit ──
echo "[4/6] Installing systemd service..."
SERVICE_FILE="$INSTALL_DIR/hyperliquid-bot.service"
sudo cp "$SERVICE_FILE" /etc/systemd/system/hyperliquid-bot.service
sudo sed -i "s|/opt/hyperliquid-bot|$INSTALL_DIR|g" /etc/systemd/system/hyperliquid-bot.service
sudo systemctl daemon-reload

# ── Enable + start ──
echo "[5/6] Enabling auto-start on boot..."
sudo systemctl enable hyperliquid-bot

if [ -f .env ] && grep -q "0xYOUR" .env; then
    echo ""
    echo "  >>> .env still has placeholder values."
    echo "  >>> Edit it and then run: sudo systemctl start hyperliquid-bot"
    echo ""
else
    echo "[6/6] Starting bot..."
    sudo systemctl start hyperliquid-bot
    sleep 2
    sudo systemctl status hyperliquid-bot --no-pager
fi

echo ""
echo "=== Installation complete ==="
echo "  Service:  sudo systemctl [start|stop|restart|status] hyperliquid-bot"
echo "  Logs:     sudo journalctl -u hyperliquid-bot -f"
echo "  File log: $INSTALL_DIR/logs/bot.log (if LOG_FILE set in .env)"
echo "  Dir:      $INSTALL_DIR"

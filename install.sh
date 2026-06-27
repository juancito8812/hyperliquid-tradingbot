#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/juancito8812/hyperliquid-tradingbot.git"
INSTALL_DIR="${1:-/opt/hyperliquid-bot}"

clear
echo "=============================================="
echo "  Hyperliquid Trading Bot — Ubuntu Installer"
echo "  SOL/ETH/BTC | Testnet | EMA+ADX+ATR+SAR"
echo "=============================================="
echo ""

# ── Prerequisites ──
for cmd in git python3 curl; do
    if ! command -v $cmd &>/dev/null; then
        echo "Installing $cmd..."
        sudo apt-get update -qq && sudo apt-get install -y -qq $cmd
    fi
done

# ── Clone ──
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "[1/7] Updating existing install at $INSTALL_DIR..."
    cd "$INSTALL_DIR"
    git pull -q
else
    echo "[1/7] Cloning repo..."
    sudo mkdir -p "$INSTALL_DIR"
    sudo chown "$USER:$USER" "$INSTALL_DIR"
    git clone -q "$REPO" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# ── Credentials ──
echo ""
echo "[2/7] API Credentials"
echo "  (press Enter to skip, you can edit /opt/hyperliquid-bot/.env later)"
echo ""

read -p "  Hyperliquid Wallet Address (0x...): " HL_ADDR
read -p "  Hyperliquid Private Key (0x...):    " HL_KEY
read -p "  Telegram Bot Token:                 " TG_TOKEN
read -p "  Telegram Chat ID:                   " TG_CHAT

cat > .env <<EOF
HL_ACCOUNT_ADDRESS=${HL_ADDR:-0xYOUR_WALLET_ADDRESS}
HL_PRIVATE_KEY=${HL_KEY:-0xYOUR_PRIVATE_KEY}
TELEGRAM_TOKEN=${TG_TOKEN:-YOUR_BOT_TOKEN}
TELEGRAM_CHAT_ID=${TG_CHAT:-YOUR_CHAT_ID}
LOG_FILE=$INSTALL_DIR/logs/bot.log
EOF

chmod 600 .env
echo ""
echo "  Credentials saved to .env"

# ── Venv + deps ──
echo "[3/7] Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install -q --upgrade pip

echo "[4/7] Installing dependencies..."
pip install -q -r requirements.txt

# ── Directories ──
mkdir -p logs

# ── systemd ──
echo "[5/7] Installing systemd service..."
sudo cp hyperliquid-bot.service /etc/systemd/system/hyperliquid-bot.service
sudo sed -i "s|/opt/hyperliquid-bot|$INSTALL_DIR|g" /etc/systemd/system/hyperliquid-bot.service
sudo systemctl daemon-reload

# ── Enable ──
echo "[6/7] Enabling auto-start on boot..."
sudo systemctl enable hyperliquid-bot

# ── Start ──
if grep -q "0xYOUR\|YOUR_BOT\|YOUR_CHAT" .env 2>/dev/null; then
    echo ""
    echo "  >>> Some credentials are still placeholders."
    echo "  >>> Edit .env and then: sudo systemctl start hyperliquid-bot"
else
    echo "[7/7] Starting bot..."
    sudo systemctl start hyperliquid-bot
    sleep 3
    echo ""
    sudo systemctl status hyperliquid-bot --no-pager --lines=5
fi

echo ""
echo "=============================================="
echo "  INSTALL COMPLETE"
echo ""
echo "  Manage:   sudo systemctl [start|stop|restart|status] hyperliquid-bot"
echo "  Logs:     sudo journalctl -u hyperliquid-bot -f"
echo "  File log: $INSTALL_DIR/logs/bot.log"
echo "=============================================="

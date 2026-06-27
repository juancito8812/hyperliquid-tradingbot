#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d venv ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt

export $(grep -v '^#' .env | xargs) 2>/dev/null || true
mkdir -p logs

exec python main.py

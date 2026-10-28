#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

echo "Anaplan Daily Backup v1.1 — macOS setup"
command -v python3 >/dev/null 2>&1 || { echo "ERROR: Python 3 is required."; exit 1; }
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
[ -f .env ] || cp .env.example .env
[ -f config/models.yaml ] || cp config/models.example.yaml config/models.yaml
mkdir -p logs .browser-profile

echo
echo "Setup complete."
echo "1. Edit config/models.yaml"
echo "2. Keep backup.dry_run: true"
echo "3. Run: ./run.sh --dry-run"

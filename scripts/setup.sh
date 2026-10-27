#!/usr/bin/env bash
# macOS / Linux setup:  bash scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
command -v node >/dev/null || { echo "Node.js 20+ required"; exit 1; }
command -v python3 >/dev/null || { echo "Python 3.11+ required"; exit 1; }
echo "[1/3] npm install";                  npm install
echo "[2/3] backend/.venv";                [ -d backend/.venv ] || python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip
echo "[3/3] Python packages (torch is large)"; backend/.venv/bin/python -m pip install -r backend/requirements.txt
echo; echo "Done. Next:  ollama pull phi && ollama pull mistral && hf auth login && npm start"

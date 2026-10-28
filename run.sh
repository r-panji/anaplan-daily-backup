#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "ERROR: Environment not installed. Run ./setup.sh first."
  exit 1
fi
exec .venv/bin/python app/main.py "$@"

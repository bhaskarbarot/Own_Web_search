#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
port="${1:-8765}"
python_bin=python3
if [[ -x .venv/bin/python ]]; then python_bin=.venv/bin/python; fi
if [[ ! "$port" =~ ^[0-9]+$ ]] || (( port < 1 || port > 65535 )); then
  echo 'Usage: ./run.sh [port 1–65535]' >&2
  exit 2
fi
export OWNSEARCH_SOURCES_FILE="${OWNSEARCH_SOURCES_FILE:-$(pwd)/sources.txt}"
if [[ "${OWNSEARCH_OPEN_BROWSER:-1}" == 1 ]] && command -v xdg-open >/dev/null; then
  (sleep 1; xdg-open "http://127.0.0.1:$port/ui" >/dev/null 2>&1 || true) &
fi
exec "$python_bin" main.py serve --port "$port"

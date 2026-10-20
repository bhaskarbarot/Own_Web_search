#!/usr/bin/env sh
set -eu
profile=${1:-base}
case "$profile" in base|full) ;; *) echo 'Usage: sh scripts/setup.sh [base|full]' >&2; exit 2;; esac
python3 -m venv .venv
if [ "$profile" = full ]; then
    .venv/bin/python -m pip install -e '.[full]'
else
    .venv/bin/python -m pip install -e .
fi
.venv/bin/python -m unittest discover -s tests -t .

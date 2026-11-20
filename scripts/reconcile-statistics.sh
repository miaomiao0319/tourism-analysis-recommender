#!/bin/sh
set -eu
[ "$#" -eq 2 ] && [ "$1" = '--batch-id' ] || { echo 'Usage: sh scripts/reconcile-statistics.sh --batch-id ID' >&2; exit 2; }
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
cd "$ROOT"
exec "$ROOT/.venv/bin/python" -m analysis.runner reconcile --batch-id "$2"

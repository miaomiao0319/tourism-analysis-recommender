#!/bin/sh
# Source .env before launching; all jobs run from the current checkout.
set -eu
[ "$#" -eq 4 ] && [ "$1" = '--batch-id' ] && [ "$3" = '--run-id' ] || { echo 'Usage: sh scripts/run-mapreduce.sh --batch-id ID --run-id ID' >&2; exit 2; }
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
cd "$ROOT"
exec "$ROOT/.venv/bin/python" -m analysis.runner mapreduce --batch-id "$2" --run-id "$4"

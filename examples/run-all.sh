#!/usr/bin/env bash
# Run every decree demo scenario, in narrative order:
#   before you code → while you code → after you code → keeping it honest over time.
# Each scenario builds a throwaway repo, runs real `decree`, and prints real output.
#
#   bash examples/run-all.sh                         # uses `decree` on PATH
#   DECREE="$PWD/.venv/bin/decree" bash examples/run-all.sh   # local checkout
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
for s in 01-why 02-intent-check-conflict 03-parallel-sessions 04-intent-review 05-health-dead-governance 06-governs-gap; do
  printf '\n\033[1;44m  %s  \033[0m\n' "$s"
  bash "$DIR/$s.sh"
done
printf '\n\033[1;42m  all scenarios ran  \033[0m\n'

#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 || ${1:-} != --half || ! ${2:-} =~ ^[12]$ ]]; then
  echo "Usage: bash run_experiments_n4.sh --half {1|2}" >&2
  exit 2
fi

cd "$(dirname "${BASH_SOURCE[0]}")"
half="$2"
workers="${N4_WORKERS:-4}"
timeout="${N4_TIMEOUT:-300}"
out="results/n4-and-or/half-$half"

aig-exact npn -n 4 --out "$out/functions.txt"
aig-exact reproduce -n 4 --functions "$out/functions.txt" --half "$half" \
  --model paper-aig --encoding ssv --max-gates 10 \
  --workers "$workers" --timeout "$timeout" --out "$out" --resume
aig-exact manifest --minima "$out/minima.json" \
  --config configs/paper-encodings.json --out "$out/manifest.jsonl"
aig-exact run --manifest "$out/manifest.jsonl" \
  --workers "$workers" --timeout "$timeout" --out "$out/benchmarks" --resume

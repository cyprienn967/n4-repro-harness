# draft!!

#!/usr/bin/env bash
set -euo pipefail

# Run this from the n4-repro-harness repository root.
# Activate your virtual environment first and install -e '.[sat,analysis]'.

mkdir -p data results

NPN=data/n3_npn_representatives.txt
MINIMA_DIR=results/n3_exact_minima_ssv
MANIFEST=data/n3_encoding_pruning_benchmark_manifest.jsonl
RUNS_DIR=results/n3_encoding_pruning_benchmark_runs
SUMMARY_DIR=results/n3_encoding_pruning_benchmark_summary
FEATURES=data/n3_boolean_features_npn_stabilizers.jsonl

aig-exact npn -n 3 --out "$NPN"

aig-exact reproduce -n 3 \
  --functions "$NPN" \
  --max-gates 10 \
  --encoding ssv \
  --out "$MINIMA_DIR" \
  --resume

aig-exact manifest \
  --minima "$MINIMA_DIR/minima.json" \
  --config configs/encodings.json \
  --out "$MANIFEST"

aig-exact run \
  --manifest "$MANIFEST" \
  --out "$RUNS_DIR" \
  --resume

aig-exact aggregate \
  --runs "$RUNS_DIR" \
  --out "$SUMMARY_DIR"

aig-exact features -n 3 \
  --functions "$NPN" \
  --stabilizer-elements \
  --out "$FEATURES"

printf '\nOutput locations:\n%s\n%s\n%s\n%s\n%s\n%s\n' \
  "$NPN" "$MINIMA_DIR" "$MANIFEST" "$RUNS_DIR" "$SUMMARY_DIR" "$FEATURES"

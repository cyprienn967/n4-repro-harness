#!/usr/bin/env bash
set -euo pipefail

# Run from the repository root

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
python -m pip install --upgrade pip
python -m pip install -e '.[sat,analysis]'

# Create directories
mkdir -p data results

# Generate NPN representatives
aig-exact npn -n 3 --out data/npn3.txt
cat data/npn3.txt

# Reproduce minimum gate counts (find minimum gate count C(f) for each NPN class) using SSV encoding
aig-exact reproduce -n 3 \
  --functions data/npn3.txt \
  --max-gates 10 \
  --encoding ssv \
  --workers 4 \
  --out results/reproduction3 \
  --resume

# Generate experiment manifest (generate a list of SAT experiments to run) for each NPN class, for each encoding
# Purpose: compare SSV, MSV, DITT, and different symmetry-breaking configurations on the same synthesis problems
# Use the known minima to generate SAT instances at
# k = C(f)-1 (UNSAT) and k = C(f) (SAT).
# Include all encoding and pruning configurations.
aig-exact manifest \
  --minima results/reproduction3/minima.json \
  --config configs/encodings.json \
  --out data/benchmark_manifest_n3.jsonl

# Run experiments (run SAT solver on each experiment in the list)
aig-exact run \
  --manifest data/benchmark_manifest_n3.jsonl \
  --out results/benchmark_out_n3 \
  --resume

# Aggregate results (aggregate results from all experiments into a single summary, combine measurements and compute summary statistics)
aig-exact aggregate \
  --runs results/benchmark_out_n3 \
  --out results/tables3

# Extract features (independent analysis, computing math properties of each Boolean function)
aig-exact features -n 3 \
  --functions data/npn3.txt \
  --stabilizer-elements \
  --out data/features3.jsonl

echo "All experiments completed successfully!"

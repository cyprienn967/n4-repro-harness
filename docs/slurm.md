# Slurm example

Generate the manifest on your workstation or login node first. Copy the source,
manifest and solver dependencies to a filesystem accessible by all workers.
Install the package in an environment that every worker can activate.

Save a job script such as the following, replacing paths and partition/account
settings to match your cluster. This file is documentation, not an automatically
submitted job.

```bash
#!/bin/bash
#SBATCH --job-name=aig-matrix
#SBATCH --array=0-31
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=04:00:00
#SBATCH --output=slurm-%A_%a.log
set -euo pipefail
cd /absolute/path/to/aig-exact
source .venv/bin/activate
export OMP_NUM_THREADS=1
aig-exact run --manifest data/proof-matrix.jsonl \
  --shards 32 --shard-index "$SLURM_ARRAY_TASK_ID" \
  --out results/proof-matrix --resume
```

Submit with `sbatch your-job.sh`. Each array worker processes a disjoint shard
sequentially. Make the scheduler time limit larger than your per-run solver
limit plus encoding/proof I/O overhead, or use smaller manifests. `--timeout`
limits external solve time, not encoding or total job time. Proof size is not
bounded by this harness; provision disk explicitly. Do not launch overlapping
shards into the same run directories. Reaggregate only after workers finish.

# aig-exact

Exact synthesis of small single-output Boolean circuits, plus an experiment
harness for comparing encodings, symmetry breaking, and function structure.

**Status:** source implementation prepared without running it. No synthesis,
NPN enumeration, tests, solver builds, or benchmarks were run during creation.
There are no bundled results and no automatic GitHub Actions workflows. Run the
small checks below locally before trusting a full campaign. The target is to
reproduce the known **L(4) = 10**, not to claim that this repository has already
reproduced it.

## What is being counted?

- Two-input AND: one gate.
- NOT/complemented wires: free.
- Fanout: unrestricted and free.
- One output; constants 0 and 1 are allowed for free.
- OR is represented by De Morgan; XOR is not a primitive.
- These are circuits (DAGs), not formulas/trees.

`F(f,k)` normally means **a circuit with at most k paid gates**. The encoder
allocates k gate slots, permits unused slots and duplicate/identity gates, and
selects the output from any signed signal. Thus a smaller circuit can always be
padded. Three optional pruning flags change this contract to a search preserving
minimum circuits; see the toggle table. The minimum-search command always tries
0,1,... in order and stops on the first unresolved result.

NPN equivalence preserves this cost because input permutations, input negation,
and output negation cost nothing. Four inputs have **222 NPN classes**; **768**
is the size of the transformation group, not the number of classes.

## 1. Install locally

Requires Python 3.11 or newer. Linux and macOS are the intended platforms;
external solver timeouts use POSIX process groups. On Windows, use WSL.

```bash
cd aig-exact
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[sat]'
aig-exact --help
```

The `sat` extra installs **python-sat (PySAT)**, not the unrelated astronomy
package called `pysat`. The default embedded solver is `cadical195`. Optional
analysis dependencies provide pandas/Parquet and NetworkX:

```bash
python -m pip install -e '.[sat,analysis]'
```

To capture your actual resolved versions:

```bash
python -m pip freeze > local-environment.txt
```

There is intentionally no dependency lockfile claiming versions tested here.
The Python package itself needs no dependencies to generate CNF or features.

## 2. Run small correctness checks first

These are commands for you to run; they have not been executed here.

```bash
python -m unittest discover -s tests -v
AIG_EXACT_FULL_TESTS=1 python -m unittest discover -s tests -v
```

The first command checks truth-table conventions, cofactor math, the scalar
circuit interpreter, and solver-output parsing. With the `sat` extra it also
compares all three encodings against an independent tiny chain enumerator and
checks exact costs of all 16 two-input functions, including optional pruning.
The second also checks that the 222 four-input orbits partition all 65,536 truth
tables. Neither command runs a complete four-input synthesis campaign.

A useful first synthesis smoke test is XOR of two variables:

```bash
aig-exact minimum -n 2 --hex 6 --max-gates 3 --out results/xor
```

Expected minimum: 3 AND nodes. A constant or literal has minimum 0:

```bash
aig-exact minimum -n 2 --hex a --max-gates 0 --out results/literal
```

## 3. Reproduce L(4) = 10

Generate a complete representative set locally; no data download is required:

```bash
aig-exact npn -n 4 --out data/npn4.txt
```

This explicitly enumerates NPN orbits, takes the smallest integer truth table
in each orbit, checks the expected class count, and writes a checksum/convention
sidecar. Representatives use our canonical convention; another database can
use different hex representatives of the same classes.

Then find every exact minimum:

```bash
aig-exact reproduce -n 4 --functions data/npn4.txt \
  --max-gates 10 --expect-max 10 --encoding ssv \
  --workers 8 --out results/reproduction --resume
```

This validates that your input contains one representative of every NPN class,
tries budgets from 0 upward for each representative, verifies each SAT witness,
and writes `results/reproduction/minima.json` after each function. At completion
it checks full coverage and that the largest exact minimum is 10. A timeout,
error or unknown prevents that function from being declared exact. The command
returns a nonzero exit code for an incomplete campaign or a failed expected
maximum. `--allow-subset` permits pilot runs, but cannot establish the universal
L(4) claim.

`--workers` defaults to 1. With multiple workers, each process searches a
different function and still tries that function's gate counts in order. The
report keeps the input order even when functions finish out of order.

`claim_verified` in this report means the solver-based reproduction completed
with validated witnesses and full coverage. It does **not** mean the UNSAT
certificates have been checked. Proof checks are separate, explicit artifacts.
Do not report a proof-certified result until those are checked too.

Restart the identical command with `--resume` after interruption. Completed
SAT/UNSAT runs are reused only when source/solver fingerprints and saved
artifact hashes match. TIMEOUT/UNKNOWN/ERROR runs are retried. The campaign
reconstructs its minima report from these runs rather than trusting a partial
report. A changed configuration creates different run directories.

## 4. Solve one instance or emit CNF only

```bash
# Find one circuit or prove this budget impossible.
aig-exact solve -n 4 --hex 1669 -k 9 --encoding ssv \
  --out results/single

# Emit DIMACS, variable names and metadata; launches no solver.
aig-exact emit -n 4 --hex 1669 -k 9 --encoding ditt \
  --out artifacts/1669-ditt-k9
```

`1669` is just a convenient named instance here; the full reproduction does not
hard-code which classes must be hardest. Solving at a single budget does not
by itself determine an exact minimum unless an upper/lower argument supplies
the other side.

### Encodings

These are original **AIG-specialized adaptations** of the selection ideas in
the exact-synthesis literature. They are not Percy's source code and do not
claim to reproduce the paper's general-gate encodings clause for clause.

| Flag | Meaning |
| --- | --- |
| `--encoding ssv` | One-hot selection over pairs of signed fanins. Each selected pair directly guards AND semantics. |
| `--encoding msv` | Separate one-hot selection for each fanin. A pair of selected ports jointly guards AND semantics. |
| `--encoding ditt` | Separate one-hot selection for each fanin plus selected-input truth-table variables. Wiring propagates into these variables; AND semantics use them directly. |
| `--cardinality sequential` | Sinz-style ladder at-most-one plus an at-least-one clause; default. |
| `--cardinality pairwise` | Pairwise at-most-one clauses plus an at-least-one clause. |

All encodings include all truth-table rows, free signed edges and explicit
output selection. No CEGAR or arbitrary two-input operators are mixed into the
comparison. No binary-index encoding is implemented.

### Symmetry/pruning toggles

| Flag | Default | Effect and scope |
| --- | --- | --- |
| `--fanin-order` / `--no-fanin-order` | On | Canonical order of signed fanins, exploiting commutativity. Preserves at-most-k semantics. |
| `--no-trivial` | Off | Forbids constant fanins and two fanins from the same unsigned source, removing constant/identity gates. Preserves all size-minimum circuits; changes the padded query. |
| `--no-duplicates` | Off | Forbids repeated unordered pairs of the same signed fanins. Minimum circuits never need these with free fanout. Changes the padded query. |
| `--all-used` | Off | Every gate must feed a later gate or the output, which implies output reachability in a DAG. Preserves minima; changes the padded query. |
| `--target-symmetry` | Off | Computes the exact NPN stabilizer of f, then retains only the smallest signed first-gate pair in each stabilizer orbit. Requires fanin ordering. Preserves the baseline query and minimum-search variants. |

Example:

```bash
aig-exact minimum -n 4 --hex 1669 --max-gates 10 \
  --encoding msv --cardinality sequential \
  --no-trivial --no-duplicates --all-used --target-symmetry \
  --out results/pruned --resume
```

`--no-trivial` is an enable flag, not the negation of a `--trivial` option.
With any minimum-only pruning enabled, an UNSAT answer at a large budget does
not rule out all smaller circuits on its own. The increasing-budget search is
the safe route. For uncomplicated fixed-budget lower-bound certificates, use
the default at-most formulation.

The target breaker is deliberately modest and transparent: it does not enforce
lexicographic canonicality of the entire circuit, assume that an optimal circuit
is symmetric, or claim complete symmetry elimination. No gate-order/colex
breaker, canonical augmentation, topology enumeration or double-coset method is
implemented. These need separate soundness arguments before combining them
with the existing constraints.

## 5. External solvers, timeouts and proof certificates

Embedded PySAT gives structured decisions/conflicts/propagations/restarts, but
this harness does not produce certificates or hard timeouts through it. Use an
external solver for proof-quality campaigns and bounded runtimes.

Build/install the upstream tools locally:

- [CaDiCaL](https://github.com/arminbiere/cadical)
- [Kissat](https://github.com/arminbiere/kissat)
- [DRAT-trim](https://github.com/marijnheule/drat-trim)

For example, from the project root:

```bash
mkdir -p third_party
git clone https://github.com/arminbiere/cadical third_party/cadical
(cd third_party/cadical && ./configure && make -j4)
git clone https://github.com/marijnheule/drat-trim third_party/drat-trim
make -C third_party/drat-trim
export PATH="$PWD/third_party/cadical/build:$PWD/third_party/drat-trim:$PATH"
```

Record upstream commit IDs alongside your experiment notes. The harness hashes
the external executable bytes for result identity. Its saved argv records the
flags, including seeds. Check your installed solver's help if flags differ.

```bash
aig-exact solve -n 4 --hex 1669 -k 9 \
  --backend external \
  --solver-argv '["cadical", "--seed=0", "{cnf}", "{proof}"]' \
  --timeout 3600 --out results/certificates
```

The runner replaces `{cnf}` and `{proof}` with absolute artifact paths in each
argument and invokes the executable directly, never through a shell. A timeout
kills the process group and records TIMEOUT. Status/exit-code disagreements
are errors. SAT requires a decodable full selection model and independent
witness simulation; missing/invalid witnesses become ERROR.

The command prints the exact run directory. Use it for checking:

```bash
# Replace RUN_ID with the directory printed by solve.
aig-exact check-proof results/certificates/RUN_ID --checker drat-trim

# Also ask DRAT-trim to write LRAT:
aig-exact check-proof results/certificates/RUN_ID --checker drat-trim --lrat
```

A successful check requires an UNSAT result, a zero checker exit code, and its
explicit `s VERIFIED` verdict. `proof-check.json` binds the verdict to the CNF
and proof hashes. LRAT export alone is not a formally verified proof check;
this repository does not integrate cake_lpr.

For a complete proof-producing reproduction, replace the solver options in
section 3 with the external options above. It will save proofs for all UNSAT
budgets. Check the desired run directories separately. A clean certificate of
L(4)=10 needs 10-or-fewer-gate witnesses for every class and a verified
9-gate UNSAT instance for at least one class, provided that query is at-most-9.
Proving every individual exact minimum additionally requires the corresponding
lower-bound certificates. With minimum-only pruning, all lower budgets must be
accounted for rather than inferring monotonicity of the padded query.

A certificate proves the emitted CNF is UNSAT; the encoding's completeness and
the pruning lemmas remain part of the trusted reduction. Use the differential
checks and independent cross-checks before treating a campaign as research evidence.

## 6. Benchmark near-optimal SAT and UNSAT instances

After producing exact minima:

```bash
aig-exact manifest --minima results/reproduction/minima.json \
  --config configs/encodings.json --out data/encoding-matrix.jsonl

aig-exact run --manifest data/encoding-matrix.jsonl \
  --out results/encoding-matrix --resume

aig-exact aggregate --runs results/encoding-matrix --out results/tables
```

`manifest` only creates jobs. `run` executes them. The supplied matrix uses
budgets C(f)-1 and C(f), skips negative budgets for zero-cost functions, and
compares baseline encodings and individual/combined pruning options with a
fixed solver. Exact minima are required; unresolved functions are not silently
excluded. Edit the JSON to add the same toggle combinations to MSV/DITT or
compare additional solvers. An external proof/seed example is provided as
`configs/external-proof.json`:

```bash
aig-exact manifest --minima results/reproduction/minima.json \
  --config configs/external-proof.json --out data/proof-matrix.jsonl
```

Each variant has a name and an `options` object using Python-style keys:
`encoding`, `cardinality`, `fanin_order`, `no_trivial`, `no_duplicates`,
`all_used`, `target_symmetry`. A solver row uses either `backend=pysat` plus
`solver`, or `backend=external` plus `solver_argv` and `timeout`. Seed changes
belong in external argv, e.g. `--seed=1`. Labels distinguish repeated campaigns.
There is no hidden random seed in NPN enumeration or CNF construction.

### Parallel runs / cluster use

Use disjoint shards of the identical manifest:

```bash
aig-exact run --manifest data/encoding-matrix.jsonl --shards 8 \
  --shard-index 0 --out results/encoding-matrix --resume
# Start seven other processes with shard-index 1,...,7.
```

For Slurm, see [docs/slurm.md](docs/slurm.md). The manifest row index modulo
`--shards` determines ownership; blank lines count toward indices. Do not
change the manifest while workers are running. Writes are per-run and atomic;
there is no shared JSONL file being appended by multiple workers. An exclusive
`.lock` rejects accidental concurrent ownership of a run. After a hard crash,
remove a stale lock only after confirming no worker still owns that run.

### Statistics and outputs

Every run has its own directory:

```text
results/<campaign>/<RUN_ID>/
  task.json           requested function/budget/configuration
  instance.cnf        exact DIMACS sent to the solver
  instance.json       query contract and CNF statistics
  variables.json      SAT variable names, indexed from 1 (list offset + 1)
  model.json          signed SAT model (empty for UNSAT)
  solver.stdout       raw solver output
  solver.stderr       external solver diagnostics, when applicable
  witness.json        compact independently verified SAT circuit
  witness.aag         ASCII AIGER representation
  proof.drat          external proof, when requested (may be binary DRAT)
  proof-check.json    independent checker verdict and hashes, after check-proof
  result.json         statistics, status, hashes and provenance
```

Recorded: encoding time, solver time, CNF variables/clauses/literals and length
histogram, solver counters when available, proof bytes, source hash, git commit,
Python/platform, solver identity, witness depth/fanouts/complemented edges and
restriction gate losses. PySAT initialization time is separate from solve time.
External time includes process startup. External counters and memory/CPU fields
are best-effort parsers; absent metrics are null/missing, never invented zeros.
External raw logs are authoritative; parsers may need adapting to your version.

`aggregate` produces `runs.csv`, raw `runs.jsonl`, and `summary.json`. Summaries
separate SAT/UNSAT/unknown/error/timeout, show geometric mean, median, p95, maximum,
and timeout fraction, and group by configuration and source/solver fingerprint.
Successful-run means exclude timeouts; always report timeout counts beside them.
For fair comparisons use the same instance set, machine, thread policy, solver,
and seeds; avoid drawing conclusions from only a pooled mean. Export Parquet
with `aggregate ... --parquet` after installing the analysis extra.

## 7. Boolean-function and group-theoretic features

```bash
aig-exact features -n 4 --functions data/npn4.txt \
  --stabilizer-elements --out data/features4.jsonl

# Or inspect a single function:
aig-exact features -n 4 --hex 1669 --stabilizer-elements \
  --out data/1669-features.jsonl
```

Each line contains:

- Truth table and minimum-integer NPN representative.
- Essential-variable count, Hamming weight, ANF degree and monomial support.
- Complete Walsh spectrum, autocorrelation, pointwise sensitivities,
  maximum sensitivity, influence vector, Boolean derivatives.
- Every one-variable cofactor and its NPN class, monotonicity and unateness.
- Exact NPN group size, stabilizer size, orbit size, input-only stabilizer size,
  and orbits of signed restrictions `(variable,value)`.
- With `--stabilizer-elements`, **all** stabilizer elements, not heuristic
  generators or an approximate group size.

`degree=0` is used for the zero polynomial. Raw weight, signed spectra and
coordinate-ordered vectors are features of this representative; not all are
NPN invariants without normalization. Do not treat them as automatically
invariant. See [docs/mathematics.md](docs/mathematics.md) for conventions.

To attach exact cofactor complexities, first classify three-input functions:

```bash
aig-exact npn -n 3 --out data/npn3.txt
aig-exact reproduce -n 3 --functions data/npn3.txt --max-gates 10 \
  --out results/reproduction3 --resume
aig-exact features -n 4 --functions data/npn4.txt \
  --cofactor-minima results/reproduction3/minima.json \
  --stabilizer-elements --out data/features4.jsonl
```

The join requires EXACT records of dimension n-1 and fails if a needed class is
missing. Exact complexities of the four-input functions themselves are in the
four-input `minima.json`; join by canonical hex/NPN representative.

### Circuit structure and restriction experiments

```bash
aig-exact verify results/CAMPAIGN/RUN_ID/witness.json --hex 1669
aig-exact inspect results/CAMPAIGN/RUN_ID/witness.json \
  --out data/circuit-features.json

# Optional, requires the analysis extra; can be expensive:
aig-exact inspect results/CAMPAIGN/RUN_ID/witness.json --automorphisms \
  --out data/circuit-group.json
```

The optional automorphism count fixes individual primary inputs and constants,
allows gate permutations, treats AND ports as unordered and preserves wire
phases and the designated output. It counts signal-vertex maps, not artificial
permutations of duplicate incidence edges. It is a circuit-topology symmetry
under this explicit convention, not the NPN automorphism group of the function.

Restriction gate loss applies constant propagation, identities/complements,
structural hashing, then dead-gate removal. It describes **this particular
witness**. Observing that a restriction removes d gates does not prove that it
removes d gates from every circuit computing f; do not promote it into a circuit
lower bound without a universal argument.

Suggested first analyses: compare hard classes' cofactor complexity profiles,
stabilizers and restriction orbits; compare the same SAT/UNSAT instances across
encodings; inspect which toggle helps high-symmetry targets. No ML selector or
unproved mathematical pruning is included.

## 8. Truth-table and circuit formats

A truth table is a hex integer. **Bit t is f(x0,...,x[n-1]), where
xi = (t >> i) & 1.** Thus for two inputs x0=`a`, x1=`c`, AND=`8`, XOR=`6`.
For four inputs x0=`aaaa`, x1=`cccc`, x2=`f0f0`, x3=`ff00`.

A functions file contains one hex truth table per line; comments after `#` and
blank lines are allowed. The JSON input route accepts a list of hex strings or
an object with a `functions` list whose rows have `hex` fields.

Witness JSON:

```json
{"n": 2, "gates": [[2, 4], [3, 5], [7, 9]], "output": 10}
```

Source 0 is constant false, sources 1..n are inputs, subsequent sources are
AND gates in topological order. Literal `2*s` reads source s; `2*s+1` complements
it. The example is XOR with three AND nodes. ASCII AIGER `.aag` files can be
read by standard AIG tools; binary `.aig` export is not implemented.

## 9. Independent tools and references

The main pipeline is self-contained Python plus a SAT solver; it does not
require building ABC, Percy, Kitty, or Mockturtle. Those remain useful independent
cross-checks and extension points:

- [OEIS A057241](https://oeis.org/A057241): AND/free-NOT worst-case complexity;
  [Schroeppel's notes](https://oeis.org/A057241/a057241.txt).
- [OEIS A000370](https://oeis.org/A000370): NPN class counts.
- [Haaswijk et al., SAT-Based Exact Synthesis](https://people.eecs.berkeley.edu/~alanmi/publications/2020/tcad20_exact.pdf): selection encodings, symmetry and topology experiments. Our restricted AIG encodings are adaptations.
- [Percy](https://github.com/whaaswijk/percy), [Kitty](https://github.com/lsils/kitty),
  [Mockturtle](https://github.com/lsils/mockturtle).
- [Berkeley ABC](https://github.com/berkeley-abc/abc): independent synthesis oracle.
  Run `abc -c 'twoexact -h'` for your exact build, confirm AND-only mode and the
  truth-table convention, then compare minima. This repository does not wrap
  version-dependent ABC commands or count an ABC output as a certificate.
- [PySAT](https://pysathq.github.io/), [CaDiCaL](https://github.com/arminbiere/cadical),
  [Kissat](https://github.com/arminbiere/kissat), [DRAT-trim](https://github.com/marijnheule/drat-trim).

Full n=5 enumeration is intentionally **not** provided: generating every orbit
by scanning 2^32 functions is not an appropriate next step. The individual
encoders and feature extractor accept up to five inputs, but NPN representative
generation and full-coverage reproduction are limited to n<=4. Five-input feature
extraction is brute-force exact and may be slow. Scaling to 616,126 classes,
topology-aware methods and stronger function-specific lemmas are future work.

## Publish this source to GitHub

If this folder was supplied as an archive, extract it and run:

```bash
gh auth login
bash scripts/publish.sh aig-exact
```

This creates a **private** repository in your authenticated personal account
and pushes the source. It does not run tests, solvers or campaigns. It requires
GitHub CLI and a configured git author identity. If you already have an origin
remote, the script stops so you can inspect it and push manually. Research data,
large proofs and local virtual environments are ignored by git by default.

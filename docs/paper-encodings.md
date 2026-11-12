# Paper-aligned binary exact synthesis

Reference: Haaswijk et al., *SAT-Based Exact Synthesis: Encodings, Topology
Families, and Parallelism*, TCAD 2020, Sections III-A–D.
[Paper](https://people.eecs.berkeley.edu/~alanmi/publications/2020/tcad20_exact.pdf).

## Gate model and scope

Use `--model paper`. Each step is an arbitrary two-input Boolean operator;
its three free bits are f01, f10, f11, and f00=0. Its two operands are distinct
unsigned earlier signals j<h<i. Constants are not pooled operands. A target
with f(0)=1 is complemented before synthesis, then the output is complemented
when decoding. This normal form retains arbitrary binary-gate circuit minima.

This implements the two-input, single-output case, not the paper's general
multi-output/k-input model, topology families, or topology-parallel algorithms.
The existing parallel campaign scheduler remains available. Zero-step constants
and literals are handled as a boundary case. Positive-step synthesis requires
at least two available primary signals, as required by distinct binary operands.

The default `--model aig` is retained for existing experiments: arbitrary binary
gates change the cost model. For example, XOR needs one paper step but three
AND gates. Do not apply the AIG L(4)=10 expectation to paper-mode results.
Legacy AIG pruning flags cannot be mixed with paper mode; they are not aliases
for the paper's symmetry breakers.

## Variables and clauses

For step i and input row t=1,...,2^n-1, x_it denotes its value. Primary input
values are constants. Row zero is implicit because every signal is normal.
The main clause schema enumerates a,b,c in {0,1}:

    (negative selection guards) OR (x_it XOR a) OR (x_jt XOR b)
        OR (x_ht XOR c) OR (f_i_bc XOR NOT a)

Together these eight clauses enforce x_it=f_i(x_jt,x_ht) whenever the operands
are selected. f_i_00 is fixed false. Output selectors g_1i have an at-least-one
clause and imply equality of x_it with the normalized target on every row.

| Encoding | Selection variables | Cardinality and semantics |
| --- | --- | --- |
| SSV | s_ijh for each j<h<i | At least one pair; main clauses guarded by that pair selector. |
| MSV | s_ij for each j<i | Exactly two members of one pool; main clauses guarded by s_ij AND s_ih. |
| DITT | s_i1j, s_i2j | At least one source per port, strict source ordering, and direct input truth-table variables. Selected sources imply port-value equality; main clauses use port values without selection guards. |

SSV and DITT deliberately do not add at-most-one clauses absent from the paper.
Multiple active selections must be semantically consistent. Decoding chooses
one active pair and independently simulates the resulting witness.

MSV uses a linear unary prefix threshold counter, enforcing threshold 2 and
forbidding threshold 3. This implements the paper's UBC cardinality choice;
auxiliary naming and clause allocation are not claimed to be byte-identical
to a particular Percy release. Fixed literals are retained using a unit constant.

## Six symmetry breakers

Pass a subset with `--symmetries NARCOS`; omission means none. The matrix config
contains all 64 subsets for each of SSV, MSV and DITT.

| Letter | Paper constraint | Implementation |
| --- | --- | --- |
| N | No trivial operators | Exclude normal constant zero and the two projections using three operator clauses. |
| A | All steps used | Each step must feed a later step or the designated output. |
| R | No reapplication | If step i uses j,h, no later step may use i together with j or h. |
| C | Colexicographically ordered steps | Adjacent operand pairs are nondecreasing by (h,j). |
| O | Ordered operators | Adjacent steps with identical operand pairs have strictly increasing operator vectors (f11,f10,f01). |
| S | Symmetric variables | For symmetric primary inputs p<q, selecting q without p requires a preceding step that selects p. |

R relies on the ability to replace a composition on the same two signals with
one arbitrary operator. It is not sound as a direct restriction on AND-only
circuits. S tests ordinary input-swap symmetry of the target, not its full NPN
stabilizer. O is not merely duplicate signed-AND elimination.

Two transcription issues are resolved according to the intended constraints:
C negates both pair selectors (the displayed paper clause misses one bar);
DITT ordering includes the boundary first-source=i-1 so reversed/equal operands
cannot slip through. The C rule and S interpretation agree with
[Percy's encoder](https://github.com/whaaswijk/percy/blob/master/include/percy/encoders/ssv_encoder.hpp).
O uses the paper's strict order; some Percy implementations instead allow
non-strict operator order. Equality would only retain a redundant duplicate.

Symmetry-constrained queries preserve minimum solutions, but should not be
interpreted as arbitrary padded at-most-k queries. Use increasing-budget
`minimum`/`reproduce`; a single high-budget UNSAT answer is not sufficient to
establish all smaller budgets with these constraints.

## Run and compare

```bash
# XOR: one arbitrary binary step.
aig-exact minimum -n 2 --hex 6 --max-gates 3 --model paper \
  --encoding msv --symmetries NARCOS --out results/paper-xor

# Three-input campaign using the existing worker scheduler.
aig-exact npn -n 3 --out data/npn3.txt
aig-exact reproduce -n 3 --functions data/npn3.txt --max-gates 6 \
  --model paper --encoding ssv --symmetries NARCOS \
  --workers 8 --timeout 300 --out results/paper3 --resume

aig-exact manifest --minima results/paper3/minima.json \
  --config configs/paper-encodings.json --out data/paper-matrix.jsonl
aig-exact run --manifest data/paper-matrix.jsonl --out results/paper-matrix --resume
aig-exact aggregate --runs results/paper-matrix --out results/paper-tables
```

Results, options, minima and witnesses identify their model. Manifest creation
rejects minima from a different model. Paper witnesses contain `operators`,
with operator truth-table bit index 2*left+right, alongside unsigned AIGER-style
signal literals in `gates`. They can be verified and inspected, but are not
exported as AAG. AIG-specific restriction simplification is unavailable for
paper witnesses; it is not silently applied to arbitrary operators.

## Validation

`tests/test_paper_encodings.py` checks the MSV counter exhaustively, variable
families, all two-input functions, all three-input functions through three
steps against an independent integer-truth-table enumerator, all 64 symmetry
subsets on every three-input NPN minimum (the remaining classes use verified
four-step witnesses and the exhaustive three-step lower bound), and explicit forbidden
patterns for every breaker. SAT witnesses are independently simulated before
and after dead-step compaction. These finite checks are regression evidence,
not a proof of encoding correctness for arbitrary sizes.

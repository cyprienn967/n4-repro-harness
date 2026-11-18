# Paper-aligned binary exact synthesis

Reference: Haaswijk et al., *SAT-Based Exact Synthesis: Encodings, Topology
Families, and Parallelism*, TCAD 2020, Sections III-A–D.
[Paper](https://people.eecs.berkeley.edu/~alanmi/publications/2020/tcad20_exact.pdf).

## Gate model and scope

Use `--model paper-aig`. Each step has two distinct earlier operands with
unrestricted fanout. With free inversion every signal can be phased to be
zero on the all-zero input. In that convention the only two-input gates needed
are AND, OR, (~a AND b), and (a AND ~b). Each costs one AND with signed wires.
Restoring the output phase recovers the requested target. Constants and
literals cost zero. Equal-source gates simplify to a literal or constant.
The legacy `--model aig` uses the same cost metric and different selectors.

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
| N | No trivial operators | Exclude normal constant zero and the two projections through the gate basis. |
| A | All steps used | Each step must feed a later step or the designated output. |
| R | No reapplication | If step i uses j,h, no later step may use i together with j or h. |
| C | Colexicographically ordered steps | Adjacent operand pairs are nondecreasing by (h,j). |
| O | Ordered operators | Adjacent steps with identical operand pairs have strictly increasing operator vectors (f11,f10,f01). |
| S | Symmetric variables | For symmetric primary inputs p<q, selecting q without p requires a preceding step that selects p. |

N is automatic in this basis. Runs differing only by N generate identical CNFs.
For R, a later signed AND/OR gate that reuses an operand has a constant
cofactor on that operand (set it to the outer gate's controlling value).
The composition on the original two signals therefore cannot be XOR or XNOR.
After normalization it is one of the four allowed gates, a projection, or
zero. In the last two cases substitute and delete the later gate. Otherwise
replace just that gate, preserving every other consumer of the earlier gate.

Two transcription issues are resolved according to the intended constraints:
C negates both pair selectors (the displayed paper clause misses one bar);
DITT ordering includes the boundary first-source=i-1 so reversed/equal operands
cannot slip through. The C rule and S interpretation agree with
[Percy's encoder](https://github.com/whaaswijk/percy/blob/master/include/percy/encoders/ssv_encoder.hpp).
O uses the paper's strict order; some Percy implementations instead allow
non-strict operator order. Equality would only retain a redundant duplicate.

All six constraints can hold in the same size-minimum chain. Among the
minimum chains for a target, choose the lexicographically least sequence of
step keys `(larger operand, smaller operand, operator bits)`. This uses the
operator order `(f11, f10, f01)` from the encoder.

- **N and A.** A constant or a projection can be eliminated by substitution.
  An unused step can be deleted. Both would give a smaller chain.
- **R.** If a later step takes an earlier step and one of its operands,
  use the constant-cofactor argument above to compose the operators on the earlier step's
  original operands. The earlier step can still serve its other consumers.
  The replacement has a smaller largest operand at the later step, so the
  new chain contradicts the choice of the least sequence.
- **C and O.** If adjacent steps are out of order by their keys, they are
  independent. A dependency on the preceding step would make the later
  step's largest operand strictly larger. Swapping independent steps and
  updating references decreases the sequence. Identical keys are duplicate
  steps and can be merged, so O can require strict order for equal fanins.
- **S.** If a symmetric input q appears without p before any use of p,
  swap the labels p and q throughout the chain, transposing operators when
  operand order changes. At the first such use the operand pair gets smaller
  and the earlier step keys stay the same. The target is preserved by the swap.

A single chain therefore witnesses completeness for any subset. The argument
is for minimum size. Check budgets in increasing order with `minimum` or
`reproduce`, since constraints such as A can rule out padding at larger sizes.

## Run and compare

```bash
# XOR: three AND/OR gates.
aig-exact minimum -n 2 --hex 6 --max-gates 3 --model paper-aig \
  --encoding msv --symmetries NARCOS --out results/and-or-xor

# Three-input benchmark with unpruned reference minima.
aig-exact npn -n 3 --out data/npn3.txt
aig-exact reproduce -n 3 --functions data/npn3.txt --max-gates 6 \
  --model paper-aig --encoding ssv \
  --workers 8 --timeout 300 --out results/and-or3 --resume

aig-exact manifest --minima results/and-or3/minima.json \
  --config configs/paper-encodings.json --out data/paper-matrix.jsonl
aig-exact run --manifest data/paper-matrix.jsonl --out results/and-or-matrix --workers 8 --resume
aig-exact aggregate --runs results/and-or-matrix --out results/and-or-tables
```

Results, options, minima and witnesses identify their model. Manifest creation
rejects minima from a different model. Decoded witnesses use ordinary signed AIG literals and support AAG export,
independent simulation, and restriction analysis.

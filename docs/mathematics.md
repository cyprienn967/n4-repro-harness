# Reduction and symmetry contracts

Let C(f) denote minimum AND-node count with complemented wires, constants and
unbounded fanout. A signed signal is a source and a phase. Every gate has two
earlier signed fanins; output selection may choose any signed source.

## Completeness and padding

Every AIG has a topological order and is represented by these variables. In the
baseline, a circuit with r<=k gates can occupy the first r slots; remaining
slots may be duplicates or identities and need not feed the output. Therefore
baseline SAT iff C(f)<=k. Each truth-table row propagates all AND semantics;
one-hot selectors and output constraints imply that decoding a SAT assignment
yields f. The independent scalar interpreter checks this implication again.

Fanin order preserves a representative by AND commutativity. A minimum circuit
has no dead gates, no repeated signed fanin pair, no constant-dependent AND,
and no gate with equal or complementary fanins: each could be simplified or
merged to decrease size with free fanout. These facts justify the three
minimum-preserving pruning toggles. They do not justify assuming feasibility
is monotone in the number of slots after those toggles are enabled. Query every
budget up to the first SAT result.

## NPN action

For permutation p, input-phase mask a and output phase b, use
T(f)(x)=b XOR f(y), with y_i=x_{p[i]} XOR a_i. The group has
2^n n! 2 elements. The full stabilizer consists of transformations for which
T(f)=f; orbit size is group size divided by stabilizer size. The repository
explicitly enumerates the group (no probabilistic group computation).

For a stabilizer element, substitute each circuit primary literal x_i with
x_{p[i]} XOR a_i and complement the circuit output by b. The resulting circuit
computes the same f and uses the same gate count. This transforms the signed
fanin pair of gate zero into another pair of primary/constant literals.
Taking the lexicographically smallest sorted pair in each orbit therefore
preserves at least one representative. Constants are fixed by substitution.
The minimum-only pruning predicates are invariant under this action, so this
first-gate breaker can safely be combined with them. This is a partial breaker;
it does not canonicalize later gates or their order.

The action on restrictions is (i,v) -> (p[i],v XOR a_i). Output complementation
does not change the restriction's domain point. Features record these orbits.
Different restrictions in one orbit are NPN-equivalent, though their literal
truth tables may differ by output complement or remaining-variable relabeling.

## Feature conventions

ANF is computed by the Boolean Mobius transform. The zero function's degree is
reported as 0 by convention. Walsh W_f(a) sums (-1)^(f(x) XOR <a,x>).
Autocorrelation sums (-1)^(f(x) XOR f(x XOR a)). Influence is the fraction of
assignments on which flipping a variable changes the output; the equivalent
cofactor derivative fraction is used. Sensitivity counts such variables at
each assignment. Monotone means nondecreasing in every original input; unate
permits an individually chosen polarity for each variable.

Signed spectra, coordinate profiles, monotonicity, and raw weight are not all
invariant under the full NPN action in their unnormalized form. Interpret each
record with its explicit representative and transformation convention.

## Evidence boundaries

Independently verified DRAT establishes UNSAT of a specific CNF. It does not
verify the Python encoder or its completeness theorem. An observed simplification
of a witness is not a universal gate-elimination lower bound. Likewise, a
symmetric target does not imply the existence of a symmetric optimal circuit.
The repository contains no claimed new Boolean-function lemmas or new bounds.

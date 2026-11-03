"""Manual tests. No CI workflow is installed, and these are NOT run on creation.

Small exhaustive differential checks compare encodings against independent
truth-table chain enumeration, plus exact minima for all two-input functions.
"""
import unittest
from itertools import combinations_with_replacement
from dataclasses import replace
from aig_exact.encode import Instance, Options
from aig_exact.circuit import simulate

try:
    from pysat.solvers import Solver
except ImportError:
    Solver = None


def reachable_functions(n, k):
    size = 1 << n
    mask = (1 << size) - 1
    primary = tuple([0] + [sum(((t >> i) & 1) << t for t in range(size)) for i in range(n)])
    states = {primary}
    reached = set(primary) | {x ^ mask for x in primary}
    for _ in range(k):
        new_states = set()
        for state in states:
            signed = set(state) | {x ^ mask for x in state}
            for a, b in combinations_with_replacement(signed, 2):
                value = a & b
                reached.update((value, value ^ mask))
                new_states.add(state + (value,))
        states = new_states
    return reached


@unittest.skipIf(Solver is None, 'Install .[sat] to run encoding checks')
class EncodingTests(unittest.TestCase):
    def sat(self, n, f, k, opt):
        inst = Instance(n, f, k, opt)
        with Solver(name='cadical195', bootstrap_with=inst.cnf.clauses) as solver:
            status = solver.solve()
            if status:
                self.assertEqual(simulate(inst.decode(solver.get_model())), f)
            return status

    def test_exhaustive_small_budgets(self):
        for k in range(3):
            reachable = reachable_functions(2, k)
            for encoding in ('ssv', 'msv', 'ditt'):
                for cardinality in ('sequential', 'pairwise'):
                    for ordered in (False, True):
                        for f in range(16):
                            opt = Options(encoding=encoding, cardinality=cardinality, fanin_order=ordered)
                            self.assertEqual(self.sat(2, f, k, opt), f in reachable,
                                             (f, k, opt))

    def test_every_two_input_minimum_and_optional_pruning(self):
        # Every nonconstant/nonliteral function except XOR/XNOR is a signed AND.
        zero_cost = {0, 15, 0xa, 0x5, 0xc, 0x3}
        for encoding in ('ssv', 'msv', 'ditt'):
            base = Options(encoding=encoding)
            variants = [base, replace(base, no_trivial=True), replace(base, no_duplicates=True),
                        replace(base, all_used=True), replace(base, target_symmetry=True),
                        replace(base, no_trivial=True, no_duplicates=True, all_used=True, target_symmetry=True)]
            for opt in variants:
                for f in range(16):
                    cost = 0 if f in zero_cost else 3 if f in (0x6, 0x9) else 1
                    for k in range(cost + 1):
                        self.assertEqual(self.sat(2, f, k, opt), k == cost, (f, k, opt))

    def test_constant_and_zero_input_boundaries(self):
        for encoding in ('ssv', 'msv', 'ditt'):
            for f in (0, 1):
                for k in (0, 1):
                    self.assertTrue(self.sat(0, f, k, Options(encoding=encoding)))

"""Differential checks for Sections III-A--D of Haaswijk et al. (2020)."""
import itertools
import unittest
from aig_exact.cnf import CNF
from aig_exact.encode import Instance, Options
from aig_exact import circuit
try:
    from pysat.solvers import Solver
except ImportError:
    Solver = None


def enumerated_minima(n, max_gates):
    """Independent integer truth-table enumeration of arbitrary binary gates."""
    mask = (1 << (1 << n)) - 1
    inputs = tuple(sum(((t >> j) & 1) << t for t in range(1 << n)) for j in range(n))
    minima = {0: 0, mask: 0}
    for value in inputs:
        minima[value] = minima[value ^ mask] = 0
    states = {inputs}
    for gates in range(1, max_gates + 1):
        next_states = set()
        for state in states:
            for a, b in itertools.combinations(state, 2):
                regions = ((~a & b) & mask, (a & ~b) & mask, a & b)
                for bits in range(8):
                    value = 0
                    for bit, region in enumerate(regions):
                        if (bits >> bit) & 1:
                            value |= region
                    minima.setdefault(value, gates)
                    minima.setdefault(value ^ mask, gates)
                    next_states.add(state + (value,))
        states = next_states
    return minima


@unittest.skipIf(Solver is None, 'Install .[sat]')
class PaperEncodings(unittest.TestCase):
    def solve(self, n, f, k, encoding='ssv', symmetries=''):
        instance = Instance(n, f, k, Options(model='paper', encoding=encoding, symmetries=symmetries))
        with Solver(name='cadical195', bootstrap_with=instance.cnf.clauses) as solver:
            sat = solver.solve()
            if sat:
                witness = instance.decode(solver.get_model())
                self.assertEqual(circuit.simulate(witness), f)
                self.assertEqual(circuit.simulate(circuit.compact(witness)), f)
            return sat

    def test_unary_counter_all_assignments(self):
        for size in range(7):
            cnf = CNF()
            inputs = [cnf.var(f'in:{i}') for i in range(size)]
            cnf.exactly_two(inputs)
            with Solver(name='cadical195', bootstrap_with=cnf.clauses) as solver:
                for bits in itertools.product((0, 1), repeat=size):
                    self.assertEqual(solver.solve(assumptions=[v if bit else -v for v, bit in zip(inputs, bits)]),
                                     sum(bits) == 2)

    def test_variable_families(self):
        for encoding, selections in [('ssv', 9), ('msv', 7), ('ditt', 14)]:
            inst = Instance(3, 0x96, 2, Options(model='paper', encoding=encoding))
            names = inst.cnf.names
            self.assertEqual(sum(name.startswith('s:') for name in names), selections)
            self.assertEqual(sum(name.startswith('f:') for name in names), 6)
            self.assertEqual(sum(name.startswith('x:') for name in names), 42 if encoding == 'ditt' else 14)
            self.assertFalse(any(name.endswith(':00') for name in names if name.startswith('f:')))

    def test_all_two_input_minima_all_symmetries(self):
        minima = enumerated_minima(2, 1)
        self.assertEqual(len(minima), 16)
        for mask in range(64):
            symmetries = ''.join(s for i, s in enumerate('NARCOS') if (mask >> i) & 1)
            for encoding in ('ssv', 'msv', 'ditt'):
                for f, minimum in minima.items():
                    for k in range(minimum + 1):
                        self.assertEqual(self.solve(2, f, k, encoding, symmetries), k == minimum,
                                         (encoding, symmetries, f, k))

    def test_three_input_differential(self):
        minima = enumerated_minima(3, 3)
        for encoding in ('ssv', 'msv', 'ditt'):
            for f in range(256):
                for k in range(4):
                    expected = f in minima and minima[f] <= k
                    # At k=0 direct primary/constant outputs are handled separately.
                    self.assertEqual(self.solve(3, f, k, encoding), expected, (encoding, f, k))
        # Exercise interactions on optimal multi-step chains for every NPN class.
        from aig_exact.boolean import representatives
        for f in representatives(3):
            # Exhaustive enumeration rules out <=3 for remaining classes;
            # a simulated four-step witness establishes the matching upper bound.
            k = minima.get(f, 4)
            for mask in range(64):
                symmetries = ''.join(s for i, s in enumerate('NARCOS') if (mask >> i) & 1)
                for encoding in ('ssv', 'msv', 'ditt'):
                    self.assertTrue(self.solve(3, f, k, encoding, symmetries), (encoding, symmetries, f, k))
                    if k:
                        self.assertFalse(self.solve(3, f, k - 1, encoding, symmetries))

    def test_each_symmetry_excludes_its_pattern(self):
        def satisfiable(symmetry, assumptions):
            inst = Instance(3, 0, 3, Options(model='paper', symmetries=symmetry))
            by_name = {name: i + 1 for i, name in enumerate(inst.cnf.names)}
            literals = [by_name[name] if value else -by_name[name] for name, value in assumptions]
            with Solver(name='cadical195', bootstrap_with=inst.cnf.clauses) as solver:
                return solver.solve(assumptions=literals)
        patterns = {
            'N': [('f:4:01', False), ('f:4:10', False), ('f:4:11', False)],
            'A': [('g:1:4', True), ('g:1:6', False)],
            'R': [('s:4:1:2', True), ('s:5:1:4', True)],
            'C': [('s:4:2:3', True), ('s:5:1:2', True)],
            'O': [('s:4:1:2', True), ('s:5:1:2', True),
                  ('f:4:11', True), ('f:5:11', False)],
            'S': [('s:4:2:3', True)],
        }
        for flag, pattern in patterns.items():
            self.assertTrue(satisfiable('', pattern), flag)
            self.assertFalse(satisfiable(flag, pattern), flag)

    def test_model_boundary_and_legacy_options(self):
        self.assertTrue(self.solve(2, 0x6, 1))
        inst = Instance(2, 0x6, 1, Options())
        with Solver(name='cadical195', bootstrap_with=inst.cnf.clauses) as solver:
            self.assertFalse(solver.solve())
        with self.assertRaises(ValueError):
            Options(model='aig', symmetries='R')
        with self.assertRaises(ValueError):
            Options(model='paper', target_symmetry=True)
        with self.assertRaises(ValueError):
            Options(model='paper', no_duplicates=True)

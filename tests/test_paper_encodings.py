"""Differential checks for Sections III-A--D of Haaswijk et al. (2020)."""
import itertools
import unittest
from aig_exact.cnf import CNF
from aig_exact.encode import Instance, Options
from aig_exact import circuit
from cadical_helper import CADICAL, solve


def enumerated_minima(n, max_gates):
    """Independent integer truth-table enumeration of signed AND gates."""
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
                for value in (a & b, a | b, (~a) & b, a & (~b)):
                    minima.setdefault(value, gates)
                    minima.setdefault(value ^ mask, gates)
                    next_states.add(state + (value,))
        states = next_states
    return minima


@unittest.skipIf(CADICAL is None, 'Put CaDiCaL 3+ on PATH to run encoding checks')
class PaperEncodings(unittest.TestCase):
    def solve(self, n, f, k, encoding='ssv', symmetries=''):
        instance = Instance(n, f, k, Options(model='paper-aig', encoding=encoding, symmetries=symmetries))
        sat, model = solve(instance.cnf)
        if sat:
            witness = instance.decode(model)
            self.assertEqual(circuit.simulate(witness), f)
            self.assertEqual(circuit.simulate(circuit.compact(witness)), f)
        return sat

    def test_unary_counter_all_assignments(self):
        for size in range(7):
            cnf = CNF()
            inputs = [cnf.var(f'in:{i}') for i in range(size)]
            cnf.exactly_two(inputs)
            for bits in itertools.product((0, 1), repeat=size):
                assumptions = [v if bit else -v for v, bit in zip(inputs, bits)]
                self.assertEqual(solve(cnf, assumptions)[0], sum(bits) == 2)

    def test_variable_families(self):
        for encoding, selections in [('ssv', 9), ('msv', 7), ('ditt', 14)]:
            inst = Instance(3, 0x96, 2, Options(model='paper-aig', encoding=encoding))
            names = inst.cnf.names
            self.assertEqual(sum(name.startswith('s:') for name in names), selections)
            self.assertEqual(sum(name.startswith('f:') for name in names), 6)
            self.assertEqual(sum(name.startswith('x:') for name in names), 42 if encoding == 'ditt' else 14)
            self.assertFalse(any(name.endswith(':00') for name in names if name.startswith('f:')))

    def test_all_two_input_minima_all_symmetries(self):
        minima = enumerated_minima(2, 3)
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
                for k in range(min(minima.get(f, 3), 3) + 1):
                    expected = f in minima and minima[f] <= k
                    # At k=0 direct primary/constant outputs are handled separately.
                    self.assertEqual(self.solve(3, f, k, encoding), expected, (encoding, f, k))
        # Exercise interactions on optimal multi-step chains for every NPN class.
        from aig_exact.boolean import representatives
        for f in representatives(3):
            # For larger minima use the independent signed-wire AIG encoder.
            k = minima.get(f)
            if k is None:
                k = next(size for size in range(4, 7)
                         if solve(Instance(3, f, size, Options()).cnf)[0])
            for mask in range(64):
                symmetries = ''.join(s for i, s in enumerate('NARCOS') if (mask >> i) & 1)
                for encoding in ('ssv', 'msv', 'ditt'):
                    self.assertTrue(self.solve(3, f, k, encoding, symmetries), (encoding, symmetries, f, k))
                    if k:
                        self.assertFalse(self.solve(3, f, k - 1, encoding, symmetries))

    def test_each_symmetry_excludes_its_pattern(self):
        def satisfiable(encoding, symmetry, pairs, values):
            inst = Instance(3, 0x88, 3, Options(model='paper-aig', encoding=encoding, symmetries=symmetry))
            by_name = {name: i + 1 for i, name in enumerate(inst.cnf.names)}
            literals = [by_name[name] if value else -by_name[name] for name, value in values]
            for step, pair in pairs:
                literals.extend(inst.pairs[step][pair])
            return solve(inst.cnf, literals)[0]

        patterns = {
            'A': ([], [('g:1:4', True), ('g:1:6', False)]),
            'R': ([(4, (1, 2)), (5, (1, 4))], []),
            'C': ([(4, (2, 3)), (5, (1, 2))], []),
            'O': ([(4, (1, 2)), (5, (1, 2))], [('f:4:11', True), ('f:5:11', False)]),
            'S': ([(4, (2, 3))], []),
        }
        for encoding in ('ssv', 'msv', 'ditt'):
            for flag, (pairs, values) in patterns.items():
                with self.subTest(encoding=encoding, flag=flag):
                    self.assertTrue(satisfiable(encoding, '', pairs, values))
                    self.assertFalse(satisfiable(encoding, flag, pairs, values))

    def test_model_boundary_and_legacy_options(self):
        with self.assertRaises(ValueError):
            Options(model='paper')
        self.assertFalse(self.solve(2, 0x6, 1))
        self.assertTrue(self.solve(2, 0x6, 3))
        inst = Instance(2, 0x6, 1, Options())
        self.assertFalse(solve(inst.cnf)[0])
        with self.assertRaises(ValueError):
            Options(model='aig', symmetries='R')
        with self.assertRaises(ValueError):
            Options(model='paper-aig', target_symmetry=True)
        with self.assertRaises(ValueError):
            Options(model='paper-aig', no_duplicates=True)

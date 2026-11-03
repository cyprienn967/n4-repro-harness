import unittest
from aig_exact.circuit import simulate, compact, restricted, aag, analyze


# XOR: ~(x & y) & ~(~x & ~y)
XOR = dict(n=2, gates=[[2, 4], [3, 5], [7, 9]], output=10)


class CircuitTests(unittest.TestCase):
    def test_scalar_simulation(self):
        self.assertEqual(simulate(XOR), 0x6)
        self.assertEqual(analyze(XOR)['depth'], 2)
        self.assertEqual(len(compact(XOR)['gates']), 3)
        self.assertTrue(aag(XOR).startswith('aag 5 2 0 1 3\n'))

    def test_dead_gate(self):
        c = dict(n=2, gates=[[2, 4]], output=2)
        self.assertEqual(len(compact(c)['gates']), 0)
        self.assertEqual(simulate(compact(c)), 0xa)

    def test_restriction(self):
        self.assertEqual(simulate(restricted(XOR, 0, 0)), 0xc)
        self.assertEqual(simulate(restricted(XOR, 0, 1)), 0x3)
        self.assertEqual(len(restricted(XOR, 0, 0)['gates']), 0)

    def test_invalid_topology(self):
        with self.assertRaises(ValueError):
            simulate(dict(n=1, gates=[[2, 4]], output=4))

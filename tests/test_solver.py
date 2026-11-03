import unittest
from aig_exact.solver import parse_output, parse_stats
from aig_exact.cnf import CNF


class SolverTests(unittest.TestCase):
    def test_status_and_model(self):
        self.assertEqual(parse_output('s SATISFIABLE\nv 1 -2 0\n', 10), ('SAT', [1, -2]))
        self.assertEqual(parse_output('s UNSATISFIABLE\n', 20), ('UNSAT', []))
        self.assertEqual(parse_output('s SATISFIABLE\n', 20)[0], 'ERROR')
        self.assertEqual(parse_output('s SATISFIABLE\ns UNSATISFIABLE\n', 10)[0], 'ERROR')
        self.assertEqual(parse_output('nothing\n', 1)[0], 'ERROR')
        self.assertEqual(parse_output('s UNKNOWN\n', 0)[0], 'UNKNOWN')

    def test_stats(self):
        stats = parse_stats('c conflicts: 1,200\nc decisions: 3000\nc propagations: 4000\n')
        self.assertEqual(stats['conflicts'], 1200)
        self.assertEqual(stats['decisions'], 3000)

    def test_empty_cardinality(self):
        c = CNF()
        c.exactly_one([])
        self.assertIn([], c.clauses)

"""Explicitly opt-in full four-input partition check."""
import os
import unittest
from aig_exact.boolean import representatives, orbit


@unittest.skipUnless(os.environ.get('AIG_EXACT_FULL_TESTS') == '1', 'Set AIG_EXACT_FULL_TESTS=1')
class FullNPNTests(unittest.TestCase):
    def test_full_partition(self):
        reps = list(representatives(4))
        self.assertEqual(len(reps), 222)
        sets = [orbit(4, f) for f in reps]
        self.assertEqual(sum(map(len, sets)), 65536)
        self.assertEqual(len(set.union(*sets)), 65536)

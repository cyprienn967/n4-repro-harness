import unittest
from aig_exact.boolean import (inputs, transform, orbit, canonical, stabilizer,
                               representatives, cofactor, features, mask)


class BooleanTests(unittest.TestCase):
    def test_convention(self):
        self.assertEqual(inputs(2), [0xa, 0xc])
        self.assertEqual(transform(2, 0xa, (1, 0)), 0xc)
        self.assertEqual(transform(2, 0xa, (0, 1), 1), 0x5)
        self.assertEqual(transform(2, 0xa, (0, 1), 0, 1), 0x5)

    def test_group_and_partition(self):
        for n, expected in [(0, 1), (1, 2), (2, 4), (3, 14)]:
            reps = list(representatives(n))
            self.assertEqual(len(reps), expected)
            sets = [orbit(n, f) for f in reps]
            self.assertEqual(sum(map(len, sets)), 1 << (1 << n))
            self.assertEqual(len(set.union(*sets)), 1 << (1 << n))
        row = features(4, 0)
        self.assertEqual(row['npn_group_size'], 768)
        self.assertEqual(row['stabilizer_size'], 384)
        self.assertEqual(row['orbit_size'], 2)

    def test_cofactors_and_parity(self):
        parity = 0x96
        for i in range(3):
            self.assertEqual(cofactor(3, parity, i, 0), 0x6)
            self.assertEqual(cofactor(3, parity, i, 1), 0x9)
        row = features(3, parity)
        self.assertEqual(row['degree'], 1)
        self.assertEqual(row['influences'], [1, 1, 1])
        self.assertEqual(row['max_sensitivity'], 3)
        self.assertEqual(row['restriction_orbits'], [((0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1))])

    def test_orbit_stabilizer(self):
        for f in range(16):
            self.assertEqual(len(orbit(2, f)) * len(stabilizer(2, f)), 16)
            self.assertEqual(canonical(2, f), canonical(2, f ^ mask(2)))

import unittest

from hdpcg.random_utils import rng_from_seed


class TestRandom(unittest.TestCase):
    def test_mulberry32_reproducible(self):
        a = rng_from_seed('seed-x')
        b = rng_from_seed('seed-x')
        seq_a = [a.random() for _ in range(10)]
        seq_b = [b.random() for _ in range(10)]
        self.assertEqual(seq_a, seq_b)

    def test_mulberry32_changes_with_seed(self):
        a = rng_from_seed('seed-a')
        b = rng_from_seed('seed-b')
        self.assertNotEqual([a.random() for _ in range(5)], [b.random() for _ in range(5)])


if __name__ == '__main__':
    unittest.main()

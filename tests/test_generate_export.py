import unittest

from hdpcg.etg_core import NODE_TYPES, normalize_etg
from hdpcg.exporter import build_export_package
from hdpcg.generator import generate_level
from hdpcg.random_utils import rng_from_seed


class TestGenerateAndExport(unittest.TestCase):
    def test_generate_and_export_schema(self):
        etg = normalize_etg({
            'nodes': [
                {'id': 'N0', 'type': NODE_TYPES['START'], 'intensity': 0.1},
                {'id': 'N1', 'type': NODE_TYPES['NONE'], 'intensity': 0.2},
                {'id': 'N2', 'type': NODE_TYPES['GOAL'], 'intensity': 0.1},
            ],
            'edges': [
                {'id': 'E0', 'from': 'N0', 'to': 'N1', 'length': 20},
                {'id': 'E1', 'from': 'N1', 'to': 'N2', 'length': 20},
            ],
        })
        config = {
            'seed': 't0',
            'generatorMode': 'lane',
            'difficulty': 0.45,
            'length': 5,
            'branchChance': 0.2,
            'keyLock': False,
        }
        level = generate_level(etg, config, rng_from_seed('t0-geo'))
        self.assertIn('platforms', level)
        self.assertIn('mapping', level)
        self.assertIn('anchors', level)
        self.assertTrue(level['start'])
        self.assertTrue(level['goal'])

        pkg = build_export_package(level, {'status': 'ok', 'issues': [], 'fixes': [], 'warnings': []})
        self.assertIn('etg', pkg)
        self.assertIn('level', pkg)
        self.assertIn('mapping', pkg)
        self.assertIn('time_expanded', pkg)
        self.assertIn('validation', pkg)
        self.assertIn('component_generation', pkg['meta'])
        self.assertIn('component_generation', pkg['constraints'])


if __name__ == '__main__':
    unittest.main()

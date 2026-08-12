import unittest

from types import SimpleNamespace
from unittest.mock import patch

from hdpcg.etg_core import NODE_TYPES, normalize_etg
from hdpcg.generator import generate_level
from hdpcg.random_utils import rng_from_seed
from hdpcg.topology import key_lock_order_check, latent_shortcut_check, progression_structure_check, validate_global_topology


class TestTopology(unittest.TestCase):
    def test_progression_structure_rejects_shortcut(self):
        etg = normalize_etg({
            'nodes': [
                {'id': 'N0', 'type': NODE_TYPES['START'], 'intensity': 0.1},
                {'id': 'N1', 'type': NODE_TYPES['PLATFORM'], 'intensity': 0.4},
                {'id': 'N2', 'type': NODE_TYPES['GOAL'], 'intensity': 0.1},
            ],
            'edges': [
                {'id': 'E0', 'from': 'N0', 'to': 'N1', 'length': 18},
                {'id': 'E1', 'from': 'N1', 'to': 'N2', 'length': 18},
            ],
        })
        first_hit = {
            'N0': {'time': 0, 'phase': 0},
            'N2': {'time': 1, 'phase': 0},
            'N1': {'time': 3, 'phase': 0},
        }
        report = progression_structure_check(etg, ['N0', 'N2'], first_hit)
        self.assertFalse(report['ok'])
        reasons = {issue['reason'] for issue in report['issues']}
        self.assertIn('unexpected_path_transition', reasons)
        self.assertIn('premature_node_reachability', reasons)
        self.assertIn('required_region_bypassed', reasons)

    def test_progression_structure_accepts_valid_branch_route(self):
        etg = normalize_etg({
            'nodes': [
                {'id': 'S', 'type': NODE_TYPES['START'], 'intensity': 0.1},
                {'id': 'A', 'type': NODE_TYPES['PLATFORM'], 'intensity': 0.4},
                {'id': 'B', 'type': NODE_TYPES['PLATFORM'], 'intensity': 0.4},
                {'id': 'G', 'type': NODE_TYPES['GOAL'], 'intensity': 0.1},
            ],
            'edges': [
                {'id': 'E0', 'from': 'S', 'to': 'A', 'length': 10},
                {'id': 'E1', 'from': 'S', 'to': 'B', 'length': 10},
                {'id': 'E2', 'from': 'A', 'to': 'G', 'length': 10},
                {'id': 'E3', 'from': 'B', 'to': 'G', 'length': 10},
            ],
        })
        first_hit = {
            'S': {'time': 0, 'phase': 0},
            'A': {'time': 2, 'phase': 0},
            'B': {'time': 3, 'phase': 0},
            'G': {'time': 5, 'phase': 0},
        }
        report = progression_structure_check(etg, ['S', 'A', 'G'], first_hit)
        self.assertTrue(report['ok'])

    def test_progression_structure_rejects_equal_time_chain(self):
        etg = normalize_etg({
            'nodes': [
                {'id': 'S', 'type': NODE_TYPES['START'], 'intensity': 0.1},
                {'id': 'M', 'type': NODE_TYPES['PLATFORM'], 'intensity': 0.4},
                {'id': 'G', 'type': NODE_TYPES['GOAL'], 'intensity': 0.1},
            ],
            'edges': [
                {'id': 'E0', 'from': 'S', 'to': 'M', 'length': 10},
                {'id': 'E1', 'from': 'M', 'to': 'G', 'length': 10},
            ],
        })
        first_hit = {
            'S': {'time': 0, 'phase': 0},
            'M': {'time': 1, 'phase': 0},
            'G': {'time': 1, 'phase': 0},
        }
        report = progression_structure_check(etg, ['S', 'M', 'G'], first_hit)
        self.assertFalse(report['ok'])
        self.assertIn('premature_node_reachability', {issue['reason'] for issue in report['issues']})

    def test_key_lock_rejects_same_tick_across_phases(self):
        etg = normalize_etg({
            'nodes': [
                {'id': 'S', 'type': NODE_TYPES['START'], 'intensity': 0.1},
                {'id': 'K', 'type': NODE_TYPES['KEY'], 'key_id': 'gold', 'intensity': 0.3},
                {'id': 'L', 'type': NODE_TYPES['LOCK'], 'requires_key_id': 'gold', 'intensity': 0.5},
                {'id': 'G', 'type': NODE_TYPES['GOAL'], 'intensity': 0.1},
            ],
            'edges': [
                {'id': 'E0', 'from': 'S', 'to': 'K', 'length': 10},
                {'id': 'E1', 'from': 'K', 'to': 'L', 'length': 10},
                {'id': 'E2', 'from': 'L', 'to': 'G', 'length': 10},
            ],
        })
        report = key_lock_order_check(etg, ['S', 'K', 'L', 'G'], {
            'S': {'time': 0, 'phase': 0},
            'K': {'time': 1, 'phase': 0},
            'L': {'time': 1, 'phase': 1},
            'G': {'time': 2, 'phase': 1},
        })
        self.assertFalse(report['ok'])
        self.assertEqual(report['issues'][0]['reason'], 'key_not_before_lock')

    def test_latent_shortcut_checks_only_mandatory_nodes(self):
        etg = normalize_etg({
            'nodes': [
                {'id': 'S', 'type': NODE_TYPES['START'], 'intensity': 0.1},
                {'id': 'A', 'type': NODE_TYPES['PLATFORM'], 'intensity': 0.3},
                {'id': 'B', 'type': NODE_TYPES['PLATFORM'], 'intensity': 0.3},
                {'id': 'M', 'type': NODE_TYPES['PLATFORM'], 'intensity': 0.4},
                {'id': 'G', 'type': NODE_TYPES['GOAL'], 'intensity': 0.1},
            ],
            'edges': [
                {'id': 'E0', 'from': 'S', 'to': 'A', 'length': 10},
                {'id': 'E1', 'from': 'S', 'to': 'B', 'length': 10},
                {'id': 'E2', 'from': 'A', 'to': 'M', 'length': 10},
                {'id': 'E3', 'from': 'B', 'to': 'M', 'length': 10},
                {'id': 'E4', 'from': 'M', 'to': 'G', 'length': 10},
            ],
        })
        markers = {node_id: {f'{node_id}-cell'} for node_id in ('S', 'A', 'B', 'M', 'G')}
        with patch('hdpcg.topology._goal_reachable_avoiding', return_value={'reached': False, 'expanded': 1, 'truncated': False}) as search:
            report = latent_shortcut_check({'platforms': []}, etg, SimpleNamespace(cellSize=1.0), markers, {})
        self.assertTrue(report['ok'])
        self.assertEqual([item['required_node'] for item in report['checks']], ['M'])
        self.assertEqual(search.call_count, 1)

    def test_global_topology_rejects_direct_shortcut(self):
        etg = normalize_etg({
            'nodes': [
                {'id': 'S', 'type': NODE_TYPES['START'], 'intensity': 0.1},
                {'id': 'M', 'type': NODE_TYPES['PLATFORM'], 'intensity': 0.4},
                {'id': 'G', 'type': NODE_TYPES['GOAL'], 'intensity': 0.1},
            ],
            'edges': [
                {'id': 'E0', 'from': 'S', 'to': 'M', 'length': 18},
                {'id': 'E1', 'from': 'M', 'to': 'G', 'length': 18},
            ],
        })
        level = generate_level(etg, {
            'seed': 'shortcut', 'generatorMode': 'lane', 'difficulty': 0.5,
            'length': 5, 'branchChance': 0.0, 'keyLock': False,
        }, rng_from_seed('shortcut-geo'))
        start = level['anchors']['S']['exit']
        goal = level['anchors']['G']['entry']
        level['platforms'].append({
            'id': 'direct_shortcut',
            'pos': {'x': (start['x'] + goal['x']) / 2, 'y': min(start['y'], goal['y']) - 0.5, 'z': (start['z'] + goal['z']) / 2},
            'size': {'x': abs(goal['x'] - start['x']) + 8, 'y': 1, 'z': abs(goal['z'] - start['z']) + 8},
            'kind': 'static',
        })
        report = validate_global_topology(level, etg, {
            'maxTime': 80, 'maxStates': 50000, 'maxJumpOffsets': 80,
            'allowJump': False, 'allowDrop': False,
        })
        self.assertFalse(report['ok'])
        self.assertTrue(report['goal_reachable'])
        self.assertEqual(report['reason'], 'topology_violation')

    def test_global_topology_report(self):
        etg = normalize_etg({
            'nodes': [
                {'id': 'N0', 'type': NODE_TYPES['START'], 'intensity': 0.1},
                {'id': 'N1', 'type': NODE_TYPES['PLATFORM'], 'intensity': 0.4},
                {'id': 'N2', 'type': NODE_TYPES['GOAL'], 'intensity': 0.1},
            ],
            'edges': [
                {'id': 'E0', 'from': 'N0', 'to': 'N1', 'length': 18},
                {'id': 'E1', 'from': 'N1', 'to': 'N2', 'length': 18},
            ],
        })

        level = generate_level(etg, {
            'seed': 'tp',
            'generatorMode': 'lane',
            'difficulty': 0.5,
            'length': 5,
            'branchChance': 0.0,
            'keyLock': False,
        }, rng_from_seed('tp-geo'))

        report = validate_global_topology(level, etg, {'maxTime': 80, 'maxStates': 12000, 'maxJumpOffsets': 80, 'allowJump': False, 'allowDrop': False})
        self.assertIn('ok', report)
        self.assertIn('goal_reachable', report)
        self.assertIn('observed_etg', report)
        self.assertIn('comparison', report)
        self.assertIn('comparison', report)
        self.assertTrue(report.get('search', {}).get('path_length_states', 0) >= 0)


if __name__ == '__main__':
    unittest.main()

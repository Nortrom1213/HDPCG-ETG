import unittest

from hdpcg.topology import validate_local_topology


class TestLocalTopology(unittest.TestCase):
    def test_local_topology_rejects_forbidden_marker(self):
        level = {
            'meta': {},
            'etg': None,
            'platforms': [
                {
                    'id': 'P0',
                    'pos': {'x': 0.0, 'y': 0.0, 'z': 0.0},
                    'size': {'x': 10.0, 'y': 1.0, 'z': 10.0},
                    'kind': 'static',
                    'motion': None,
                    'tags': [],
                    'node_id': 'A',
                }
            ],
            'enemies': [],
            'keys': [],
            'locks': [],
            'checkpoints': [],
            'start': {'x': 0.0, 'y': 0.5, 'z': 0.0},
            'goal': {'x': 2.0, 'y': 0.5, 'z': 0.0},
            'mapping': {'node': {}, 'edge': {}},
            'anchors': {
                'A': {'entry': {'x': 0.0, 'y': 0.5, 'z': 0.0}, 'exit': {'x': 0.0, 'y': 0.5, 'z': 0.0}},
                'B': {'entry': {'x': 2.0, 'y': 0.5, 'z': 0.0}, 'exit': {'x': 2.0, 'y': 0.5, 'z': 0.0}},
                'C': {'entry': {'x': 2.0, 'y': 0.5, 'z': 0.0}, 'exit': {'x': 2.0, 'y': 0.5, 'z': 0.0}},
            },
        }

        etg = {
            'version': 2,
            'nodes': [
                {'id': 'A', 'types': ['Start'], 'type': 'Start', 'intensity': 0.1},
                {'id': 'B', 'types': ['Goal'], 'type': 'Goal', 'intensity': 0.1},
                {'id': 'C', 'types': ['None'], 'type': 'None', 'intensity': 0.1},
            ],
            'edges': [
                {'id': 'E0', 'from': 'A', 'to': 'B', 'length': 10},
            ],
            'meta': {'defaultSpeed': 7.5},
        }

        bounds_delta = {
            'A': {
                'min': {'x': -5.0, 'y': -1.0, 'z': -5.0},
                'max': {'x': 5.0, 'y': 1.0, 'z': 5.0},
            }
        }

        report = validate_local_topology(
            {
                'level': level,
                'etg': etg,
                'fromId': 'A',
                'toId': 'B',
                'boundsDelta': bounds_delta,
                'allowSiblingTolerance': False,
                'maxTime': 40,
                'maxStates': 15000,
                'maxQueue': 12000,
                'maxJumpOffsets': 220,
            }
        )

        self.assertFalse(report.get('ok', True))
        self.assertEqual(report.get('reason'), 'forbidden_reached')


if __name__ == '__main__':
    unittest.main()

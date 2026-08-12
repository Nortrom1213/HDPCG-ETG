import unittest

from hdpcg.etg_qd_selection import compute_etg_descriptor


class TestEtgQdSelection(unittest.TestCase):
    def test_challenge_ratio_uses_non_terminal_nodes_and_includes_keys(self):
        etg = {
            "nodes": [
                {"id": "S", "type": "Start"},
                {"id": "K", "type": "Key", "key_id": "k1"},
                {"id": "P", "type": "Platform"},
                {"id": "G", "type": "Goal"},
            ],
            "edges": [
                {"id": "E0", "from": "S", "to": "K", "length": 10},
                {"id": "E1", "from": "K", "to": "P", "length": 10},
                {"id": "E2", "from": "P", "to": "G", "length": 10},
            ],
        }
        descriptor = compute_etg_descriptor(etg)
        self.assertEqual(descriptor["challenge_ratio"], 0.5)


if __name__ == "__main__":
    unittest.main()

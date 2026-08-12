import unittest

from hdpcg.etg_core import NODE_TYPES, compute_canonical_route, normalize_etg, validate_etg
from hdpcg.topology import compare_etg


def _nodes() -> list[dict]:
    return [
        {"id": "S", "type": NODE_TYPES["START"], "intensity": 0.1},
        {"id": "A", "type": NODE_TYPES["PLATFORM"], "intensity": 0.4},
        {"id": "G", "type": NODE_TYPES["GOAL"], "intensity": 0.1},
    ]


class TestEtgDirectionality(unittest.TestCase):
    def test_validation_rejects_self_loops_and_parallel_ordered_pairs(self):
        etg = normalize_etg(
            {
                "nodes": _nodes(),
                "edges": [
                    {"id": "E0", "from": "S", "to": "A", "length": 10},
                    {"id": "E1", "from": "S", "to": "A", "length": 12},
                    {"id": "E2", "from": "A", "to": "A", "length": 4},
                    {"id": "E2", "from": "A", "to": "G", "length": 10},
                ],
            }
        )
        report = validate_etg(etg)
        self.assertFalse(report.ok)
        self.assertTrue(any("parallel edge" in issue for issue in report.issues))
        self.assertTrue(any("self-loop" in issue for issue in report.issues))
        self.assertTrue(any("duplicate edge id" in issue for issue in report.issues))

    def test_canonical_route_does_not_reverse_edges(self):
        etg = normalize_etg(
            {
                "nodes": _nodes(),
                "edges": [
                    {"id": "E0", "from": "A", "to": "S", "length": 10},
                    {"id": "E1", "from": "G", "to": "A", "length": 10},
                ],
            }
        )
        self.assertFalse(compute_canonical_route(etg)["ok"])

    def test_fidelity_distinguishes_reversed_edges(self):
        expected = normalize_etg(
            {
                "nodes": _nodes(),
                "edges": [
                    {"id": "E0", "from": "S", "to": "A", "length": 10},
                    {"id": "E1", "from": "A", "to": "G", "length": 10},
                ],
            }
        )
        observed = normalize_etg(
            {
                "nodes": _nodes(),
                "edges": [
                    {"id": "O0", "from": "A", "to": "S", "length": 10},
                    {"id": "O1", "from": "G", "to": "A", "length": 10},
                ],
            }
        )
        report = compare_etg(expected, observed, ["S", "A", "G"], ["S", "A", "G"])
        self.assertEqual(report["edge"]["f1"], 0.0)


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from hdpcg.evaluate import _progression_balance, compute_paper_composites, compute_signature_diversity, evaluate_level_quality


class TestPaperMetrics(unittest.TestCase):
    def test_composite_formulas(self):
        scores = compute_paper_composites(
            node_coverage=0.5,
            route_length_agreement=0.75,
            topology_validity=1.0,
            etg_fidelity=0.8,
            content_variation=0.6,
            event_balance=0.4,
            route_rhythm=0.2,
            playability=1.0,
            key_lock_consistency=0.5,
        )
        self.assertAlmostEqual(scores["controllability"], 0.70)
        self.assertAlmostEqual(scores["topological_consistency"], 0.90)
        self.assertAlmostEqual(scores["pacing_variation"], 0.43)
        self.assertAlmostEqual(scores["overall"], 0.7595)

    def test_topology_validity_requires_prerequisite_order(self):
        topology = {
            "ok": False,
            "goal_reachable": True,
            "key_lock_order": {"ok": False},
            "fidelity_score": 1.0,
            "comparison": {},
            "observed_node_sequence_path": ["S", "G"],
        }
        etg = {
            "nodes": [{"id": "S", "type": "Start"}, {"id": "G", "type": "Goal"}],
            "edges": [{"id": "E0", "from": "S", "to": "G", "length": 10}],
            "meta": {"defaultSpeed": 7.5},
        }
        level = {
            "anchors": {
                "S": {"entry": {"x": 0, "y": 0, "z": 0}},
                "G": {"entry": {"x": 10, "y": 0, "z": 0}},
            },
            "platforms": [],
            "meta": {},
        }
        with patch("hdpcg.evaluate.validate_global_topology", return_value=topology):
            report = evaluate_level_quality(level, etg)
        self.assertEqual(report["metrics"]["playability"]["score"], 1.0)
        self.assertEqual(report["metrics"]["key_lock_consistency"]["score"], 0.0)
        metric = report["metrics"]["topological_consistency"]
        self.assertEqual(metric["topology_validity"], 0.0)
        self.assertEqual(metric["score"], 0.5)

    def test_reachable_topology_violation_preserves_playability_and_key_lock(self):
        topology = {
            "ok": False,
            "goal_reachable": True,
            "key_lock_order": {"ok": True},
            "fidelity_score": 0.5,
            "comparison": {},
            "observed_node_sequence_path": ["S", "G"],
        }
        etg = {
            "nodes": [{"id": "S", "type": "Start"}, {"id": "G", "type": "Goal"}],
            "edges": [{"id": "E0", "from": "S", "to": "G", "length": 10}],
            "meta": {"defaultSpeed": 7.5},
        }
        level = {
            "anchors": {
                "S": {"entry": {"x": 0, "y": 0, "z": 0}},
                "G": {"entry": {"x": 10, "y": 0, "z": 0}},
            },
            "platforms": [],
            "meta": {},
        }
        with patch("hdpcg.evaluate.validate_global_topology", return_value=topology):
            report = evaluate_level_quality(level, etg)
        self.assertEqual(report["metrics"]["playability"]["score"], 1.0)
        self.assertEqual(report["metrics"]["key_lock_consistency"]["score"], 1.0)
        self.assertEqual(report["metrics"]["topological_consistency"]["topology_validity"], 1.0)

    def test_unreachable_level_keeps_independent_key_lock_score(self):
        topology = {
            "ok": False,
            "goal_reachable": False,
            "key_lock_order": {"ok": True},
            "fidelity_score": 0.0,
            "comparison": {},
            "observed_node_sequence_path": ["S"],
        }
        etg = {
            "nodes": [{"id": "S", "type": "Start"}, {"id": "G", "type": "Goal"}],
            "edges": [{"id": "E0", "from": "S", "to": "G", "length": 10}],
        }
        level = {
            "anchors": {
                "S": {"entry": {"x": 0, "y": 0, "z": 0}},
                "G": {"entry": {"x": 10, "y": 0, "z": 0}},
            },
            "platforms": [],
            "meta": {},
        }
        with patch("hdpcg.evaluate.validate_global_topology", return_value=topology):
            report = evaluate_level_quality(level, etg)
        self.assertEqual(report["metrics"]["playability"]["score"], 0.0)
        self.assertEqual(report["metrics"]["key_lock_consistency"]["score"], 1.0)
        self.assertEqual(report["metrics"]["topological_consistency"]["topology_validity"], 0.0)

    def test_diversity_is_batch_structural_spread(self):
        first = {
            "node_types": ["Start", "Jump", "Goal"],
            "component_families": ["linear"],
            "shape_vector": [0.1, 0.2, 0.3, 0.4],
        }
        second = {
            "node_types": ["Start", "Enemy", "Goal"],
            "component_families": ["arc", "island"],
            "shape_vector": [0.9, 0.7, 0.2, 0.1],
        }
        self.assertEqual(compute_signature_diversity([first, first])["score"], 0.0)
        self.assertGreater(compute_signature_diversity([first, second])["score"], 0.0)

    def test_balance_rewards_progression_spread(self):
        sequence = ["S", "A", "B", "C", "D", "G"]
        etg = {"nodes": [{"id": node_id, "type": "Platform"} for node_id in sequence]}
        spread_level = {
            "mapping": {
                "node": {
                    "A": {"enemies": ["e1"]},
                    "B": {"keys": ["k1"]},
                    "D": {"locks": ["l1"]},
                }
            }
        }
        concentrated_level = {
            "mapping": {"node": {"A": {"enemies": ["e1", "e2", "e3"]}}}
        }
        spread_score, _ = _progression_balance(spread_level, etg, sequence, 30.0, True)
        concentrated_score, _ = _progression_balance(concentrated_level, etg, sequence, 30.0, True)
        self.assertGreater(spread_score, concentrated_score)

    def test_route_rhythm_includes_elevation(self):
        topology = {
            "ok": True,
            "key_lock_order": {"ok": True},
            "fidelity_score": 1.0,
            "comparison": {},
            "observed_node_sequence_path": ["S", "A", "G"],
        }
        etg = {
            "nodes": [
                {"id": "S", "type": "Start"},
                {"id": "A", "type": "Platform"},
                {"id": "G", "type": "Goal"},
            ],
            "edges": [
                {"id": "E0", "from": "S", "to": "A", "length": 10},
                {"id": "E1", "from": "A", "to": "G", "length": 10},
            ],
        }
        base_level = {"platforms": [], "mapping": {"node": {}}, "meta": {}}
        flat = {
            **base_level,
            "anchors": {
                "S": {"entry": {"x": 0, "y": 0, "z": 0}},
                "A": {"entry": {"x": 10, "y": 0, "z": 0}},
                "G": {"entry": {"x": 20, "y": 0, "z": 0}},
            },
        }
        elevated = {
            **base_level,
            "anchors": {
                "S": {"entry": {"x": 0, "y": 0, "z": 0}},
                "A": {"entry": {"x": 10, "y": 3, "z": 0}},
                "G": {"entry": {"x": 20, "y": 0, "z": 0}},
            },
        }
        with patch("hdpcg.evaluate.validate_global_topology", return_value=topology):
            flat_report = evaluate_level_quality(flat, etg)
            elevated_report = evaluate_level_quality(elevated, etg)
        flat_components = flat_report["metrics"]["fun_proxy"]["components"]
        elevated_components = elevated_report["metrics"]["fun_proxy"]["components"]
        self.assertEqual(flat_components["elevation"], 0.0)
        self.assertGreater(elevated_components["elevation"], 0.0)
        self.assertGreater(elevated_components["route_rhythm"], flat_components["route_rhythm"])


if __name__ == "__main__":
    unittest.main()

import unittest

from hdpcg.component_rules import check_component_hard_constraints
from hdpcg.component_sampling import build_candidate_pool
from hdpcg.component_scoring import score_candidate, select_candidate_order
from hdpcg.components import list_node_families
from hdpcg.etg_core import NODE_TYPES
from hdpcg.random_utils import rng_from_seed


class TestComponentPipeline(unittest.TestCase):
    def test_node_family_order_is_stable(self):
        node = {"id": "N1", "types": [NODE_TYPES["JUMP"], NODE_TYPES["ENEMY"], NODE_TYPES["KEY"]]}
        families = list_node_families(node)
        self.assertEqual(families, sorted(families))

    def test_candidate_pool_sampling_bounds(self):
        edge = {"id": "E0", "from": "N0", "to": "N1", "length": 24}
        node = {"id": "N1", "types": [NODE_TYPES["JUMP"]], "intensity": 0.5}
        pool = build_candidate_pool(edge=edge, to_node=node, rng=rng_from_seed("pool"), pool_size=12)
        self.assertEqual(len(pool), 12)
        for candidate in pool:
            self.assertIn("connector", candidate)
            self.assertIn("node", candidate)
            connector = candidate["connector"]
            self.assertGreaterEqual(float(connector["lateralAmplitude"]), 0.2)
            self.assertLessEqual(float(connector["lateralAmplitude"]), 2.8)
            self.assertGreaterEqual(float(connector["verticalAmplitude"]), 0.15)
            self.assertLessEqual(float(connector["verticalAmplitude"]), 2.4)
            self.assertGreaterEqual(float(candidate["complexity"]), 0.0)
            self.assertLessEqual(float(candidate["complexity"]), 1.0)

    def test_hard_constraints_lock_and_length(self):
        lock_node = {"id": "L", "types": [NODE_TYPES["LOCK"]]}
        invalid_lock = {
            "connectorFamily": "linear_bridge",
            "nodeFamily": "open_room",
            "connector": {},
            "node": {},
            "complexity": 0.5,
        }
        res_lock = check_component_hard_constraints(invalid_lock, edge={"length": 20}, to_node=lock_node)
        self.assertFalse(res_lock["ok"])
        self.assertIn("lock_node_family_mismatch", res_lock["issues"])

        short_edge = {
            "connectorFamily": "vertical_lift_bridge",
            "nodeFamily": "goal_platform",
            "connector": {},
            "node": {},
            "complexity": 0.6,
        }
        res_length = check_component_hard_constraints(
            short_edge,
            edge={"length": 10},
            to_node={"id": "G", "types": [NODE_TYPES["GOAL"]]},
        )
        self.assertFalse(res_length["ok"])
        self.assertIn("vertical_lift_requires_long_edge", res_length["issues"])

    def test_scoring_and_selection_are_seed_reproducible(self):
        edge = {"id": "E0", "from": "N0", "to": "N1", "length": 22}
        node = {"id": "N1", "types": [NODE_TYPES["PLATFORM"]], "intensity": 0.4}
        pool = build_candidate_pool(edge=edge, to_node=node, rng=rng_from_seed("score_pool"), pool_size=10)
        scored = [
            score_candidate(
                candidate,
                edge_length=22,
                family_usage={},
                weights={
                    "alignmentWeight": 0.35,
                    "playabilityWeight": 0.30,
                    "noveltyWeight": 0.20,
                    "shapeWeight": 0.15,
                    "riskWeight": 0.20,
                },
            )
            for candidate in pool
        ]
        ordered_a = select_candidate_order(
            scored,
            selection_top_p=0.5,
            selection_temperature=0.85,
            rng=rng_from_seed("sel"),
        )
        ordered_b = select_candidate_order(
            scored,
            selection_top_p=0.5,
            selection_temperature=0.85,
            rng=rng_from_seed("sel"),
        )
        self.assertEqual(len(ordered_a), 5)
        self.assertEqual([x["id"] for x in ordered_a], [x["id"] for x in ordered_b])

    def test_selection_fallbacks_match_paper_defaults(self):
        scored = [{"id": f"C{i}", "score": 1.0 - i * 0.05} for i in range(10)]
        fallback = select_candidate_order(
            scored,
            selection_top_p=None,
            selection_temperature=None,
            rng=rng_from_seed("paper_selection_defaults"),
        )
        explicit = select_candidate_order(
            scored,
            selection_top_p=0.70,
            selection_temperature=0.80,
            rng=rng_from_seed("paper_selection_defaults"),
        )
        self.assertEqual(len(fallback), 7)
        self.assertEqual([x["id"] for x in fallback], [x["id"] for x in explicit])


if __name__ == "__main__":
    unittest.main()

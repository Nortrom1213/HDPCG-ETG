import unittest

from hdpcg.etg_core import NODE_TYPES, normalize_etg
from hdpcg.generator import enforce_key_lock_route_coverage, generate_level
from hdpcg.random_utils import rng_from_seed


def _route_etg() -> dict:
    return normalize_etg(
        {
            "nodes": [
                {"id": "S", "type": NODE_TYPES["START"], "intensity": 0.1},
                {"id": "A", "type": NODE_TYPES["PLATFORM"], "intensity": 0.45},
                {"id": "L", "type": NODE_TYPES["LOCK"], "requires_key_id": "K1", "intensity": 0.6},
                {"id": "G", "type": NODE_TYPES["GOAL"], "intensity": 0.1},
                {"id": "K", "type": NODE_TYPES["KEY"], "key_id": "K1", "intensity": 0.3},
            ],
            "edges": [
                {"id": "E0", "from": "S", "to": "A", "length": 20},
                {"id": "E1", "from": "A", "to": "L", "length": 20},
                {"id": "E2", "from": "L", "to": "G", "length": 20},
                {"id": "E3", "from": "S", "to": "K", "length": 14},
                {"id": "E4", "from": "K", "to": "A", "length": 14},
            ],
        }
    )


class TestBaselineKeyLockRoutePass(unittest.TestCase):
    def test_route_pass_repairs_missing_required_key_node(self):
        etg = _route_etg()
        level = generate_level(
            etg,
            {
                "seed": "ut_route_pass_lane",
                "generatorMode": "lane",
                "laneIncludeBranches": False,
                "laneEnsureRequiredKeyPaths": False,
            },
            rng_from_seed("ut_route_pass_lane_geo"),
        )
        anchors_before = level.get("anchors") or {}
        anchors_before.pop("K", None)
        mapping_edge = ((level.get("mapping") or {}).get("edge") or {})
        for edge_id in ("E3", "E4"):
            mapping_edge.pop(edge_id, None)
        mapping_node = ((level.get("mapping") or {}).get("node") or {})
        if "K" in mapping_node:
            mapping_node.pop("K", None)

        repair = enforce_key_lock_route_coverage(
            level,
            etg,
            {
                "baselineKeyLockRoutePass": True,
                "baselineRouteRepairBudget": 4,
                "baselineRequireKeyNodeCoverage": True,
                "baselineConnectivityBridgeMaxGap": 18.0,
            },
            rng_from_seed("ut_route_pass_fix_geo"),
        )
        self.assertGreaterEqual(int(repair.get("missing_key_nodes_before_repair", 0)), 1)
        self.assertEqual(int(repair.get("missing_key_nodes_after_repair", 0)), 0)
        self.assertGreaterEqual(int(repair.get("required_key_path_repairs", 0)), 1)

    def test_route_pass_does_not_reverse_directed_edges(self):
        etg = normalize_etg({
            "nodes": [
                {"id": "S", "type": NODE_TYPES["START"], "intensity": 0.1},
                {"id": "K", "type": NODE_TYPES["KEY"], "key_id": "K1", "intensity": 0.3},
                {"id": "L", "type": NODE_TYPES["LOCK"], "requires_key_id": "K1", "intensity": 0.6},
                {"id": "G", "type": NODE_TYPES["GOAL"], "intensity": 0.1},
            ],
            "edges": [
                {"id": "E0", "from": "K", "to": "S", "length": 12},
                {"id": "E1", "from": "L", "to": "K", "length": 12},
                {"id": "E2", "from": "L", "to": "G", "length": 12},
            ],
        })
        level = generate_level(etg, {"seed": "directed", "generatorMode": "lane", "laneEnsureRequiredKeyPaths": False}, rng_from_seed("directed"))
        level.get("anchors", {}).pop("K", None)
        report = enforce_key_lock_route_coverage(level, etg, {"baselineKeyLockRoutePass": True}, rng_from_seed("directed-repair"))
        self.assertEqual(report["required_key_path_repairs"], 0)


if __name__ == "__main__":
    unittest.main()

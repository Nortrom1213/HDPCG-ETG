import unittest

from hdpcg.etg_core import NODE_TYPES, normalize_etg
from hdpcg.generator import generate_level
from hdpcg.random_utils import rng_from_seed


def _lane_keylock_etg() -> dict:
    return normalize_etg(
        {
            "nodes": [
                {"id": "S", "type": NODE_TYPES["START"], "intensity": 0.1},
                {"id": "A", "type": NODE_TYPES["PLATFORM"], "intensity": 0.45},
                {"id": "L", "type": NODE_TYPES["LOCK"], "requires_key_id": "K1", "intensity": 0.55},
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


class TestLaneRequiredKeyPaths(unittest.TestCase):
    def test_lane_attaches_required_key_path_when_branches_disabled(self):
        etg = _lane_keylock_etg()
        level = generate_level(
            etg,
            {
                "seed": "ut_lane_req",
                "generatorMode": "lane",
                "laneIncludeBranches": False,
                "laneEnsureRequiredKeyPaths": True,
                "laneKeyDetourMaxExtraRatio": 0.35,
                "laneBranchAttachMaxGap": 16.0,
            },
            rng_from_seed("ut_lane_req_geo"),
        )
        anchors = level.get("anchors") or {}
        self.assertIn("K", anchors)
        mapped_edges = (level.get("mapping") or {}).get("edge") or {}
        self.assertTrue("E3" in mapped_edges or "E4" in mapped_edges)


if __name__ == "__main__":
    unittest.main()

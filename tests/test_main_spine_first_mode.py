import unittest

from hdpcg.etg_core import NODE_TYPES, normalize_etg
from hdpcg.generator import generate_level
from hdpcg.random_utils import rng_from_seed


def _spine_etg() -> dict:
    return normalize_etg(
        {
            "nodes": [
                {"id": "N0", "type": NODE_TYPES["START"], "intensity": 0.1},
                {"id": "N1", "type": NODE_TYPES["PLATFORM"], "intensity": 0.45},
                {"id": "N2", "type": NODE_TYPES["GOAL"], "intensity": 0.1},
                {"id": "N3", "type": NODE_TYPES["PLATFORM"], "intensity": 0.6},
            ],
            "edges": [
                {"id": "E0", "from": "N0", "to": "N1", "length": 22},
                {"id": "E1", "from": "N1", "to": "N2", "length": 22},
                {"id": "E2", "from": "N1", "to": "N3", "length": 16},
            ],
        }
    )


class TestMainSpineFirstMode(unittest.TestCase):
    def test_spine_repair_and_infill_are_recorded(self):
        etg = _spine_etg()
        call_counter = {"n": 0}

        def fail_once(_: dict) -> dict:
            call_counter["n"] += 1
            if call_counter["n"] == 1:
                return {"ok": False, "reason": "forced_once"}
            return {"ok": True}

        level = generate_level(
            etg,
            {
                "seed": "ut_main_spine_first",
                "generatorMode": "hdpcg_incremental",
                "componentStrategy": "diverse",
                "candidatePoolSize": 14,
                "maxAttempts": 30,
                "maxLocalRejects": 24,
                "mainSpineFirstMode": True,
                "mainSpineRepairBudget": 6,
                "mainSpineEdgeSegmentLength": 5.2,
                "mainSpineSafeGround": True,
                "mainSpineLocalCheckStride": 1,
                "mainSpineRollbackOnFail": True,
                "fallbackEnabled": True,
            },
            rng_from_seed("ut_main_spine_first-geo"),
            fail_once,
        )

        stats = (((level.get("meta") or {}).get("component_generation") or {}).get("selection_stats") or {})
        self.assertGreater(int(stats.get("main_spine_edge_attempts", 0)), 0)
        self.assertGreaterEqual(int(stats.get("main_spine_edge_success", 0)), 2)
        self.assertGreaterEqual(int(stats.get("main_spine_rollbacks", 0)), 1)
        self.assertGreaterEqual(
            int(stats.get("main_spine_edge_attempts", 0)),
            int(stats.get("main_spine_edge_success", 0)),
        )
        self.assertIsInstance(level.get("goal"), dict)


if __name__ == "__main__":
    unittest.main()

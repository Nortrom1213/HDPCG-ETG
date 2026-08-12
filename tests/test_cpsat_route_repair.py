import unittest

from hdpcg.cpsat_baseline import cp_model
from hdpcg.cpsat_baseline import _cpsat_post_repair
from hdpcg.etg_core import NODE_TYPES, normalize_etg
from hdpcg.generator import generate_level
from hdpcg.random_utils import rng_from_seed


def _cpsat_route_etg() -> dict:
    return normalize_etg(
        {
            "nodes": [
                {"id": "S", "type": NODE_TYPES["START"], "intensity": 0.1},
                {"id": "A", "type": NODE_TYPES["PLATFORM"], "intensity": 0.4},
                {"id": "L", "type": NODE_TYPES["LOCK"], "requires_key_id": "K1", "intensity": 0.6},
                {"id": "G", "type": NODE_TYPES["GOAL"], "intensity": 0.1},
                {"id": "K", "type": NODE_TYPES["KEY"], "key_id": "K1", "intensity": 0.3},
            ],
            "edges": [
                {"id": "E0", "from": "S", "to": "A", "length": 16},
                {"id": "E1", "from": "A", "to": "L", "length": 18},
                {"id": "E2", "from": "L", "to": "G", "length": 18},
                {"id": "E3", "from": "S", "to": "K", "length": 12},
                {"id": "E4", "from": "K", "to": "A", "length": 14},
            ],
        }
    )


@unittest.skipIf(cp_model is None, "OR-Tools not installed")
class TestCpSatRouteRepair(unittest.TestCase):
    def test_cpsat_meta_exports_route_repair_pass(self):
        etg = _cpsat_route_etg()
        level = generate_level(
            etg,
            {
                "seed": "ut_cpsat_route",
                "generatorMode": "cpsat_baseline",
                "cpSatTimeLimitSec": 1.5,
                "cpSatNumWorkers": 1,
                "cpSatRouteRepairPasses": 2,
                "cpSatRequireKeyLockPath": True,
            },
            rng_from_seed("ut_cpsat_route_geo"),
        )
        meta = (level.get("meta") or {}).get("cpsat") or {}
        self.assertIn("route_repair_passes_used", meta)
        self.assertGreaterEqual(int(meta.get("route_repair_passes_used", 0)), 1)
        self.assertIn("route_repairs", meta)

    def test_post_repair_does_not_duplicate_platforms_across_passes(self):
        etg = _cpsat_route_etg()
        level = generate_level(
            etg,
            {"seed": "repair_once", "generatorMode": "cpsat_baseline", "cpSatPostRepairPasses": 0},
            rng_from_seed("repair_once_geo"),
        )
        for mapped in level.get("mapping", {}).get("edge", {}).values():
            mapped.pop("repair_platforms", None)
        first_edge = next(iter(level.get("mapping", {}).get("edge", {}).values()))
        first_edge["exit"] = {**first_edge["entry"], "x": float(first_edge["entry"]["x"]) + 30.0}
        first = _cpsat_post_repair(level, etg, {"cpSatPostRepairPasses": 3, "cpSatRepairMaxGap": 8.0})
        second = _cpsat_post_repair(level, etg, {"cpSatPostRepairPasses": 3, "cpSatRepairMaxGap": 8.0})
        self.assertGreater(first, 0)
        self.assertEqual(second, 0)


if __name__ == "__main__":
    unittest.main()

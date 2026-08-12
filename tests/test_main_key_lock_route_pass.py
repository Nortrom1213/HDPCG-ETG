import unittest
from unittest.mock import patch

from hdpcg.etg_core import NODE_TYPES, normalize_etg
from hdpcg.generator import generate_level
from hdpcg.random_utils import rng_from_seed


def _main_key_lock_etg() -> dict:
    return normalize_etg(
        {
            "nodes": [
                {"id": "S", "type": NODE_TYPES["START"], "intensity": 0.1},
                {"id": "A", "type": NODE_TYPES["PLATFORM"], "intensity": 0.4},
                {"id": "K", "type": NODE_TYPES["KEY"], "key_id": "K1", "intensity": 0.4},
                {"id": "L", "type": NODE_TYPES["LOCK"], "requires_key_id": "K1", "intensity": 0.6},
                {"id": "G", "type": NODE_TYPES["GOAL"], "intensity": 0.1},
            ],
            "edges": [
                {"id": "E0", "from": "S", "to": "A", "length": 14},
                {"id": "E1", "from": "A", "to": "K", "length": 12},
                {"id": "E2", "from": "K", "to": "L", "length": 16},
                {"id": "E3", "from": "L", "to": "G", "length": 14},
            ],
        }
    )


class TestMainKeyLockRoutePass(unittest.TestCase):
    def test_main_route_pass_records_repairs(self):
        etg = _main_key_lock_etg()
        with patch("hdpcg.generator.enforce_key_lock_route_coverage") as route_pass:
            route_pass.return_value = {
                "required_key_path_repairs": 2,
                "missing_key_nodes_before_repair": 1,
                "missing_key_nodes_after_repair": 0,
            }
            level = generate_level(
                etg,
                {
                    "seed": "ut_main_route_pass",
                    "generatorMode": "hdpcg_incremental",
                    "componentStrategy": "diverse",
                    "mainKeyLockRoutePass": True,
                    "mainRouteRepairBudget": 3,
                },
                rng_from_seed("ut_main_route_pass_geo"),
            )
        self.assertGreaterEqual(route_pass.call_count, 1)
        stats = (((level.get("meta") or {}).get("component_generation") or {}).get("selection_stats") or {})
        self.assertEqual(int(stats.get("main_route_repairs", 0)), 2)


if __name__ == "__main__":
    unittest.main()

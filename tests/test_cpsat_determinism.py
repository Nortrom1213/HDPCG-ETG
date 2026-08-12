import json
import unittest

from hdpcg.cpsat_baseline import cp_model
from hdpcg.etg_core import NODE_TYPES, normalize_etg
from hdpcg.generator import generate_level
from hdpcg.paper_config import method_profiles
from hdpcg.random_utils import rng_from_seed


@unittest.skipIf(cp_model is None, "OR-Tools not installed")
class TestCpSatDeterminism(unittest.TestCase):
    def test_paper_profile_reproduces_serialized_level(self):
        etg = normalize_etg(
            {
                "nodes": [
                    {"id": "S", "type": NODE_TYPES["START"], "intensity": 0.1},
                    {"id": "A", "type": NODE_TYPES["PLATFORM"], "intensity": 0.4},
                    {"id": "B", "type": NODE_TYPES["JUMP"], "intensity": 0.6},
                    {"id": "G", "type": NODE_TYPES["GOAL"], "intensity": 0.1},
                ],
                "edges": [
                    {"id": "E0", "from": "S", "to": "A", "length": 16},
                    {"id": "E1", "from": "A", "to": "B", "length": 18},
                    {"id": "E2", "from": "B", "to": "G", "length": 20},
                ],
            }
        )
        profile = next(item for item in method_profiles() if item["id"] == "cpsat")
        config = {**profile["config"], "seed": "cpsat_fixed", "generatorMode": profile["generatorMode"]}
        first = generate_level(etg, config, rng_from_seed("cpsat_fixed:geometry"))
        second = generate_level(etg, config, rng_from_seed("cpsat_fixed:geometry"))
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        params = ((first.get("meta") or {}).get("cpsat") or {}).get("params") or {}
        self.assertEqual(params.get("num_workers"), 1)
        self.assertEqual(params.get("deterministic_time_limit"), 6.0)


if __name__ == "__main__":
    unittest.main()

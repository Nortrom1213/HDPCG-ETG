import unittest

from hdpcg.etg_core import NODE_TYPES, normalize_etg
from hdpcg.generator import generate_level
from hdpcg.random_utils import rng_from_seed


def _sample_etg() -> dict:
    return normalize_etg(
        {
            "nodes": [
                {"id": "N0", "type": NODE_TYPES["START"], "intensity": 0.1},
                {"id": "N1", "type": NODE_TYPES["PLATFORM"], "intensity": 0.4},
                {"id": "N2", "type": NODE_TYPES["GOAL"], "intensity": 0.1},
            ],
            "edges": [
                {"id": "E0", "from": "N0", "to": "N1", "length": 18},
                {"id": "E1", "from": "N1", "to": "N2", "length": 18},
            ],
        }
    )


class TestGeneratorModes(unittest.TestCase):
    def test_all_generator_modes_smoke(self):
        etg = _sample_etg()
        modes = ["lane", "hdpcg_incremental", "constraint_based", "ga_baseline", "cpsat_baseline"]

        for mode in modes:
            with self.subTest(mode=mode):
                config = {
                    "seed": f"mode_{mode}",
                    "generatorMode": mode,
                    "difficulty": 0.45,
                    "length": 5,
                    "branchChance": 0.2,
                    "keyLock": False,
                    "maxAttempts": 22,
                    "sectorCount": 8,
                    "safetyMargin": 1.0,
                    "componentStrategy": "diverse",
                    "candidatePoolSize": 10,
                    "selectionTopP": 0.7,
                    "selectionTemperature": 0.9,
                    "maxLocalRejects": 20,
                    "fallbackEnabled": True,
                    "gaPopulation": 4,
                    "gaGenerations": 1,
                    "gaEliteRatio": 0.25,
                    "gaMutationRate": 0.2,
                    "gaTournamentSize": 2,
                    "topologyMaxStates": 40000,
                    "topologyMaxJumpOffsets": 220,
                }
                level = generate_level(etg, config, rng_from_seed(f"mode_{mode}-geo"))
                self.assertIn("platforms", level)
                self.assertTrue(level.get("platforms"))
                self.assertTrue(level.get("start"))
                self.assertTrue(level.get("goal"))
                self.assertIn("mapping", level)
                self.assertIn("edge", level["mapping"])
                self.assertIn("component_generation", level.get("meta") or {})

                if mode == "constraint_based":
                    self.assertEqual((level.get("meta") or {}).get("generator_mode"), "constraint_based")
                if mode == "ga_baseline":
                    self.assertEqual((level.get("meta") or {}).get("generator_mode"), "ga_baseline")
                    self.assertIn("ga", level.get("meta") or {})
                if mode == "cpsat_baseline":
                    self.assertEqual((level.get("meta") or {}).get("generator_mode"), "cpsat_baseline")
                    self.assertIn("cpsat", level.get("meta") or {})

    def test_diverse_incremental_and_constraint_emit_component_families(self):
        etg = _sample_etg()
        for mode in ("hdpcg_incremental", "constraint_based"):
            with self.subTest(mode=mode):
                config = {
                    "seed": f"diverse_{mode}",
                    "generatorMode": mode,
                    "difficulty": 0.5,
                    "componentStrategy": "diverse",
                    "candidatePoolSize": 12,
                    "selectionTopP": 0.75,
                    "selectionTemperature": 0.85,
                    "maxAttempts": 24,
                    "maxLocalRejects": 20,
                    "fallbackEnabled": True,
                }
                level = generate_level(etg, config, rng_from_seed(f"diverse_{mode}-geo"))
                edge_map = (level.get("mapping") or {}).get("edge") or {}
                self.assertTrue(edge_map)
                any_constraint = next(iter(edge_map.values()))
                constraints = (any_constraint or {}).get("constraints") or {}
                self.assertIn("connector_family", constraints)
                self.assertIn("node_family", constraints)

    def test_missing_key_gets_repaired_for_lock(self):
        etg = normalize_etg(
            {
                "nodes": [
                    {"id": "N0", "type": NODE_TYPES["START"], "intensity": 0.1},
                    {"id": "N1", "types": [NODE_TYPES["LOCK"]], "requires_key_id": "K9", "lock_id": "L9", "intensity": 0.5},
                    {"id": "N2", "type": NODE_TYPES["GOAL"], "intensity": 0.1},
                ],
                "edges": [
                    {"id": "E0", "from": "N0", "to": "N1", "length": 18},
                    {"id": "E1", "from": "N1", "to": "N2", "length": 18},
                ],
            }
        )
        level = generate_level(
            etg,
            {
                "seed": "repair_lock_key",
                "generatorMode": "constraint_based",
                "componentStrategy": "diverse",
                "candidatePoolSize": 8,
                "maxAttempts": 20,
            },
            rng_from_seed("repair_lock_key-geo"),
        )
        lock_key_ids = {lock.get("key_id") for lock in level.get("locks") or [] if lock.get("key_id")}
        generated_key_ids = {key.get("key_id") for key in level.get("keys") or [] if key.get("key_id")}
        self.assertTrue(lock_key_ids.issubset(generated_key_ids))


if __name__ == "__main__":
    unittest.main()

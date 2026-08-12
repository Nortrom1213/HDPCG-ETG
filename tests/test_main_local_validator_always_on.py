import unittest

from hdpcg.etg_core import NODE_TYPES, normalize_etg
from hdpcg.generator import generate_level
from hdpcg.random_utils import rng_from_seed


def _branch_etg() -> dict:
    return normalize_etg(
        {
            "nodes": [
                {"id": "S", "type": NODE_TYPES["START"], "intensity": 0.1},
                {"id": "A", "type": NODE_TYPES["PLATFORM"], "intensity": 0.5},
                {"id": "B", "type": NODE_TYPES["PLATFORM"], "intensity": 0.6},
                {"id": "G", "type": NODE_TYPES["GOAL"], "intensity": 0.1},
            ],
            "edges": [
                {"id": "E0", "from": "S", "to": "A", "length": 16},
                {"id": "E1", "from": "A", "to": "G", "length": 16},
                {"id": "E2", "from": "A", "to": "B", "length": 14},
            ],
        }
    )


class TestMainLocalValidatorAlwaysOn(unittest.TestCase):
    def test_main_local_validation_not_skipped(self):
        etg = _branch_etg()
        calls = {"n": 0}

        def validator(_: dict) -> dict:
            calls["n"] += 1
            return {"ok": True}

        level = generate_level(
            etg,
            {
                "seed": "ut_local_always",
                "generatorMode": "hdpcg_incremental",
                "componentStrategy": "diverse",
                "mainSpineFirstMode": True,
                "mainSpineLocalCheckStride": 6,
                "mainInfillSkipLocalValidation": True,
                "maxAttempts": 20,
                "maxLocalRejects": 16,
                "fallbackEnabled": True,
            },
            rng_from_seed("ut_local_always-geo"),
            validator,
        )
        stats = (((level.get("meta") or {}).get("component_generation") or {}).get("selection_stats") or {})
        self.assertGreater(calls["n"], 0)
        self.assertGreater(int(stats.get("local_validation_calls", 0)), 0)
        self.assertEqual(int(stats.get("local_validation_skips", 0)), 0)


if __name__ == "__main__":
    unittest.main()

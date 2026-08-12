import unittest

from hdpcg.etg_core import NODE_TYPES, normalize_etg
from hdpcg.evaluate import evaluate_level_quality
from hdpcg.generator import generate_level
from hdpcg.random_utils import rng_from_seed


def _diverse_etg() -> dict:
    return normalize_etg(
        {
            "nodes": [
                {"id": "S", "type": NODE_TYPES["START"], "intensity": 0.1},
                {"id": "A", "type": NODE_TYPES["PLATFORM"], "intensity": 0.4},
                {"id": "B", "type": NODE_TYPES["PLATFORM"], "intensity": 0.5},
                {"id": "G", "type": NODE_TYPES["GOAL"], "intensity": 0.2},
            ],
            "edges": [
                {"id": "E0", "from": "S", "to": "A", "length": 16},
                {"id": "E1", "from": "A", "to": "B", "length": 18},
                {"id": "E2", "from": "B", "to": "G", "length": 16},
                {"id": "E3", "from": "A", "to": "G", "length": 22},
            ],
        }
    )


class TestComponentFamilyUsagePersistence(unittest.TestCase):
    def test_family_usage_persists_on_meta(self):
        etg = _diverse_etg()
        level = generate_level(
            etg,
            {
                "seed": "ut_family_usage",
                "generatorMode": "constraint_based",
                "componentStrategy": "diverse",
                "candidatePoolSize": 10,
                "maxAttempts": 20,
                "maxLocalRejects": 16,
                "fallbackEnabled": True,
            },
            rng_from_seed("ut_family_usage_geo"),
        )
        component_meta = (((level.get("meta") or {}).get("component_generation") or {}))
        family_usage = component_meta.get("family_usage") or {}
        usage_total = sum(int(v) for v in family_usage.values())
        self.assertGreater(usage_total, 0)

        report = evaluate_level_quality(level, etg, {"metricVersion": "v2"})
        comp = ((report.get("metrics") or {}).get("component_diversity") or {})
        self.assertEqual(int(comp.get("family_usage_total", 0)), usage_total)


if __name__ == "__main__":
    unittest.main()

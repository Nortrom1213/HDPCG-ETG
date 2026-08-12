import json
import unittest

from hdpcg.etg_core import NODE_TYPES, normalize_etg
from hdpcg.generator import generate_level
from hdpcg.random_utils import rng_from_seed


class TestDeterminism(unittest.TestCase):
    def test_same_seed_and_config_produce_identical_level(self):
        etg = normalize_etg({
            "nodes": [
                {"id": "S", "type": NODE_TYPES["START"]},
                {"id": "P", "type": NODE_TYPES["PLATFORM"]},
                {"id": "G", "type": NODE_TYPES["GOAL"]},
            ],
            "edges": [
                {"id": "E0", "from": "S", "to": "P", "length": 12},
                {"id": "E1", "from": "P", "to": "G", "length": 12},
            ],
        })
        config = {"seed": "fixed", "generatorMode": "lane", "keyLock": False, "timeStep": 1.0, "maxTimeHorizon": 180}
        first = generate_level(etg, config, rng_from_seed("fixed:geometry"))
        second = generate_level(etg, config, rng_from_seed("fixed:geometry"))
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertEqual(first["meta"]["seed"], "fixed")
        self.assertEqual(first["meta"]["config"], config)


if __name__ == "__main__":
    unittest.main()

import unittest

from hdpcg.cpsat_baseline import cp_model, solve_anchor_layout_cp_sat
from hdpcg.etg_core import NODE_TYPES, normalize_etg
from hdpcg.random_utils import rng_from_seed


def _cpsat_etg() -> dict:
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
                {"id": "E0", "from": "S", "to": "A", "length": 18},
                {"id": "E1", "from": "A", "to": "L", "length": 18},
                {"id": "E2", "from": "L", "to": "G", "length": 20},
                {"id": "E3", "from": "S", "to": "K", "length": 12},
                {"id": "E4", "from": "K", "to": "A", "length": 14},
            ],
        }
    )


@unittest.skipIf(cp_model is None, "OR-Tools not installed")
class TestCpSatKeyLockPrecedence(unittest.TestCase):
    def test_key_before_lock_margin_respected(self):
        margin = 10
        layout = solve_anchor_layout_cp_sat(
            _cpsat_etg(),
            {
                "cpSatTimeLimitSec": 2.0,
                "cpSatNumWorkers": 1,
                "cpSatLaneRange": 2,
                "cpSatRelaxRounds": 1,
                "cpSatKeyBeforeLockMargin": margin,
            },
            rng_from_seed("cpsat_margin"),
        )
        self.assertTrue(layout.get("ok"), msg=str(layout.get("reason")))
        anchors = layout.get("anchors") or {}
        self.assertGreaterEqual(float(anchors["L"]["x"]) - float(anchors["K"]["x"]), float(margin))


if __name__ == "__main__":
    unittest.main()

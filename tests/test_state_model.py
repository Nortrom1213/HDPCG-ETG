import unittest

from hdpcg.hdpcg_grid import build_hdpcg_model, compute_time_horizon


class TestStateModel(unittest.TestCase):
    def test_horizon_is_capped_at_180_ticks(self):
        level = {
            "platforms": [
                {
                    "id": "moving",
                    "kind": "moving",
                    "pos": {"x": 0, "y": 0, "z": 0},
                    "size": {"x": 2, "y": 1, "z": 2},
                    "motion": {"axis": "x", "period": 181, "amplitude": 1},
                }
            ],
            "enemies": [],
            "keys": [],
            "locks": [],
            "start": {"x": 0, "y": 1, "z": 0},
            "goal": {"x": 1, "y": 1, "z": 0},
        }
        self.assertEqual(compute_time_horizon(level, 1.0), 180)
        model = build_hdpcg_model(level, {"timeStep": 1.0, "maxTimeHorizon": 180, "maxPeriodTicks": 180})
        self.assertEqual(model.timeStep, 1.0)
        self.assertEqual(model.timeHorizon, 180)


if __name__ == "__main__":
    unittest.main()

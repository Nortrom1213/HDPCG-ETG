import unittest

from hdpcg.hdpcg_bfs import compute_reachable
from hdpcg.hdpcg_grid import build_hdpcg_model


class TestReachabilityBudgets(unittest.TestCase):
    def test_explicit_state_budget_is_not_raised(self):
        level = {
            "meta": {"time_horizon": 180},
            "start": {"x": 0.0, "y": 0.0, "z": 0.0},
            "goal": {"x": 20.0, "y": 0.0, "z": 0.0},
            "platforms": [
                {"id": "P0", "pos": {"x": 0.0, "y": -0.5, "z": 0.0}, "size": {"x": 60.0, "y": 1.0, "z": 12.0}, "kind": "static"},
            ],
            "keys": [], "locks": [], "enemies": [], "checkpoints": [],
        }
        model = build_hdpcg_model(level)
        result = compute_reachable(model, {"maxTime": 60, "maxStates": 1, "maxQueue": 1, "maxJumpOffsets": 1})
        self.assertTrue(result["truncated"])
        self.assertLessEqual(result["expanded"], 2)


if __name__ == "__main__":
    unittest.main()

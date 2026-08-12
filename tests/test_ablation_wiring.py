import unittest
from pathlib import Path
from unittest.mock import patch

from hdpcg.experiment_runner import _local_validator_for_method
from scripts.run_ablation import load_profiles


class TestAblationWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        profiles = load_profiles(Path("configs/ablation_profiles.json"))
        cls.by_id = {profile["id"]: profile for profile in profiles}

    def test_full_main_receives_local_validator(self):
        method = self.by_id["abl_full_main"]
        self.assertIsNotNone(_local_validator_for_method(method, method["config"]))

    def test_no_local_profile_removes_local_validator(self):
        method = self.by_id["abl_no_local_5d"]
        self.assertIsNone(_local_validator_for_method(method, method["config"]))

    def test_selective_profiles_inject_only_the_requested_switch(self):
        captured = []

        def fake_validator(payload):
            captured.append(payload)
            return {"ok": True}

        with patch("hdpcg.experiment_runner.validate_local_topology", side_effect=fake_validator):
            forbidden = self.by_id["abl_no_forbidden_marker"]
            forbidden_hook = _local_validator_for_method(forbidden, forbidden["config"])
            self.assertIsNotNone(forbidden_hook)
            forbidden_hook({"fromId": "A", "toId": "B"})

            lock = self.by_id["abl_no_lock_semantic_local"]
            lock_hook = _local_validator_for_method(lock, lock["config"])
            self.assertIsNotNone(lock_hook)
            lock_hook({"fromId": "A", "toId": "B"})

        self.assertTrue(captured[0]["disableForbiddenMarkers"])
        self.assertFalse(captured[0]["disableLockSemantics"])
        self.assertFalse(captured[1]["disableForbiddenMarkers"])
        self.assertTrue(captured[1]["disableLockSemantics"])


if __name__ == "__main__":
    unittest.main()

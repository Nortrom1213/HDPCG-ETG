import unittest

from hdpcg.paper_config import load_paper_config, method_profiles


class TestPaperConfig(unittest.TestCase):
    def test_state_and_candidate_defaults(self):
        config = load_paper_config()
        state = config["state_model"]
        self.assertEqual(state["time_step_seconds"], 1.0)
        self.assertEqual(state["max_time_horizon"], 180)
        self.assertEqual(state["max_period_ticks"], 180)
        self.assertEqual(state["local_padding_cells"], 3)
        self.assertEqual(state["cell_size"], 1.0)
        self.assertEqual(state["global_padding_cells"], 4)
        self.assertEqual(state["local_model_padding_cells"], 2)
        self.assertEqual(state["sibling_tolerance_radius_cells"], 2)
        selection = config["candidate_selection"]
        self.assertEqual(selection["pool_size"], 12)
        self.assertEqual(selection["top_p"], 0.70)
        self.assertEqual(selection["temperature"], 0.80)
        self.assertEqual(selection["weights"], {
            "alignment": 0.35,
            "playability": 0.30,
            "novelty": 0.20,
            "shape": 0.15,
            "risk": 0.20,
        })

    def test_protocol_and_method_ids(self):
        config = load_paper_config()
        self.assertEqual(config["benchmark"]["scales"], ["small", "medium", "large"])
        self.assertEqual(config["benchmark"]["etgs_per_scale"], 3)
        self.assertEqual(config["benchmark"]["repeats"], 100)
        self.assertEqual(config["ablation"]["repeats"], 100)
        self.assertEqual([item["id"] for item in method_profiles()], ["main", "constraint", "lane", "ga", "cpsat"])

    def test_reproducibility_settings(self):
        config = load_paper_config()
        self.assertEqual(config["etg_bank"], {
            "pool_size": 120,
            "select_count": 3,
            "seed_prefix": "paper_etg",
            "extra_batch_size": 40,
            "max_extra_batches": 5,
        })
        self.assertEqual(config["execution"]["retry_limit"], 2)
        self.assertEqual(config["execution"]["run_timeout_sec"], 600.0)
        self.assertEqual(config["benchmark"]["scale_profiles"]["small"]["length"], 6)
        self.assertEqual(config["benchmark"]["scale_profiles"]["medium"]["length"], 10)
        self.assertEqual(config["benchmark"]["scale_profiles"]["large"]["length"], 14)
        cpsat = next(item for item in method_profiles() if item["id"] == "cpsat")["config"]
        main = next(item for item in method_profiles() if item["id"] == "main")["config"]
        self.assertTrue(main["mainInfillConnectivityFallback"])
        self.assertEqual(cpsat["cpSatNumWorkers"], 1)
        self.assertEqual(cpsat["cpSatDeterministicTimeLimit"], 6.0)
        self.assertEqual(config["validation"]["strict_by_scale"]["large"]["max_states"], 924000)
        self.assertEqual(config["simulation"]["gravity"], -24.0)
        pilot = config["cross_domain_pilot"]
        self.assertEqual(pilot["repeats_per_etg_method"], 20)
        self.assertEqual(pilot["base_seed"], 20269514)
        self.assertEqual(pilot["etg_seed_stride"], 10000)
        self.assertEqual(pilot["repeat_seed_stride"], 97)
        self.assertEqual(pilot["method_seed_stride"], 1009)
        self.assertEqual(len(pilot["variants"]), 3)


if __name__ == "__main__":
    unittest.main()

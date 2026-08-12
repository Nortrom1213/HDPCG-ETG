import unittest

from hdpcg.evaluate import compute_signature_diversity
from hdpcg.experiment_runner import _failure_breakdown, _summaries


class TestExperimentReporting(unittest.TestCase):
    def test_summary_exposes_paper_dimensions_and_failure_taxonomy(self):
        records = [
            {
                "status": "success",
                "method_id": "main",
                "scale": "small",
                "valid": True,
                "failure_reason": "ok",
                "budget_limit": False,
                "strict_structural_failure": False,
                "overall_score": 0.8,
                "playability": 1.0,
                "controllability": 0.7,
                "topological_consistency": 0.9,
                "pacing_variation": 0.4,
                "balance": 0.6,
                "signature": {
                    "node_types": ["Start", "Jump", "Goal"],
                    "component_families": ["linear", "steps"],
                    "shape_vector": [0.2, 0.3, 0.4, 0.5],
                },
                "runtime_sec": 2.0,
            },
            {
                "status": "success",
                "method_id": "main",
                "scale": "large",
                "valid": False,
                "failure_reason": "budget_limit",
                "budget_limit": True,
                "strict_structural_failure": True,
                "overall_score": 0.2,
                "playability": 0.0,
                "controllability": 0.3,
                "topological_consistency": 0.2,
                "pacing_variation": 0.2,
                "balance": 0.4,
                "signature": {
                    "node_types": ["Start", "Enemy", "Goal"],
                    "component_families": ["arc", "island"],
                    "shape_vector": [0.8, 0.6, 0.2, 0.1],
                },
                "runtime_sec": 4.0,
            },
            {
                "status": "failed",
                "method_id": "main",
                "scale": "medium",
                "valid": False,
                "failure_reason": "run_error:ValueError",
                "budget_limit": False,
                "strict_structural_failure": True,
                "runtime_sec": 6.0,
            },
        ]
        row = _summaries(records, ["method_id"])[0]
        self.assertEqual(row["valid_runs"], 1)
        self.assertEqual(row["invalid_runs"], 2)
        self.assertEqual(row["budget_limit_runs"], 1)
        self.assertEqual(row["large_budget_limit_runs"], 1)
        self.assertAlmostEqual(row["failure_rate"], 2 / 3)
        self.assertAlmostEqual(row["strict_structural_failure_rate"], 2 / 3)
        expected_diversity = compute_signature_diversity([records[0]["signature"], records[1]["signature"]])["score"]
        self.assertEqual(row["diversity_mean"], expected_diversity)
        self.assertEqual(row["balance_mean"], 0.5)
        self.assertEqual(row["runtime_mean_sec"], 4.0)
        breakdown = _failure_breakdown(records)
        self.assertEqual(
            {item["failure_reason"] for item in breakdown},
            {"ok", "budget_limit", "run_error:ValueError"},
        )

    def test_failed_runs_count_as_strict_structural_failures(self):
        records = [{
            "status": "failed",
            "method_id": "main",
            "valid": False,
            "failure_reason": "run_error:RuntimeError",
            "budget_limit": False,
            "strict_structural_failure": True,
            "runtime_sec": 1.0,
        }]
        row = _summaries(records, ["method_id"])[0]
        self.assertEqual(row["strict_structural_failure_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()

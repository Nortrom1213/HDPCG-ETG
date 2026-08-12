import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hdpcg.fall_guys_simulation import (
    METHOD_ORDER,
    build_fall_guys_etg,
    evaluate_level,
    generate_constraint_constructive_baseline,
    generate_main_level,
    generate_paper_cpsat_baseline,
    generate_paper_ga_baseline,
    generate_paper_lane_baseline,
)
from scripts.run_fall_guys_pilot import main as run_pilot
GENERATORS = {
    "main": generate_main_level,
    "constraint": generate_constraint_constructive_baseline,
    "lane": generate_paper_lane_baseline,
    "ga": generate_paper_ga_baseline,
    "cpsat": generate_paper_cpsat_baseline,
}


class TestFallGuysPilot(unittest.TestCase):
    def test_methods_have_distinct_algorithms_and_complete_metrics(self):
        etg = build_fall_guys_etg()
        strategies = set()
        for method in METHOD_ORDER:
            level = GENERATORS[method](etg, 2026)
            strategies.add(level["meta"]["method_details"]["strategy"])
            metrics = evaluate_level(etg, level, method)
            for name in (
                "overall_case_study_score", "balanced_transfer_hmean", "transfer_bottleneck_min",
                "edge_fidelity", "branch_fidelity", "domain_mechanic_coverage",
                "obstacle_validity", "route_curvature_score", "edge_connector_coverage",
                "edge_continuity_score", "realization_quality",
            ):
                self.assertIn(name, metrics)
                self.assertGreaterEqual(metrics[name], 0.0)
                self.assertLessEqual(metrics[name], 1.0)
        self.assertEqual(len(strategies), 5)

    def test_cpsat_is_seed_deterministic(self):
        etg = build_fall_guys_etg()
        first = generate_paper_cpsat_baseline(etg, 77)
        second = generate_paper_cpsat_baseline(etg, 77)
        self.assertEqual(first, second)
        self.assertEqual(first["meta"]["method_details"]["strategy"], "ortools_cp_sat")

    def test_methods_use_the_supplied_paired_seed(self):
        etg = build_fall_guys_etg()
        for method in METHOD_ORDER:
            level = GENERATORS[method](etg, 91)
            self.assertEqual(level["meta"]["seed"], 91)

    def test_connector_coverage_is_not_edge_presence(self):
        etg = build_fall_guys_etg()
        level = generate_main_level(etg, 12)
        edge_record = next(iter(level["mapping"]["edge"].values()))
        edge_record["platforms"] = edge_record["platforms"][:1]
        edge_record["target_count"] = 4
        metrics = evaluate_level(etg, level, "main")
        self.assertGreater(metrics["edge_fidelity"], metrics["edge_connector_coverage"])

    def test_main_records_incremental_edge_checks(self):
        level = generate_main_level(build_fall_guys_etg(), 2026)
        details = level["meta"]["method_details"]
        self.assertTrue(details["local_topology_checks"])
        self.assertIn("edge_retries", details)
        self.assertIn("rejected_edges", details)
        mapped_edges = level["mapping"]["edge"]
        self.assertEqual(details["rejected_edges"], sum(not record["platforms"] for record in mapped_edges.values()))

    def test_runner_writes_paper_facing_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("sys.argv", ["run_fall_guys_pilot.py", "--n", "1", "--out-dir", temp_dir]):
                self.assertEqual(run_pilot(), 0)
            output = Path(temp_dir)
            self.assertTrue((output / "summary_by_method.csv").is_file())
            self.assertTrue((output / "pairwise_main_vs_baselines.csv").is_file())
            self.assertTrue((output / "rank_summary.csv").is_file())
            self.assertEqual(len((output / "run_records.jsonl").read_text(encoding="utf-8").splitlines()), 15)


if __name__ == "__main__":
    unittest.main()

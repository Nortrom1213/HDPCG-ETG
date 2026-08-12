from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def find_latest_run(root: Path) -> Path:
    candidates = [path.parent for path in root.rglob("summary_by_method.csv")]
    if not candidates:
        raise FileNotFoundError("No benchmark summary found under out/. Run the benchmark first.")
    return max(candidates, key=lambda path: (path / "summary_by_method.csv").stat().st_mtime)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a compact report from a benchmark run.")
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args()

    run_dir = Path(args.run_dir) if args.run_dir else find_latest_run(Path("out"))
    out_dir = Path(args.out_dir) if args.out_dir else run_dir / "report"
    out_dir.mkdir(parents=True, exist_ok=True)
    table = pd.read_csv(run_dir / "summary_by_method.csv")
    columns = [
        column
        for column in ["method_id", "overall_score_mean", "playability_mean", "controllability_mean", "pacing_variation_mean", "topological_consistency_mean", "diversity_mean", "balance_mean", "overall_score_std", "runtime_mean_sec", "valid_runs", "budget_limit_runs", "failure_rate"]
        if column in table.columns
    ]
    (out_dir / "summary.md").write_text(table[columns].to_markdown(index=False) + "\n", encoding="utf-8")

    if "overall_score_mean" in table.columns:
        figure, axis = plt.subplots(figsize=(6.2, 3.5))
        axis.bar(table["method_id"], table["overall_score_mean"], color="#3976b9")
        axis.set_ylabel("Overall")
        axis.set_ylim(0, 1)
        axis.tick_params(axis="x", rotation=25)
        figure.tight_layout()
        figure.savefig(out_dir / "overall_by_method.png", dpi=200)
        plt.close(figure)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

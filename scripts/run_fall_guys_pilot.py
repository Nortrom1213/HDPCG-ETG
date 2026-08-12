from __future__ import annotations

import argparse
import copy
import csv
import json
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hdpcg.fall_guys_simulation import (
    METHOD_LABELS,
    METHOD_ORDER,
    build_fall_guys_etg,
    evaluate_level,
    generate_constraint_constructive_baseline,
    generate_main_level,
    generate_paper_cpsat_baseline,
    generate_paper_ga_baseline,
    generate_paper_lane_baseline,
)
from hdpcg.paper_config import load_paper_config


METHODS = {
    "main": generate_main_level,
    "constraint": generate_constraint_constructive_baseline,
    "lane": generate_paper_lane_baseline,
    "ga": generate_paper_ga_baseline,
    "cpsat": generate_paper_cpsat_baseline,
}
SUMMARY_METRICS = [
    "overall_case_study_score", "balanced_transfer_hmean", "transfer_bottleneck_min",
    "edge_fidelity", "branch_fidelity", "domain_mechanic_coverage",
    "obstacle_validity", "route_curvature_score", "edge_connector_coverage",
    "edge_continuity_score", "realization_quality",
]


def etg_variants(settings: dict) -> dict[str, dict]:
    base = build_fall_guys_etg()
    variants = {}
    for policy in settings["variants"]:
        etg = copy.deepcopy(base)
        for item in etg["nodes"]:
            layout = item.setdefault("data", {}).setdefault("layout", {})
            node_id = str(item["id"])
            layout["x"] = round(float(layout.get("x", 0.0)) * float(policy["x_scale"]), 4)
            layout["y"] = round(float(layout.get("y", 0.0)) * float(policy["y_scale"]) + float(policy.get("extra_y", {}).get(node_id, 0.0)), 4)
            item["intensity"] = round(clamp(float(item.get("intensity", 0.5)) + float(policy["intensity_delta"])), 4)
        for item in etg["edges"]:
            item["length"] = round(max(7.5, float(item.get("length", 12.0)) * float(policy["edge_scale"])), 4)
        etg["id"] = policy["id"]
        etg["variant_policy"] = copy.deepcopy(policy)
        variants[policy["id"]] = etg
    return variants


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def arithmetic_mean(rows: list[dict], metric: str) -> float:
    return statistics.fmean(float(row[metric]) for row in rows) if rows else 0.0


def bootstrap_ci(values: list[float], seed: int, samples: int = 2000) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    rng = random.Random(seed)
    means = sorted(statistics.fmean(values[rng.randrange(len(values))] for _ in values) for _ in range(samples))
    return means[max(0, int(samples * 0.025) - 1)], means[min(samples - 1, int(samples * 0.975))]


def pairwise_rows(records: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, int], dict[str, dict]] = {}
    for row in records:
        grouped.setdefault((str(row["variant"]), int(row["repeat"])), {})[str(row["method"])] = row
    output = []
    metrics = ["overall_case_study_score", "balanced_transfer_hmean", "transfer_bottleneck_min"]
    for metric_index, metric in enumerate(metrics):
        for baseline_index, baseline in enumerate(METHOD_ORDER[1:]):
            differences = [float(group["main"][metric]) - float(group[baseline][metric]) for group in grouped.values()]
            low, high = bootstrap_ci(differences, 20260000 + metric_index * 100 + baseline_index)
            output.append({
                "metric": metric,
                "baseline": baseline,
                "paired_groups": len(differences),
                "mean_difference": round(statistics.fmean(differences), 4),
                "win_rate": round(sum(value > 0 for value in differences) / max(1, len(differences)), 4),
                "bootstrap_ci_low": round(low, 4),
                "bootstrap_ci_high": round(high, 4),
            })
    return output


def rank_rows(records: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, int], list[dict]] = {}
    for row in records:
        grouped.setdefault((str(row["variant"]), int(row["repeat"])), []).append(row)
    output = []
    for metric in ("overall_case_study_score", "balanced_transfer_hmean", "transfer_bottleneck_min"):
        wins = {method: 0 for method in METHOD_ORDER}
        rank_sums = {method: 0.0 for method in METHOD_ORDER}
        for rows in grouped.values():
            ordered = sorted(rows, key=lambda row: float(row[metric]), reverse=True)
            best = float(ordered[0][metric])
            for rank, row in enumerate(ordered, 1):
                method = str(row["method"])
                rank_sums[method] += rank
                if abs(float(row[metric]) - best) < 1e-9:
                    wins[method] += 1
        for method in METHOD_ORDER:
            output.append({
                "metric": metric,
                "method": method,
                "paired_groups": len(grouped),
                "mean_rank": round(rank_sums[method] / max(1, len(grouped)), 4),
                "win_rate": round(wins[method] / max(1, len(grouped)), 4),
            })
    return output


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    settings = load_paper_config()["cross_domain_pilot"]
    parser = argparse.ArgumentParser(description="Run the procedural obstacle-course pilot.")
    parser.add_argument("--n", type=int, default=int(settings["repeats_per_etg_method"]))
    parser.add_argument("--seed", type=int, default=int(settings["base_seed"]))
    parser.add_argument("--out-dir", default="out/obstacle_course_pilot")
    args = parser.parse_args()

    records = []
    for variant_index, (variant, etg) in enumerate(etg_variants(settings).items()):
        for repeat in range(args.n):
            base_seed = args.seed + variant_index * int(settings["etg_seed_stride"]) + repeat * int(settings["repeat_seed_stride"])
            for method in METHOD_ORDER:
                seed = base_seed
                level = METHODS[method](etg, seed)
                records.append({"variant": variant, "repeat": repeat, "seed": seed, "method": method, **evaluate_level(etg, level, method)})

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "run_records.jsonl").open("w", encoding="utf-8") as stream:
        for row in records:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    summaries = []
    for method in METHOD_ORDER:
        rows = [row for row in records if row["method"] == method]
        summaries.append({"method": method, "label": METHOD_LABELS[method], "runs": len(rows), **{name: round(arithmetic_mean(rows, name), 4) for name in SUMMARY_METRICS}})
    write_csv(out_dir / "summary_by_method.csv", summaries)
    write_csv(out_dir / "pairwise_main_vs_baselines.csv", pairwise_rows(records))
    write_csv(out_dir / "rank_summary.csv", rank_rows(records))
    (out_dir / "benchmark_config.json").write_text(json.dumps({"variants": list(etg_variants(settings)), "methods": METHOD_ORDER, "repeats": args.n, "seed": args.seed, "records": len(records)}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

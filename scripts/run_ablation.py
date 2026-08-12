from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hdpcg.etg_qd_selection import make_etg_bank
from hdpcg.experiment_runner import run_benchmark
from hdpcg.paper_config import load_paper_config


def load_json_object(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Topology overrides must be a JSON object")
    return value


def load_profiles(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    profiles = list(raw["methods"])
    by_id = {str(item["id"]): item for item in profiles}
    resolved: list[dict[str, Any]] = []
    for item in profiles:
        config = dict(item.get("config") or {})
        parent_id = config.pop("inheritFrom", None)
        if parent_id:
            parent = by_id[str(parent_id)]
            config = {**dict(parent.get("config") or {}), **config}
        resolved.append({**item, "config": config})
    return resolved


def main() -> int:
    paper = load_paper_config()
    parser = argparse.ArgumentParser(description="Run the six-profile component ablation.")
    parser.add_argument("--manifest", default="out/etg_bank/dataset_manifest.json")
    parser.add_argument("--out-dir", default="out")
    parser.add_argument("--profiles", default="configs/ablation_profiles.json")
    parser.add_argument("--n", type=int, default=int(paper["ablation"]["repeats"]))
    parser.add_argument("--run-id", default="paper_ablation")
    parser.add_argument("--topology-overrides", default=None)
    args = parser.parse_args()

    manifest = Path(args.manifest)
    if not manifest.exists():
        make_etg_bank(
            manifest.parent,
            pool_size=120,
            select_count=int(paper["benchmark"]["etgs_per_scale"]),
            seed_prefix="paper_etg",
            scales=list(paper["benchmark"]["scales"]),
        )
    report = run_benchmark(
        manifest,
        args.out_dir,
        n=args.n,
        strict=True,
        base_seed="paper_ablation",
        method_profiles=load_profiles(Path(args.profiles)),
        topology_overrides=load_json_object(args.topology_overrides),
        run_id=args.run_id,
        resume=True,
        allow_n_increase=True,
    )
    print(json.dumps(report.get("workflow_status") or {}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

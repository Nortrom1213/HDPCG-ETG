from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hdpcg.etg_qd_selection import make_etg_bank
from hdpcg.experiment_runner import run_benchmark
from hdpcg.paper_config import load_paper_config


def main() -> int:
    paper = load_paper_config()
    protocol = paper["benchmark"]
    bank = paper["etg_bank"]
    execution = paper["execution"]
    parser = argparse.ArgumentParser(description="Build an ETG bank and run the paper benchmark.")
    parser.add_argument("--bank-out", default="out/etg_bank")
    parser.add_argument("--out-dir", default="out")
    parser.add_argument("--pool-size", type=int, default=int(bank["pool_size"]))
    parser.add_argument("--n", type=int, default=int(protocol["repeats"]))
    parser.add_argument("--seed-prefix", default=str(execution["seed_prefix"]))
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    make_etg_bank(
        args.bank_out,
        pool_size=args.pool_size,
        select_count=int(bank["select_count"]),
        seed_prefix=str(bank["seed_prefix"]),
        scales=list(protocol["scales"]),
        extra_batch_size=int(bank["extra_batch_size"]),
        max_extra_batches=int(bank["max_extra_batches"]),
    )
    manifest = Path(args.bank_out) / "dataset_manifest.json"
    report = run_benchmark(
        manifest,
        args.out_dir,
        n=args.n,
        strict=bool(protocol["strict"]),
        retry_limit=int(execution["retry_limit"]),
        run_timeout_sec=float(execution["run_timeout_sec"]),
        save_each=bool(execution["save_each"]),
        base_seed=args.seed_prefix,
        run_id=args.run_id,
        resume=bool(execution["resume"]),
    )
    print(json.dumps(report.get("workflow_status") or {}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

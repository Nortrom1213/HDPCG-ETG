from __future__ import annotations

import csv
import json
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .evaluate import compute_signature_diversity, evaluate_level_quality
from .generator import generate_level
from .io_utils import read_json, write_json
from .paper_config import load_paper_config, method_profiles
from .random_utils import rng_from_seed
from .topology import validate_local_topology


def default_method_profiles() -> list[dict[str, Any]]:
    return method_profiles()


def _local_validator_for_method(
    method: dict[str, Any], config: dict[str, Any]
) -> Callable[[dict[str, Any]], dict[str, Any]] | None:
    if str(method.get("generatorMode")) != "hdpcg_incremental":
        return None
    if bool(config.get("benchmarkDisableLocalValidation", False)):
        return None

    disable_forbidden = bool(config.get("localValidationDisableForbiddenMarkers", False))
    disable_lock_semantics = bool(config.get("localValidationDisableLockSemantics", False))
    if not disable_forbidden and not disable_lock_semantics:
        return validate_local_topology

    def validate(payload: dict[str, Any]) -> dict[str, Any]:
        return validate_local_topology(
            {
                **payload,
                "disableForbiddenMarkers": disable_forbidden,
                "disableLockSemantics": disable_lock_semantics,
            }
        )

    return validate


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _std(values: list[float]) -> float:
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def _evaluation_failure(report: dict[str, Any]) -> tuple[bool, str, bool]:
    topology = report.get("topology") or {}
    metrics = report.get("metrics") or {}
    topology_ok = bool(topology.get("ok"))
    key_lock_metric = metrics.get("key_lock_consistency") or {}
    key_lock_ok = bool(key_lock_metric.get("order_ok", (metrics.get("playability") or {}).get("key_lock_order_ok", True)))
    if topology_ok and key_lock_ok:
        return True, "ok", False

    reason = str(topology.get("reason") or "invalid")
    coverage = topology.get("coverage_search") or {}
    search = topology.get("search") or {}
    budget_limited = (
        "budget_limit" in reason
        or reason in {"budget_exceeded", "wall_time_exceeded"}
        or str(search.get("reason") or "") in {"budget_exceeded", "wall_time_exceeded"}
        or bool(coverage.get("truncated"))
    )
    if budget_limited:
        return False, "budget_limit", True
    if not key_lock_ok:
        return False, "key_lock_order", False
    return False, f"topology:{reason}", False


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _summaries(records: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[tuple(record.get(key) for key in keys)].append(record)
    rows: list[dict[str, Any]] = []
    for group_key, items in sorted(groups.items(), key=lambda item: tuple(str(v) for v in item[0])):
        successful = [item for item in items if item.get("status") == "success"]
        valid = [item for item in successful if bool(item.get("valid"))]
        budget_limited = [item for item in items if bool(item.get("budget_limit"))]
        invalid_count = len(items) - len(valid)
        diversity = compute_signature_diversity(
            [item["signature"] for item in successful if isinstance(item.get("signature"), dict)]
        )
        row = {key: value for key, value in zip(keys, group_key)}
        row.update(
            {
                "runs_total": len(items),
                "runs_success": len(successful),
                "runs_failed": len(items) - len(successful),
                "valid_runs": len(valid),
                "invalid_runs": invalid_count,
                "budget_limit_runs": len(budget_limited),
                "non_budget_invalid_runs": invalid_count - len(budget_limited),
                "failure_rate": invalid_count / max(1, len(items)),
                "strict_structural_failure_rate": _mean(
                    [1.0 if bool(item.get("strict_structural_failure")) else 0.0 for item in items]
                ),
                "large_budget_limit_runs": sum(
                    1 for item in budget_limited if str(item.get("scale")) == "large"
                ),
                "overall_score_mean": _mean([float(item.get("overall_score", 0.0)) for item in successful]),
                "overall_score_std": _std([float(item.get("overall_score", 0.0)) for item in successful]),
                "playability_mean": _mean([float(item.get("playability", 0.0)) for item in successful]),
                "controllability_mean": _mean([float(item.get("controllability", 0.0)) for item in successful]),
                "topological_consistency_mean": _mean([float(item.get("topological_consistency", 0.0)) for item in successful]),
                "pacing_variation_mean": _mean([float(item.get("pacing_variation", 0.0)) for item in successful]),
                "diversity_mean": float(diversity["score"]),
                "balance_mean": _mean([float(item.get("balance", 0.0)) for item in successful]),
                "runtime_mean_sec": _mean([float(item.get("runtime_sec", 0.0)) for item in items]),
            }
        )
        rows.append(row)
    return rows


def _failure_breakdown(records: list[dict[str, Any]], include_scale: bool = False) -> list[dict[str, Any]]:
    counts: dict[tuple[str, ...], int] = defaultdict(int)
    for record in records:
        reason = str(record.get("failure_reason") or "run_error")
        key = (str(record.get("method_id")), str(record.get("scale")), reason) if include_scale else (
            str(record.get("method_id")),
            reason,
        )
        counts[key] += 1
    rows = []
    for key, count in sorted(counts.items()):
        if include_scale:
            method_id, scale, reason = key
            rows.append({"method_id": method_id, "scale": scale, "failure_reason": reason, "count": count})
        else:
            method_id, reason = key
            rows.append({"method_id": method_id, "failure_reason": reason, "count": count})
    return rows


def run_benchmark(
    manifest_path: str | Path,
    out_dir: str | Path,
    *,
    n: int = 100,
    strict: bool = True,
    retry_limit: int = 0,
    run_timeout_sec: float = 900.0,
    save_each: bool = True,
    base_seed: str = "paper_run",
    topology_overrides: dict[str, Any] | None = None,
    topology_overrides_by_scale: dict[str, Any] | None = None,
    method_profiles: list[dict[str, Any]] | None = None,
    run_id: str | None = None,
    resume: bool = True,
    reset_run: bool = False,
    allow_n_increase: bool = False,
) -> dict[str, Any]:
    del allow_n_increase
    manifest_file = Path(manifest_path).resolve()
    manifest = read_json(manifest_file)
    selected = list(manifest.get("selected_global") or [])
    methods = list(method_profiles or default_method_profiles())
    paper = load_paper_config()
    state = paper["state_model"]
    validation = paper["validation"]
    budget_profiles = validation["strict_by_scale"] if strict else validation["non_strict_by_scale"]
    topology_common = {
        "cellSize": float(state["cell_size"]),
        "timeStep": float(state["time_step_seconds"]),
        "padding": int(state["global_padding_cells"]),
        "maxTimeHorizon": int(state["max_time_horizon"]),
        "maxPeriodTicks": int(state["max_period_ticks"]),
        "allowJump": bool(validation["allow_jump"]),
        "allowDrop": bool(validation["allow_drop"]),
        "compressTime": bool(validation["compress_time"]),
        "checkLatentShortcuts": bool(strict),
    }
    topology_common.update(topology_overrides or {})

    run_name = run_id or datetime.now(timezone.utc).strftime("benchmark_%Y%m%d_%H%M%S")
    run_dir = Path(out_dir).resolve() / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    records_path = run_dir / "run_records.jsonl"
    existing: dict[str, dict[str, Any]] = {}
    if resume and records_path.exists() and not reset_run:
        for line in records_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                existing[str(row["task_id"])] = row
    if reset_run:
        existing = {}

    records = dict(existing)
    tasks = []
    for etg_entry in selected:
        for method in methods:
            for repeat in range(int(n)):
                task_id = f"{etg_entry['id']}__{method['id']}__{repeat:04d}"
                tasks.append((task_id, etg_entry, method, repeat))

    for task_id, etg_entry, method, repeat in tasks:
        if task_id in records:
            continue
        etg_path = manifest_file.parent / str(etg_entry["path"])
        etg = read_json(etg_path)
        seed = f"{base_seed}:{etg_entry['id']}:{method['id']}:{repeat}"
        config = {
            **dict(method.get("config") or {}),
            "seed": seed,
            "generatorMode": method["generatorMode"],
            "timeStep": float(state["time_step_seconds"]),
            "maxTimeHorizon": int(state["max_time_horizon"]),
            "maxPeriodTicks": int(state["max_period_ticks"]),
            "validationMaxTimeHorizon": int(state["max_time_horizon"]),
            "validationMaxPeriodTicks": int(state["max_period_ticks"]),
            "validationLocalPaddingCells": int(state["local_padding_cells"]),
        }
        scale = str(etg_entry.get("scale"))
        budget = dict(budget_profiles[scale])
        topology_options = {
            **topology_common,
            "maxStates": int(budget["max_states"]),
            "maxQueue": int(budget["max_queue"]),
            "maxJumpOffsets": int(budget["max_jump_offsets"]),
            "maxWallTimeSec": float(budget["max_wall_time_sec"]),
        }
        if budget.get("max_time") is not None:
            topology_options["maxTime"] = int(budget["max_time"])
        scale_overrides = (topology_overrides_by_scale or {}).get(scale, {})
        topology_options.update(dict(scale_overrides or {}))
        row: dict[str, Any] = {}
        for attempt in range(max(0, int(retry_limit)) + 1):
            attempt_seed = seed if attempt == 0 else f"{seed}:retry:{attempt}"
            attempt_config = {**config, "seed": attempt_seed}
            started = time.perf_counter()
            try:
                local_hook = _local_validator_for_method(method, attempt_config)
                level = generate_level(etg, attempt_config, rng_from_seed(f"{attempt_seed}:geometry"), local_hook)
                report = evaluate_level_quality(level, etg, {"topology": topology_options})
                runtime_sec = time.perf_counter() - started
                if runtime_sec > float(run_timeout_sec):
                    raise TimeoutError(f"run exceeded {float(run_timeout_sec):.3f} seconds")
                metrics = report["metrics"]
                valid, failure_reason, budget_limit = _evaluation_failure(report)
                topology = report.get("topology") or {}
                structural_pass = topology.get("structural_pass") or {}
                strict_structural_failure = (
                    not bool(structural_pass.get("ok", topology.get("ok", False)))
                    or not bool((topology.get("key_lock_order") or {}).get("ok", True))
                )
                if str((attempt_config.get("ablationGroup") or "")):
                    valid = valid and not strict_structural_failure
                    if strict_structural_failure and failure_reason == "ok":
                        failure_reason = "strict_structural_failure"
                row = {
                    "task_id": task_id,
                    "status": "success",
                    "method_id": method["id"],
                    "scale": etg_entry.get("scale"),
                    "etg_id": etg_entry["id"],
                    "repeat": repeat,
                    "attempt": attempt,
                    "seed": attempt_seed,
                    "runtime_sec": runtime_sec,
                    "valid": valid,
                    "failure_reason": failure_reason,
                    "budget_limit": budget_limit,
                    "strict_structural_failure": strict_structural_failure,
                    "overall_score": float(metrics.get("overall_score", 0.0)),
                    "playability": float((metrics.get("playability") or {}).get("score", 0.0)),
                    "key_lock_consistency": float((metrics.get("key_lock_consistency") or {}).get("score", 0.0)),
                    "controllability": float((metrics.get("controllability") or {}).get("score", 0.0)),
                    "topology_validity": float((metrics.get("topological_consistency") or {}).get("topology_validity", 0.0)),
                    "topological_consistency": float((metrics.get("topological_consistency") or {}).get("score", 0.0)),
                    "pacing_variation": float((metrics.get("fun_proxy") or {}).get("score", 0.0)),
                    "content_variation": float((metrics.get("component_diversity") or {}).get("score", 0.0)),
                    "balance": float((metrics.get("balance") or {}).get("score", 0.0)),
                    "signature": report.get("signature") or {},
                    "config": attempt_config,
                    "topology_options": topology_options,
                }
                if save_each:
                    task_dir = run_dir / "runs" / str(method["id"]) / str(etg_entry["scale"]) / str(etg_entry["id"])
                    task_dir.mkdir(parents=True, exist_ok=True)
                    write_json(task_dir / f"level_{repeat:04d}.json", level)
                    write_json(task_dir / f"evaluation_{repeat:04d}.json", report)
                break
            except Exception as error:
                row = {
                    "task_id": task_id,
                    "status": "failed",
                    "method_id": method["id"],
                    "scale": etg_entry.get("scale"),
                    "etg_id": etg_entry["id"],
                    "repeat": repeat,
                    "attempt": attempt,
                    "seed": attempt_seed,
                    "runtime_sec": time.perf_counter() - started,
                    "error": f"{type(error).__name__}: {error}",
                    "valid": False,
                    "failure_reason": "budget_limit" if isinstance(error, TimeoutError) else f"run_error:{type(error).__name__}",
                    "budget_limit": isinstance(error, TimeoutError),
                    "strict_structural_failure": True,
                    "config": attempt_config,
                    "topology_options": topology_options,
                }
                if attempt >= max(0, int(retry_limit)):
                    break
        records[task_id] = row
        records_path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in records.values()) + "\n", encoding="utf-8")

    ordered = [records[task_id] for task_id, *_ in tasks if task_id in records]
    _write_csv(run_dir / "summary_by_method.csv", _summaries(ordered, ["method_id"]))
    _write_csv(run_dir / "summary_by_scale.csv", _summaries(ordered, ["scale", "method_id"]))
    _write_csv(run_dir / "summary_by_etg.csv", _summaries(ordered, ["scale", "etg_id", "method_id"]))
    _write_csv(run_dir / "failure_breakdown.csv", _failure_breakdown(ordered))
    _write_csv(run_dir / "failure_breakdown_by_scale.csv", _failure_breakdown(ordered, include_scale=True))
    successful = sum(1 for row in ordered if row.get("status") == "success")
    valid = sum(1 for row in ordered if bool(row.get("valid")))
    budget_limited = sum(1 for row in ordered if bool(row.get("budget_limit")))
    workflow = {
        "complete": len(ordered) == len(tasks),
        "expected_runs": len(tasks),
        "successful_runs": successful,
        "failed_runs": len(ordered) - successful,
        "valid_runs": valid,
        "invalid_runs": len(ordered) - valid,
        "budget_limit_runs": budget_limited,
        "strict": bool(strict),
        "retry_limit": int(retry_limit),
        "run_timeout_sec": float(run_timeout_sec),
        "resume": bool(resume),
        "paper_config": paper,
    }
    write_json(run_dir / "workflow_status.json", workflow)
    return {"run_id": run_name, "run_dir": str(run_dir), "workflow_status": workflow, "records": ordered}

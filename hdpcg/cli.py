"""CLI for Python HDPCG framework."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .experiment_runner import run_benchmark
from .etg_core import normalize_etg
from .etg_generator import create_etg, summarize_etg
from .etg_qd_selection import make_etg_bank
from .evaluate import evaluate_batch_quality, evaluate_level_quality
from .experiment_scale_profiles import list_scale_names
from .exporter import build_export_package
from .generator import generate_level
from .io_utils import extract_level_and_etg, read_json, write_json
from .paper_config import load_paper_config
from .random_utils import rng_from_seed
from .topology import validate_global_topology, validate_local_topology
from .visualize import write_etg_comparison_html, write_etg_html, write_level_5d_html


def _default_cpsat_time_limit(length: int) -> float:
    n = max(1, int(length))
    if n <= 6:
        return 2.0
    if n <= 10:
        return 4.0
    return 8.0


def _load_json_arg(raw: str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    txt = str(raw).strip()
    if not txt:
        return None
    candidate = Path(txt)
    if candidate.exists() and candidate.is_file():
        data = read_json(candidate)
    else:
        data = json.loads(txt)
    if not isinstance(data, dict):
        raise ValueError("JSON argument must be an object")
    return data


def _build_config(args: argparse.Namespace) -> dict[str, Any]:
    paper = load_paper_config()
    state = paper["state_model"]
    profiles = {item["id"]: item["config"] for item in paper["benchmark"]["methods"]}
    cpsat_profile = profiles["cpsat"]
    config = {
        "seed": args.seed,
        "length": args.length,
        "difficulty": args.difficulty,
        "branchChance": args.branch_chance,
        "keyLock": args.key_lock,
        "generatorMode": args.generator_mode,
        "maxAttempts": args.max_attempts,
        "sectorCount": args.sector_count,
        "safetyMargin": args.safety_margin,
        "headingJitterRange": args.heading_jitter_range,
        "lateralJitterMin": args.lateral_jitter_min,
        "lateralJitterMax": args.lateral_jitter_max,
        "componentStrategy": args.component_strategy,
        "candidatePoolSize": args.candidate_pool_size,
        "selectionTopP": args.selection_top_p,
        "selectionTemperature": args.selection_temperature,
        "noveltyWeight": args.novelty_weight,
        "alignmentWeight": args.alignment_weight,
        "playabilityWeight": args.playability_weight,
        "shapeWeight": args.shape_weight,
        "riskWeight": args.risk_weight,
        "maxLocalRejects": args.max_local_rejects,
        "fallbackEnabled": args.fallback_enabled,
        "familyBalanceWindow": args.family_balance_window,
        "maxCanonicalRetries": args.max_canonical_retries,
        "gaPopulation": args.ga_population,
        "gaGenerations": args.ga_generations,
        "gaEliteRatio": args.ga_elite_ratio,
        "gaMutationRate": args.ga_mutation_rate,
        "gaTournamentSize": args.ga_tournament_size,
        "topologyMaxTime": args.topology_max_time,
        "topologyMaxStates": args.topology_max_states,
        "topologyMaxJumpOffsets": args.topology_max_jump_offsets,
        "topologyMaxGroundDistance": args.topology_max_ground_distance,
        "topologyMaxJumpDistance": args.topology_max_jump_distance,
        "topologyAllowJump": args.topology_allow_jump,
        "topologyAllowDrop": args.topology_allow_drop,
        "gaTopologyMaxTime": args.ga_topology_max_time,
        "gaTopologyMaxStates": args.ga_topology_max_states,
        "gaTopologyMaxJumpOffsets": args.ga_topology_max_jump_offsets,
        "gaTopologyMaxGroundDistance": args.ga_topology_max_ground_distance,
        "gaTopologyMaxJumpDistance": args.ga_topology_max_jump_distance,
        "gaTopologyAllowJump": args.ga_topology_allow_jump,
        "gaTopologyAllowDrop": args.ga_topology_allow_drop,
        "validationMaxTime": args.validation_max_time,
        "validationMaxStates": args.validation_max_states,
        "validationMaxQueue": args.validation_max_queue,
        "validationMaxJumpOffsets": args.validation_max_jump_offsets,
        "validationModelPadding": args.validation_model_padding,
        "validationLocalPaddingCells": args.validation_local_padding_cells,
        "validationAllowJump": args.validation_allow_jump,
        "validationAllowDrop": args.validation_allow_drop,
        "validationToleranceRadiusCells": args.validation_tolerance_radius_cells,
        "validationAllowSiblingTolerance": args.validation_allow_sibling_tolerance,
        "cpSatTimeLimitSec": (
            float(args.cp_sat_time_limit_sec)
            if args.cp_sat_time_limit_sec is not None
            else _default_cpsat_time_limit(int(args.length))
        ),
        "cpSatNumWorkers": (
            int(args.cp_sat_num_workers)
            if args.cp_sat_num_workers is not None
            else int(cpsat_profile.get("cpSatNumWorkers", 1))
        ),
        "cpSatLaneRange": int(args.cp_sat_lane_range),
        "cpSatXBound": args.cp_sat_x_bound,
        "cpSatRelaxRounds": int(args.cp_sat_relax_rounds),
        "cpSatRandomSeed": args.cp_sat_random_seed,
        "timeStep": float(state["time_step_seconds"]),
        "maxTimeHorizon": int(state["max_time_horizon"]),
        "maxPeriodTicks": int(state["max_period_ticks"]),
        "validationMaxTimeHorizon": int(state["max_time_horizon"]),
        "validationMaxPeriodTicks": int(state["max_period_ticks"]),
    }
    if args.generator_mode == "hdpcg_incremental":
        main_profile = paper["benchmark"]["methods"][0]["config"]
        config = {**main_profile, **config}
    return config


def _topology_options(args: argparse.Namespace) -> dict[str, Any]:
    state = load_paper_config()["state_model"]
    return {
        "timeStep": float(state["time_step_seconds"]),
        "maxTimeHorizon": int(state["max_time_horizon"]),
        "maxPeriodTicks": int(state["max_period_ticks"]),
        "maxTime": args.topology_max_time,
        "maxStates": args.topology_max_states,
        "maxJumpOffsets": args.topology_max_jump_offsets,
        "maxGroundDistance": args.topology_max_ground_distance,
        "maxJumpDistance": args.topology_max_jump_distance,
        "allowJump": args.topology_allow_jump,
        "allowDrop": args.topology_allow_drop,
    }


def cmd_generate(args: argparse.Namespace) -> int:
    config = _build_config(args)

    if args.etg:
        raw = read_json(args.etg)
        _, etg, _ = extract_level_and_etg(raw)
        if etg is None:
            raise ValueError("--etg file does not contain an ETG payload")
        etg = normalize_etg(etg, {"defaultSpeed": (etg.get("meta") or {}).get("defaultSpeed")})
    else:
        rng_etg = rng_from_seed(f"{config['seed']}-etg")
        etg = create_etg(config, rng_etg)

    rng_geo = rng_from_seed(f"{config['seed']}-geo")
    local_hook = validate_local_topology if args.topology_validate else None
    level = generate_level(etg, config, rng_geo, local_hook)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    etg_path = out_dir / f"etg_{config['seed']}.json"
    level_path = out_dir / f"level_{config['seed']}.json"
    package_path = out_dir / f"level_package_{config['seed']}.json"

    topology = None
    topo_options = _topology_options(args)

    if args.global_topology:
        topology = validate_global_topology(level, etg, topo_options)
        write_json(out_dir / f"topology_{config['seed']}.json", topology)
        if args.etg_html:
            write_etg_comparison_html(etg, topology.get("observed_etg") or {"nodes": [], "edges": []}, out_dir / f"observed_etg_{config['seed']}.html")
            write_etg_html(etg, out_dir / f"etg_expected_{config['seed']}.html", title="Expected ETG")
            write_etg_html(topology.get("observed_etg") or {"nodes": [], "edges": []}, out_dir / f"etg_observed_{config['seed']}.html", title="Observed ETG from 5D")

    component_diagnostics = ((level.get("meta") or {}).get("component_generation") or {}).get("selection_stats") or {}
    report = {
        "status": "ok" if topology and topology.get("ok") else ("failed" if topology else "not_run"),
        "scope": "global_5d" if topology is not None else ("generation_time_local" if args.topology_validate else "generation_only"),
        "issues": [] if topology is None or topology.get("ok") else [str(topology.get("reason") or "invalid")],
        "fixes": [],
        "warnings": (
            []
            if topology is not None
            else (["global_topology_not_requested"] if args.topology_validate else ["local_validation_disabled", "global_topology_not_requested"])
        ),
        "configuration": topo_options,
        "generation_diagnostics": component_diagnostics,
        "topology": topology,
    }
    package = build_export_package(level, report, {"sampleDuration": args.sample_duration, "sampleStep": args.sample_step})
    write_json(etg_path, etg)
    write_json(level_path, level)
    write_json(package_path, package)

    if args.visualize:
        write_level_5d_html(
            level,
            out_dir / f"viewer_5d_{config['seed']}.html",
            {
                "visualMaxTime": args.visual_max_time,
                "timeStep": config["timeStep"],
                "maxTimeHorizon": config["maxTimeHorizon"],
                "maxPeriodTicks": config["maxPeriodTicks"],
                "maxStates": args.visual_max_states,
                "maxJumpOffsets": args.visual_max_jump_offsets,
                "maxGroundDistance": args.visual_max_ground_distance,
                "maxJumpDistance": args.visual_max_jump_distance,
                "skipReachable": (not args.visual_with_reachable),
            },
        )

    summary = {
        "seed": config["seed"],
        "generator_mode": config["generatorMode"],
        "paths": {"etg": str(etg_path), "level": str(level_path), "package": str(package_path)},
        "etg_summary": summarize_etg(etg),
        "topology_ok": bool((topology or {}).get("ok", False)) if topology is not None else None,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def cmd_check_topology(args: argparse.Namespace) -> int:
    raw = read_json(args.input)
    level, etg, kind = extract_level_and_etg(raw)

    if level is None:
        if not etg:
            raise ValueError("Topology check requires level/package input or ETG + --generate-temp")
        config = _build_config(args)
        level = generate_level(etg, config, rng_from_seed(f"{config['seed']}-geo"), validate_local_topology if args.topology_validate else None)

    etg_expected = read_json(args.expected_etg) if args.expected_etg else (etg or level.get("etg"))
    topo = validate_global_topology(
        level,
        etg_expected,
        _topology_options(args),
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, topo)

    if args.out_observed_etg:
        write_json(args.out_observed_etg, topo.get("observed_etg") or {"version": 2, "nodes": [], "edges": []})

    if args.etg_html and etg_expected:
        write_etg_comparison_html(etg_expected, topo.get("observed_etg") or {"nodes": [], "edges": []}, args.etg_html)
        etg_html_path = Path(args.etg_html)
        write_etg_html(etg_expected, etg_html_path.with_name(f"{etg_html_path.stem}_expected{etg_html_path.suffix}"), title="Expected ETG")
        write_etg_html(
            topo.get("observed_etg") or {"nodes": [], "edges": []},
            etg_html_path.with_name(f"{etg_html_path.stem}_observed{etg_html_path.suffix}"),
            title="Observed ETG from 5D",
        )

    if args.visualize:
        write_level_5d_html(
            level,
            args.visualize,
            {
                "visualMaxTime": args.visual_max_time,
                "maxStates": args.visual_max_states,
                "maxJumpOffsets": args.visual_max_jump_offsets,
                "maxGroundDistance": args.visual_max_ground_distance,
                "maxJumpDistance": args.visual_max_jump_distance,
                "skipReachable": (not args.visual_with_reachable),
            },
        )

    print(json.dumps({"input_kind": kind, "out": str(out), "ok": topo.get("ok"), "fidelity": topo.get("fidelity_score")}, ensure_ascii=False, indent=2))
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    levels = []
    etgs = []

    for p in inputs:
        raw = read_json(p)
        level, etg, _ = extract_level_and_etg(raw)
        if level is None:
            if not etg:
                raise ValueError(f"{p} is not ETG/level/package")
            config = _build_config(args)
            level = generate_level(etg, config, rng_from_seed(f"{config['seed']}-geo"), validate_local_topology if args.topology_validate else None)
        levels.append(level)
        etgs.append(etg or level.get("etg"))

    if len(levels) == 1:
        report = evaluate_level_quality(
            levels[0],
            etgs[0],
            {
                "topology": _topology_options(args)
            },
        )
    else:
        report = evaluate_batch_quality(
            levels,
            etgs,
            {
                "topology": _topology_options(args)
            },
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, report)
    print(json.dumps({"out": str(out), "count": len(levels), "ok": True}, ensure_ascii=False, indent=2))
    return 0


def cmd_experiment(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    levels = []
    etgs = []
    items = []

    for i in range(args.num):
        seed = f"{args.seed_prefix}_{i}"
        config = _build_config(args)
        config["seed"] = seed
        etg = create_etg(config, rng_from_seed(f"{seed}-etg"))
        level = generate_level(etg, config, rng_from_seed(f"{seed}-geo"), validate_local_topology if args.topology_validate else None)

        levels.append(level)
        etgs.append(etg)
        items.append({"seed": seed, "etg_summary": summarize_etg(etg)})

        if args.save_each:
            write_json(out_dir / f"level_{seed}.json", level)
            write_json(out_dir / f"etg_{seed}.json", etg)

    batch = evaluate_batch_quality(
        levels,
        etgs,
        {
            "topology": _topology_options(args)
        },
    )
    batch["items"] = items
    write_json(out_dir / "experiment_report.json", batch)

    print(json.dumps({"count": args.num, "out": str(out_dir / 'experiment_report.json'), "mean_score": batch.get("overall_score", {}).get("mean")}, ensure_ascii=False, indent=2))
    return 0


def cmd_make_etg_bank(args: argparse.Namespace) -> int:
    scales = [s.strip().lower() for s in (args.scales or list_scale_names()) if str(s).strip()]
    manifest = make_etg_bank(
        args.out_dir,
        pool_size=args.pool_size,
        select_count=args.select_count,
        seed_prefix=args.seed_prefix,
        scales=scales,
        extra_batch_size=args.extra_batch_size,
        max_extra_batches=args.max_extra_batches,
    )
    workflow = {
        "command": "make-etg-bank",
        "out_dir": str(args.out_dir),
        "manifest": str(Path(args.out_dir) / "dataset_manifest.json"),
        "dataset_incomplete": bool(manifest.get("dataset_incomplete")),
        "selected_total": len(manifest.get("selected_global") or []),
        "scales": scales,
    }
    write_json(Path(args.out_dir) / "workflow_status.json", workflow)
    print(json.dumps(workflow, ensure_ascii=False, indent=2))
    return 0


def cmd_run_benchmark(args: argparse.Namespace) -> int:
    topology_overrides = _load_json_arg(args.topology_overrides)
    topology_overrides_by_scale = _load_json_arg(args.topology_overrides_by_scale)
    method_profiles = None
    if args.method_profiles:
        loaded_profiles = _load_json_arg(args.method_profiles)
        if loaded_profiles is not None:
            profiles = loaded_profiles.get("methods") if isinstance(loaded_profiles.get("methods"), list) else loaded_profiles.get("method_profiles")
            if isinstance(profiles, list):
                method_profiles = profiles

    report = run_benchmark(
        args.manifest,
        args.out_dir,
        n=args.n,
        strict=bool(args.strict),
        retry_limit=args.retry_limit,
        run_timeout_sec=args.run_timeout_sec,
        save_each=bool(args.save_each),
        base_seed=args.seed_prefix,
        topology_overrides=topology_overrides,
        topology_overrides_by_scale=topology_overrides_by_scale,
        method_profiles=method_profiles,
        run_id=args.run_id,
        resume=bool(args.resume),
        reset_run=bool(args.reset_run),
        allow_n_increase=bool(args.allow_n_increase),
    )
    workflow = report.get("workflow_status") or {}
    print(
        json.dumps(
            {
                "command": "run-benchmark",
                "manifest": str(args.manifest),
                "run_dir": report.get("run_dir"),
                "complete": workflow.get("complete"),
                "expected_runs": workflow.get("expected_runs"),
                "successful_runs": workflow.get("successful_runs"),
                "failed_runs": workflow.get("failed_runs"),
                "run_id": report.get("run_id"),
                "resume": workflow.get("resume"),
                "metric_profile": "paper",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    paper = load_paper_config()
    selection = paper["candidate_selection"]
    weights = selection["weights"]
    benchmark = paper["benchmark"]
    state = paper["state_model"]
    validation = paper["validation"]
    local_validation = validation["local"]
    medium_validation = validation["strict_by_scale"]["medium"]
    etg_bank = paper["etg_bank"]
    execution = paper["execution"]
    profiles = {item["id"]: item["config"] for item in benchmark["methods"]}
    main_profile = profiles["main"]
    ga_profile = profiles["ga"]
    cpsat_profile = profiles["cpsat"]
    parser = argparse.ArgumentParser(prog="hdpcg", description="Python ETG->5D PCG framework")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--seed", default="paper-demo")
    common.add_argument("--length", type=int, default=9)
    common.add_argument("--difficulty", type=float, default=0.55)
    common.add_argument("--branch-chance", type=float, default=0.7)
    common.add_argument("--key-lock", action="store_true", default=True)
    common.add_argument(
        "--generator-mode",
        default="hdpcg_incremental",
        choices=["hdpcg_incremental", "lane", "constraint_based", "constraint", "ga_baseline", "ga", "cpsat_baseline", "cpsat", "cp_sat"],
    )
    common.add_argument("--max-attempts", type=int, default=14)
    common.add_argument("--sector-count", type=int, default=8)
    common.add_argument("--safety-margin", type=float, default=1.0)
    common.add_argument("--heading-jitter-range", type=float, default=0.35)
    common.add_argument("--lateral-jitter-min", type=float, default=1.0)
    common.add_argument("--lateral-jitter-max", type=float, default=2.2)
    common.add_argument("--component-strategy", default="diverse", choices=["legacy", "diverse"])
    common.add_argument("--candidate-pool-size", type=int, default=int(selection["pool_size"]))
    common.add_argument("--selection-top-p", type=float, default=float(selection["top_p"]))
    common.add_argument("--selection-temperature", type=float, default=float(selection["temperature"]))
    common.add_argument("--novelty-weight", type=float, default=float(weights["novelty"]))
    common.add_argument("--alignment-weight", type=float, default=float(weights["alignment"]))
    common.add_argument("--playability-weight", type=float, default=float(weights["playability"]))
    common.add_argument("--shape-weight", type=float, default=float(weights["shape"]))
    common.add_argument("--risk-weight", type=float, default=float(weights["risk"]))
    common.add_argument("--max-local-rejects", type=int, default=int(main_profile["maxLocalRejects"]))
    common.add_argument("--family-balance-window", type=int, default=40)
    common.add_argument("--max-canonical-retries", type=int, default=int(main_profile["maxCanonicalRetries"]))
    common.add_argument("--fallback-enabled", dest="fallback_enabled", action="store_true")
    common.add_argument("--no-fallback-enabled", dest="fallback_enabled", action="store_false")
    common.set_defaults(fallback_enabled=True)
    common.add_argument("--ga-population", type=int, default=int(ga_profile["gaPopulation"]))
    common.add_argument("--ga-generations", type=int, default=int(ga_profile["gaGenerations"]))
    common.add_argument("--ga-elite-ratio", type=float, default=float(ga_profile["gaEliteRatio"]))
    common.add_argument("--ga-mutation-rate", type=float, default=float(ga_profile["gaMutationRate"]))
    common.add_argument("--ga-tournament-size", type=int, default=int(ga_profile["gaTournamentSize"]))
    common.add_argument("--topology-validate", dest="topology_validate", action="store_true")
    common.add_argument("--no-topology-validate", dest="topology_validate", action="store_false")
    common.set_defaults(topology_validate=True)
    common.add_argument("--validation-max-time", type=int, default=int(local_validation["max_time"]))
    common.add_argument("--validation-max-states", type=int, default=int(local_validation["max_states"]))
    common.add_argument("--validation-max-queue", type=int, default=int(local_validation["max_queue"]))
    common.add_argument("--validation-max-jump-offsets", type=int, default=int(local_validation["max_jump_offsets"]))
    common.add_argument("--validation-model-padding", type=int, default=int(state["local_model_padding_cells"]))
    common.add_argument("--validation-local-padding-cells", type=int, default=int(state["local_padding_cells"]))
    common.add_argument("--validation-allow-jump", action="store_true", default=bool(validation["allow_jump"]))
    common.add_argument("--validation-allow-drop", action="store_true", default=bool(validation["allow_drop"]))
    common.add_argument("--validation-tolerance-radius-cells", type=int, default=int(state["sibling_tolerance_radius_cells"]))
    common.add_argument("--validation-allow-sibling-tolerance", action="store_true", default=bool(local_validation["allow_sibling_tolerance"]))
    common.add_argument("--cp-sat-time-limit-sec", type=float, default=float(cpsat_profile["cpSatTimeLimitSec"]))
    common.add_argument("--cp-sat-num-workers", type=int, default=None)
    common.add_argument("--cp-sat-lane-range", type=int, default=int(cpsat_profile["cpSatLaneRange"]))
    common.add_argument("--cp-sat-x-bound", type=int, default=None)
    common.add_argument("--cp-sat-relax-rounds", type=int, default=int(cpsat_profile["cpSatRelaxRounds"]))
    common.add_argument("--cp-sat-random-seed", type=int, default=None)
    common.add_argument("--topology-max-time", type=int, default=None)
    common.add_argument("--topology-max-states", type=int, default=int(medium_validation["max_states"]))
    common.add_argument("--topology-max-jump-offsets", type=int, default=int(medium_validation["max_jump_offsets"]))
    common.add_argument("--topology-max-ground-distance", type=float, default=None)
    common.add_argument("--topology-max-jump-distance", type=float, default=None)
    common.add_argument("--topology-allow-jump", action="store_true", default=True)
    common.add_argument("--topology-allow-drop", action="store_true", default=True)
    common.add_argument("--ga-topology-max-time", type=int, default=None)
    common.add_argument("--ga-topology-max-states", type=int, default=450000)
    common.add_argument("--ga-topology-max-jump-offsets", type=int, default=1400)
    common.add_argument("--ga-topology-max-ground-distance", type=float, default=None)
    common.add_argument("--ga-topology-max-jump-distance", type=float, default=None)
    common.add_argument("--ga-topology-allow-jump", action="store_true", default=True)
    common.add_argument("--ga-topology-allow-drop", action="store_true", default=True)
    common.add_argument("--visual-max-states", type=int, default=250000)
    common.add_argument("--visual-max-jump-offsets", type=int, default=1400)
    common.add_argument("--visual-max-ground-distance", type=float, default=None)
    common.add_argument("--visual-max-jump-distance", type=float, default=None)
    common.add_argument("--visual-max-time", type=int, default=-1)
    common.add_argument("--visual-with-reachable", dest="visual_with_reachable", action="store_true")
    common.add_argument("--visual-skip-reachable", dest="visual_with_reachable", action="store_false")
    common.set_defaults(visual_with_reachable=True)

    p_gen = sub.add_parser("generate", parents=[common], help="Generate ETG/Level/Package")
    p_gen.add_argument("--etg", help="Input ETG JSON (optional)")
    p_gen.add_argument("--out-dir", default="out")
    p_gen.add_argument("--sample-duration", type=float, default=12.0)
    p_gen.add_argument("--sample-step", type=float, default=1.0)
    p_gen.add_argument("--visualize", action="store_true")
    p_gen.add_argument("--global-topology", action="store_true")
    p_gen.add_argument("--etg-html", action="store_true")
    p_gen.set_defaults(func=cmd_generate)

    p_top = sub.add_parser("check-topology", parents=[common], help="Run global 5D topology check")
    p_top.add_argument("--input", required=True, help="ETG / level / package JSON")
    p_top.add_argument("--expected-etg", help="Expected ETG JSON")
    p_top.add_argument("--out", default="out/topology_report.json")
    p_top.add_argument("--out-observed-etg", default="out/observed_etg.json")
    p_top.add_argument("--visualize", help="Output 5D viewer HTML")
    p_top.add_argument("--etg-html", help="Output ETG comparison HTML")
    p_top.set_defaults(func=cmd_check_topology)

    p_eval = sub.add_parser("evaluate", parents=[common], help="Evaluate generated level quality")
    p_eval.add_argument("--input", nargs="+", required=True)
    p_eval.add_argument("--out", default="out/evaluation_report.json")
    p_eval.set_defaults(func=cmd_evaluate)

    p_exp = sub.add_parser("experiment", parents=[common], help="Run batch experiment")
    p_exp.add_argument("--num", type=int, default=10)
    p_exp.add_argument("--seed-prefix", default="exp")
    p_exp.add_argument("--out-dir", default="out/experiment")
    p_exp.add_argument("--save-each", action="store_true")
    p_exp.set_defaults(func=cmd_experiment)

    p_bank = sub.add_parser("make-etg-bank", help="Build the QD ETG benchmark bank")
    p_bank.add_argument("--out-dir", default="out/etg_bank")
    p_bank.add_argument("--pool-size", type=int, default=int(etg_bank["pool_size"]))
    p_bank.add_argument("--select-count", type=int, default=int(etg_bank["select_count"]))
    p_bank.add_argument("--seed-prefix", default=str(etg_bank["seed_prefix"]))
    p_bank.add_argument("--scales", nargs="+", default=list_scale_names())
    p_bank.add_argument("--extra-batch-size", type=int, default=int(etg_bank["extra_batch_size"]))
    p_bank.add_argument("--max-extra-batches", type=int, default=int(etg_bank["max_extra_batches"]))
    p_bank.set_defaults(func=cmd_make_etg_bank)

    p_cog = sub.add_parser("run-benchmark", help="Run the five-method benchmark")
    p_cog.add_argument("--manifest", default="out/etg_bank/dataset_manifest.json")
    p_cog.add_argument("--out-dir", default="out")
    p_cog.add_argument("--n", type=int, default=int(benchmark["repeats"]))
    p_cog.add_argument("--retry-limit", type=int, default=int(execution["retry_limit"]))
    p_cog.add_argument("--run-timeout-sec", type=float, default=float(execution["run_timeout_sec"]))
    p_cog.add_argument("--seed-prefix", default=str(execution["seed_prefix"]))
    p_cog.add_argument("--run-id", default=None)
    p_cog.add_argument("--topology-overrides", default=None, help="JSON object or path for global topology overrides")
    p_cog.add_argument("--topology-overrides-by-scale", default=None, help="JSON object or path for per-scale topology overrides")
    p_cog.add_argument("--method-profiles", default=None, help="JSON object (or path) with `methods` list")
    p_cog.add_argument("--strict", dest="strict", action="store_true")
    p_cog.add_argument("--no-strict", dest="strict", action="store_false")
    p_cog.set_defaults(strict=bool(benchmark["strict"]))
    p_cog.add_argument("--resume", dest="resume", action="store_true")
    p_cog.add_argument("--no-resume", dest="resume", action="store_false")
    p_cog.set_defaults(resume=bool(execution["resume"]))
    p_cog.add_argument("--reset-run", action="store_true", default=False)
    p_cog.add_argument("--allow-n-increase", action="store_true", default=False)
    p_cog.add_argument("--save-each", dest="save_each", action="store_true")
    p_cog.add_argument("--no-save-each", dest="save_each", action="store_false")
    p_cog.set_defaults(save_each=bool(execution["save_each"]))
    p_cog.set_defaults(func=cmd_run_benchmark)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

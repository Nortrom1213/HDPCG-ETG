"""Solver-based CP-SAT baseline for ETG-to-level generation."""

from __future__ import annotations

import math
from typing import Any

from .etg_core import NODE_TYPES, compute_canonical_route
from .random_utils import Mulberry32

try:
    from ortools.sat.python import cp_model
except Exception:  # pragma: no cover - optional dependency guard
    cp_model = None  # type: ignore[assignment]


def _clamp_int(value: Any, lo: int, hi: int) -> int:
    try:
        n = int(round(float(value)))
    except Exception:
        n = lo
    return max(lo, min(hi, n))


def _node_has_type(node: dict[str, Any], t: str) -> bool:
    types = (
        node.get("types")
        if isinstance(node.get("types"), list) and node.get("types")
        else ([node.get("type")] if node.get("type") else [])
    )
    return t in types


def _build_neighbors(edges: list[dict[str, Any]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for edge in edges:
        a = edge.get("from")
        b = edge.get("to")
        if not a or not b or a == b:
            continue
        out.setdefault(a, set()).add(b)
        out.setdefault(b, set()).add(a)
    return out


def _cfg_value(config: dict[str, Any], key: str, default: Any) -> Any:
    value = config.get(key, default)
    return default if value is None else value


def _derive_defaults(etg: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    canonical = compute_canonical_route(etg, {"defaultSpeed": (etg.get("meta") or {}).get("defaultSpeed")})
    canonical_len = float(canonical.get("totalLength", 120.0) or 120.0)
    node_count = max(1, len(etg.get("nodes") or []))
    lane_spacing_world = _clamp_int(_cfg_value(config, "cpSatLaneSpacingWorld", 22), 8, 64)
    min_sep = _clamp_int(_cfg_value(config, "cpSatMinSeparation", 8), 4, 28)
    x_bound_default = max(80, int(round(canonical_len * 1.55)) + node_count * 8)
    return {
        "lane_spacing_world": lane_spacing_world,
        "lane_range": _clamp_int(_cfg_value(config, "cpSatLaneRange", 3), 1, 10),
        "x_bound": _clamp_int(_cfg_value(config, "cpSatXBound", x_bound_default), 40, 4000),
        "min_sep": min_sep,
        "node_width": _clamp_int(_cfg_value(config, "cpSatNodeWidth", 8), 4, 24),
        "node_depth": _clamp_int(_cfg_value(config, "cpSatNodeDepth", 8), 4, 24),
        "z_stride": _clamp_int(_cfg_value(config, "cpSatZStride", 12), 6, 32),
        "time_limit_sec": float(_cfg_value(config, "cpSatTimeLimitSec", 4.0)),
        "deterministic_time_limit": float(
            _cfg_value(config, "cpSatDeterministicTimeLimit", _cfg_value(config, "cpSatTimeLimitSec", 4.0))
        ),
        "num_workers": _clamp_int(_cfg_value(config, "cpSatNumWorkers", 1), 1, 32),
        "relax_rounds": _clamp_int(_cfg_value(config, "cpSatRelaxRounds", 2), 0, 4),
        "random_seed": _clamp_int(_cfg_value(config, "cpSatRandomSeed", 1), 1, 2_000_000_000),
        "w_len": _clamp_int(_cfg_value(config, "cpSatWeightLen", 10), 1, 50),
        "w_lane": _clamp_int(_cfg_value(config, "cpSatWeightLane", 2), 0, 20),
        "w_span": _clamp_int(_cfg_value(config, "cpSatWeightSpan", 1), 0, 20),
        "w_canon": _clamp_int(_cfg_value(config, "cpSatWeightCanonBend", 2), 0, 20),
        "key_before_lock_margin": _clamp_int(_cfg_value(config, "cpSatKeyBeforeLockMargin", 10), 0, 80),
        "canonical": canonical,
    }


def solve_anchor_layout_cp_sat(etg: dict[str, Any], config: dict[str, Any], rng: Mulberry32) -> dict[str, Any]:
    if cp_model is None:
        return {
            "ok": False,
            "status": "ortools_missing",
            "reason": "ortools not installed",
            "relax_round": -1,
            "anchors": {},
            "solver_stats": {},
        }

    nodes = [n for n in (etg.get("nodes") or []) if n.get("id")]
    edges = [e for e in (etg.get("edges") or []) if e.get("from") and e.get("to")]
    if not nodes or not edges:
        return {
            "ok": False,
            "status": "invalid_etg",
            "reason": "missing nodes/edges",
            "relax_round": -1,
            "anchors": {},
            "solver_stats": {},
        }

    by_id = {n["id"]: n for n in nodes}
    key_node_by_key_id: dict[str, str] = {}
    for node in nodes:
        key_id = node.get("key_id")
        if _node_has_type(node, NODE_TYPES["KEY"]) and key_id and str(key_id) not in key_node_by_key_id:
            key_node_by_key_id[str(key_id)] = str(node["id"])
    start = next((n for n in nodes if _node_has_type(n, NODE_TYPES["START"])), None)
    if not start:
        return {
            "ok": False,
            "status": "invalid_etg",
            "reason": "missing start",
            "relax_round": -1,
            "anchors": {},
            "solver_stats": {},
        }

    defaults = _derive_defaults(etg, config)
    neighbors = _build_neighbors(edges)
    canonical_nodes = list((defaults["canonical"].get("nodes") or []))
    first_idx: dict[str, int] = {}
    for i, nid in enumerate(canonical_nodes):
        if nid not in first_idx:
            first_idx[nid] = i

    rand_seed = _clamp_int(_cfg_value(config, "cpSatRandomSeed", int(math.floor(rng.random() * 1_000_000_000))), 1, 2_000_000_000)
    base_lane_range = int(defaults["lane_range"])
    base_x_bound = int(defaults["x_bound"])
    base_min_sep = int(defaults["min_sep"])

    last_status = "unknown"
    last_reason = "no_solution"
    last_stats: dict[str, Any] = {}

    for relax_round in range(int(defaults["relax_rounds"]) + 1):
        lane_range = base_lane_range + relax_round
        x_bound = base_x_bound + relax_round * max(20, int(base_x_bound * 0.18))
        min_sep = max(4, base_min_sep - (2 if relax_round >= 2 else 0))

        model = cp_model.CpModel()
        node_width = int(defaults["node_width"])
        node_depth = int(defaults["node_depth"])
        z_stride = int(defaults["z_stride"])
        lane_spacing_world = int(defaults["lane_spacing_world"])

        x_left: dict[str, Any] = {}
        lane_var: dict[str, Any] = {}
        z_start: dict[str, Any] = {}
        x_intervals: list[Any] = []
        z_intervals: list[Any] = []

        max_z_index = max(1, (2 * lane_range + 1) * z_stride)

        for node in nodes:
            nid = node["id"]
            x_left[nid] = model.NewIntVar(0, x_bound, f"x_left_{nid}")
            lane_var[nid] = model.NewIntVar(-lane_range, lane_range, f"lane_{nid}")
            z_start[nid] = model.NewIntVar(0, max_z_index, f"z_start_{nid}")
            model.Add(z_start[nid] == (lane_var[nid] + lane_range) * z_stride)
            x_intervals.append(model.NewFixedSizeIntervalVar(x_left[nid], node_width, f"x_itv_{nid}"))
            z_intervals.append(model.NewFixedSizeIntervalVar(z_start[nid], node_depth, f"z_itv_{nid}"))

        model.AddNoOverlap2D(x_intervals, z_intervals)
        model.Add(x_left[start["id"]] == 0)
        model.Add(lane_var[start["id"]] == 0)

        dev_terms: list[Any] = []
        lane_terms: list[Any] = []
        bend_terms: list[Any] = []

        max_dist = x_bound + (2 * lane_range + 1) * lane_spacing_world + 20
        for i, edge in enumerate(edges):
            u = str(edge["from"])
            v = str(edge["to"])
            if u not in x_left or v not in x_left:
                continue
            dx = model.NewIntVar(-x_bound, x_bound, f"dx_{i}")
            adx = model.NewIntVar(0, x_bound, f"adx_{i}")
            dl = model.NewIntVar(-2 * lane_range, 2 * lane_range, f"dl_{i}")
            adl = model.NewIntVar(0, 2 * lane_range, f"adl_{i}")
            d = model.NewIntVar(0, max_dist, f"d_{i}")
            target = _clamp_int(edge.get("length", 30), 1, max_dist)
            delta = model.NewIntVar(-max_dist, max_dist, f"delta_{i}")
            dev = model.NewIntVar(0, max_dist, f"dev_{i}")
            model.Add(dx == x_left[u] - x_left[v])
            model.AddAbsEquality(adx, dx)
            model.Add(dl == lane_var[u] - lane_var[v])
            model.AddAbsEquality(adl, dl)
            model.Add(d == adx + lane_spacing_world * adl)
            model.Add(delta == d - target)
            model.AddAbsEquality(dev, delta)
            dev_terms.append(dev)
            lane_terms.append(adl)

        for i in range(len(canonical_nodes) - 1):
            a = canonical_nodes[i]
            b = canonical_nodes[i + 1]
            if a not in x_left or b not in x_left:
                continue
            if first_idx.get(b, 10**9) > first_idx.get(a, 10**9):
                model.Add(x_left[b] >= x_left[a] + min_sep)
                d_lane = model.NewIntVar(-2 * lane_range, 2 * lane_range, f"canon_dl_{i}")
                ad_lane = model.NewIntVar(0, 2 * lane_range, f"canon_adl_{i}")
                model.Add(d_lane == lane_var[a] - lane_var[b])
                model.AddAbsEquality(ad_lane, d_lane)
                bend_terms.append(ad_lane)

        for node in nodes:
            if not _node_has_type(node, NODE_TYPES["LOCK"]):
                continue
            nid = node["id"]
            neigh = sorted(list(neighbors.get(nid, set())))
            if len(neigh) != 2:
                continue
            a, b = neigh[0], neigh[1]
            if a not in x_left or b not in x_left:
                continue
            mn = model.NewIntVar(0, x_bound, f"lock_min_{nid}")
            mx = model.NewIntVar(0, x_bound, f"lock_max_{nid}")
            model.AddMinEquality(mn, [x_left[a], x_left[b]])
            model.AddMaxEquality(mx, [x_left[a], x_left[b]])
            model.Add(x_left[nid] >= mn)
            model.Add(x_left[nid] <= mx)
            required_key = node.get("requires_key_id")
            if required_key and str(required_key) in key_node_by_key_id:
                key_node = key_node_by_key_id[str(required_key)]
                margin = int(defaults["key_before_lock_margin"])
                model.Add(x_left[nid] >= x_left[key_node] + margin)

        x_max = model.NewIntVar(0, x_bound, "x_max")
        x_min = model.NewIntVar(0, x_bound, "x_min")
        span = model.NewIntVar(0, x_bound, "x_span")
        model.AddMaxEquality(x_max, [x_left[n["id"]] for n in nodes])
        model.AddMinEquality(x_min, [x_left[n["id"]] for n in nodes])
        model.Add(span == x_max - x_min)

        objective_terms = []
        if dev_terms:
            objective_terms.append(int(defaults["w_len"]) * sum(dev_terms))
        if lane_terms:
            objective_terms.append(int(defaults["w_lane"]) * sum(lane_terms))
        objective_terms.append(int(defaults["w_span"]) * span)
        if bend_terms:
            objective_terms.append(int(defaults["w_canon"]) * sum(bend_terms))
        model.Minimize(sum(objective_terms) if objective_terms else span)

        solver = cp_model.CpSolver()
        solver.parameters.max_deterministic_time = max(
            0.2, float(defaults["deterministic_time_limit"]) * (1.0 + 0.25 * relax_round)
        )
        solver.parameters.num_search_workers = int(defaults["num_workers"])
        solver.parameters.random_seed = int(rand_seed + relax_round)
        solver.parameters.log_search_progress = False
        solver.parameters.cp_model_presolve = True

        status = solver.Solve(model)
        status_name = solver.StatusName(status).lower()
        last_status = status_name
        last_stats = {
            "objective": float(solver.ObjectiveValue()) if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
            "deterministic_time": float(solver.ResponseProto().deterministic_time),
            "branches": int(solver.NumBranches()),
            "conflicts": int(solver.NumConflicts()),
        }

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            half = node_width * 0.5
            anchors: dict[str, dict[str, Any]] = {}
            for node in nodes:
                nid = node["id"]
                x_center = float(solver.Value(x_left[nid])) + half
                lane_idx = int(solver.Value(lane_var[nid]))
                z = float(lane_idx * lane_spacing_world)
                anchors[nid] = {
                    "x": x_center,
                    "y": 0.0,
                    "z": z,
                    "lane": lane_idx,
                }
            return {
                "ok": True,
                "status": status_name,
                "reason": None,
                "relax_round": relax_round,
                "anchors": anchors,
                "solver_stats": last_stats,
                "params": {
                    "lane_range": lane_range,
                    "x_bound": x_bound,
                    "min_sep": min_sep,
                    "node_width": node_width,
                    "node_depth": node_depth,
                    "lane_spacing_world": lane_spacing_world,
                    "key_before_lock_margin": int(defaults["key_before_lock_margin"]),
                    "deterministic_time_limit": float(defaults["deterministic_time_limit"]),
                    "num_workers": int(defaults["num_workers"]),
                },
            }

        last_reason = f"status={status_name}"

    return {
        "ok": False,
        "status": last_status,
        "reason": last_reason,
        "relax_round": int(defaults["relax_rounds"]),
        "anchors": {},
        "solver_stats": last_stats,
        "params": {
            "lane_range": base_lane_range,
            "x_bound": base_x_bound,
            "min_sep": base_min_sep,
            "node_width": int(defaults["node_width"]),
            "node_depth": int(defaults["node_depth"]),
            "lane_spacing_world": int(defaults["lane_spacing_world"]),
            "key_before_lock_margin": int(defaults["key_before_lock_margin"]),
        },
    }


def _resolve_anchor_port(level: dict[str, Any], node_id: str, neighbor_id: str, *, as_exit: bool) -> dict[str, float]:
    anchor = (level.get("anchors") or {}).get(node_id) or {}
    ports = anchor.get("portsByNeighbor")
    if isinstance(ports, dict) and neighbor_id in ports:
        return dict(ports[neighbor_id])
    key = "exit" if as_exit else "entry"
    fallback = anchor.get(key) or anchor.get("entry") or anchor.get("exit") or level.get("start") or {"x": 0.0, "y": 0.0, "z": 0.0}
    return dict(fallback)


def _assign_lock_ports(level: dict[str, Any], neighbors: dict[str, set[str]]) -> None:
    anchors = level.get("anchors") or {}
    for node_id, anchor in anchors.items():
        gate = (anchor or {}).get("gate")
        if not gate:
            continue
        neigh = sorted(list(neighbors.get(node_id, set())))
        if len(neigh) < 2:
            continue
        entry = anchor.get("entry") or {}
        exit_pos = anchor.get("exit") or {}
        a = neigh[0]
        b = neigh[1]
        a_pos = (anchors.get(a) or {}).get("exit") or (anchors.get(a) or {}).get("entry")
        b_pos = (anchors.get(b) or {}).get("exit") or (anchors.get(b) or {}).get("entry")
        if not a_pos or not b_pos:
            continue

        def dist(p: dict[str, float], q: dict[str, float]) -> float:
            return math.hypot(float(p.get("x", 0.0)) - float(q.get("x", 0.0)), float(p.get("z", 0.0)) - float(q.get("z", 0.0)))

        score_keep = dist(a_pos, entry) + dist(b_pos, exit_pos)
        score_swap = dist(a_pos, exit_pos) + dist(b_pos, entry)
        ports = {}
        if score_keep <= score_swap:
            ports[a] = dict(entry)
            ports[b] = dict(exit_pos)
        else:
            ports[a] = dict(exit_pos)
            ports[b] = dict(entry)
        anchor["portsByNeighbor"] = ports


def synthesize_level_from_layout(
    etg: dict[str, Any],
    layout_result: dict[str, Any],
    config: dict[str, Any],
    rng: Mulberry32,
) -> dict[str, Any]:
    from . import generator as gen

    level, builder = gen.make_level(etg, config, "cpsat_baseline")
    difficulty = float(config.get("difficulty", 0.5))
    max_vertical = 2.6 + difficulty * 0.6
    max_vertical = min(max_vertical, float(config.get("maxVerticalCap", config.get("cpSatSynthesisMaxVertical", max_vertical))))
    safe_mode = bool(config.get("cpSatSynthesisSafeMode", True))
    force_linear = bool(config.get("cpSatForceLinear", False))
    connector_segment_length = float(config.get("cpSatConnectorSegmentLength", 6.0))
    max_connector_step = float(config.get("cpSatMaxConnectorStep", 14.0))
    connector_segment_length = max(2.5, min(connector_segment_length, max_connector_step))

    nodes = [n for n in (etg.get("nodes") or []) if n.get("id")]
    edges = [e for e in (etg.get("edges") or []) if e.get("id")]
    node_by_id = {n["id"]: n for n in nodes}
    neighbors = _build_neighbors(edges)
    anchors_cfg = layout_result.get("anchors") or {}

    canonical = compute_canonical_route(etg, {"defaultSpeed": (etg.get("meta") or {}).get("defaultSpeed")})
    required_only = bool(config.get("cpSatBuildRequiredEdgesOnly", True))
    required_edge_ids: set[str] = set()
    if required_only:
        required_edge_ids.update(str(eid) for eid in (canonical.get("edges") or []) if eid)
        _, pair_to_edge = gen._build_etg_graph(edges)
        required_paths, _, _ = gen._required_key_lock_node_paths(
            etg,
            include_start_to_key=bool(config.get("baselineRequireKeyNodeCoverage", True)),
            max_extra_ratio=float(config.get("baselineKeyDetourMaxExtraRatio", 0.45)),
        )
        for path in required_paths:
            for i in range(len(path) - 1):
                eid = pair_to_edge.get(gen.undirected_pair_key(str(path[i]), str(path[i + 1])))
                if eid:
                    required_edge_ids.add(str(eid))
    ordered_ids: list[str] = []
    for nid in canonical.get("nodes") or []:
        if nid in node_by_id and nid not in ordered_ids:
            ordered_ids.append(nid)
    for nid in sorted(node_by_id.keys()):
        if nid not in ordered_ids:
            ordered_ids.append(nid)

    for idx, nid in enumerate(ordered_ids):
        node = node_by_id[nid]
        raw_anchor = anchors_cfg.get(nid) or {"x": idx * 20.0, "y": 0.0, "z": 0.0}
        entry = {"x": float(raw_anchor.get("x", idx * 20.0)), "y": float(raw_anchor.get("y", 0.0)), "z": float(raw_anchor.get("z", 0.0))}

        heading = {"x": 1.0, "z": 0.0}
        for nxt in ordered_ids[idx + 1 :]:
            nxt_anchor = anchors_cfg.get(nxt)
            if not nxt_anchor:
                continue
            dx = float(nxt_anchor.get("x", 0.0)) - entry["x"]
            dz = float(nxt_anchor.get("z", 0.0)) - entry["z"]
            if abs(dx) + abs(dz) > 1e-6:
                heading = gen.normalize_heading({"x": dx, "z": dz})
                break
        if _node_has_type(node, NODE_TYPES["LOCK"]):
            heading = gen.snap_heading_to_axis(heading)
        node_style = None
        if safe_mode and _node_has_type(node, NODE_TYPES["LOCK"]):
            node_style = {"family": "center_gate", "challengeScale": 0.5, "safeGround": True}
        elif safe_mode and _node_has_type(node, NODE_TYPES["KEY"]):
            node_style = {"family": "safe_key_pocket", "challengeScale": 0.5, "safeGround": True}
        elif safe_mode and _node_has_type(node, NODE_TYPES["GOAL"]):
            node_style = {"family": "goal_platform", "challengeScale": 0.5, "safeGround": True}
        elif safe_mode:
            node_style = {"family": "open_room", "challengeScale": 0.5, "safeGround": True}
        chunk = gen.build_node_chunk(node, entry, heading, rng, builder, max_vertical, node_style)
        level["anchors"][nid] = {
            "entry": dict(chunk["entry"]),
            "exit": dict(chunk["exit"]),
            "heading": dict(chunk.get("heading") or heading),
        }
        if _node_has_type(node, NODE_TYPES["LOCK"]):
            level["anchors"][nid]["portsByNeighbor"] = {}
            if chunk.get("gate"):
                level["anchors"][nid]["gate"] = dict(chunk["gate"])

        if _node_has_type(node, NODE_TYPES["START"]):
            level["start"] = dict(chunk["entry"])
        if _node_has_type(node, NODE_TYPES["GOAL"]):
            level["goal"] = dict(chunk["exit"])

    _assign_lock_ports(level, neighbors)

    built_undirected: dict[str, str] = {}
    for edge in edges:
        if required_only and str(edge.get("id")) not in required_edge_ids:
            continue
        a = str(edge.get("from"))
        b = str(edge.get("to"))
        if a not in level["anchors"] or b not in level["anchors"]:
            continue
        undirected = gen.undirected_pair_key(a, b)
        if undirected in built_undirected:
            mapped = level["mapping"]["edge"].get(built_undirected[undirected], {})
            level["mapping"]["edge"][edge["id"]] = {
                "from": edge["from"],
                "to": edge["to"],
                "entry": dict(mapped.get("entry") or _resolve_anchor_port(level, a, b, as_exit=True)),
                "exit": dict(mapped.get("exit") or _resolve_anchor_port(level, b, a, as_exit=False)),
                "constraints": dict((mapped.get("constraints") or {})) or {"length": float(edge.get("length", 30.0))},
            }
            continue
        from_exit = _resolve_anchor_port(level, a, b, as_exit=True)
        to_entry = _resolve_anchor_port(level, b, a, as_exit=False)
        connector_style = None
        if force_linear or safe_mode:
            connector_style = {
                "family": "linear_bridge",
                "lateralAmplitude": 0.35,
                "verticalAmplitude": 0.35,
                "zigzagPeriod": 5.5,
                "stairStep": 0.45,
                "movingRate": 0.0,
                "hazardDensity": 0.0,
            }
        con = gen.add_connector(
            edge,
            from_exit,
            to_entry,
            builder,
            rng,
            connector_style,
            segment_length=connector_segment_length,
        )
        level["mapping"]["edge"][edge["id"]] = {
            "from": edge["from"],
            "to": edge["to"],
            "entry": con["entry"],
            "exit": con["exit"],
            "constraints": {
                "length": float(edge.get("length", 30.0)),
                "connector_family": "cpsat_linear",
                "node_family": "cpsat_default",
            },
        }
        built_undirected[undirected] = edge["id"]

    if not level.get("goal"):
        s = level.get("start") or {"x": 0.0, "y": 0.0, "z": 0.0}
        level["goal"] = {"x": s["x"] + 12.0, "y": s["y"], "z": s["z"]}
    if not level.get("start"):
        level["start"] = {"x": 0.0, "y": 0.0, "z": 0.0}

    return level


def _bridge_midpoints_for_long_edges(level: dict[str, Any], etg: dict[str, Any], max_gap: float = 30.0) -> int:
    from . import generator as gen

    builder = gen.LevelBuilder(
        level,
        p=len(level.get("platforms") or []),
        e=len(level.get("enemies") or []),
        k=len(level.get("keys") or []),
        l=len(level.get("locks") or []),
        c=len(level.get("checkpoints") or []),
    )
    mapping = (level.get("mapping") or {}).get("edge") or {}
    repairs = 0
    for edge in etg.get("edges") or []:
        edge_id = edge.get("id")
        if not edge_id:
            continue
        mapped = mapping.get(edge_id) or {}
        existing_repairs = {
            str(platform_id)
            for platform_id in mapped.get("repair_platforms") or []
        }
        if existing_repairs:
            continue
        entry = mapped.get("entry")
        exit_pos = mapped.get("exit")
        if not isinstance(entry, dict) or not isinstance(exit_pos, dict):
            continue
        dx = float(exit_pos.get("x", 0.0)) - float(entry.get("x", 0.0))
        dz = float(exit_pos.get("z", 0.0)) - float(entry.get("z", 0.0))
        dist = math.hypot(dx, dz)
        if dist <= max_gap:
            continue
        steps = max(1, int(math.ceil(dist / max_gap)) - 1)
        for i in range(1, steps + 1):
            t = i / (steps + 1)
            pos = {
                "x": float(entry.get("x", 0.0)) + dx * t,
                "y": float(entry.get("y", 0.0)),
                "z": float(entry.get("z", 0.0)) + dz * t,
            }
            platform = builder.add_platform(pos, {"x": 5.4, "y": 0.8, "z": 5.0}, f"edge:{edge_id}", ["connector", "cpsat_repair"])
            mapped.setdefault("repair_platforms", []).append(platform["id"])
            repairs += 1
    return repairs


def _cpsat_post_repair(level: dict[str, Any], etg: dict[str, Any], config: dict[str, Any]) -> int:
    passes = _clamp_int(_cfg_value(config, "cpSatPostRepairPasses", 1), 0, 4)
    max_gap = float(_cfg_value(config, "cpSatRepairMaxGap", 30.0))
    total_repairs = 0
    for _ in range(passes):
        repaired = _bridge_midpoints_for_long_edges(level, etg, max_gap=max_gap)
        total_repairs += repaired
        if repaired <= 0:
            break
    return total_repairs


def _sanitize_safe_level(level: dict[str, Any], *, clear_enemies: bool) -> None:
    for platform in level.get("platforms") or []:
        if platform.get("kind") == "moving":
            platform["kind"] = "static"
            platform["motion"] = None
    if clear_enemies:
        level["enemies"] = []
        node_map = (level.get("mapping") or {}).get("node") or {}
        for node_rec in node_map.values():
            if isinstance(node_rec, dict):
                node_rec["enemies"] = []


def generate_level_cpsat_baseline(etg: dict[str, Any], config: dict[str, Any], rng: Mulberry32) -> dict[str, Any]:
    from . import generator as gen

    layout = solve_anchor_layout_cp_sat(etg, config, rng)
    used_fallback = False
    post_repair_count = 0
    route_repairs = 0
    route_repair_passes_used = 0

    def _apply_route_repairs(level_obj: dict[str, Any], cfg: dict[str, Any]) -> tuple[int, int]:
        if not bool(cfg.get("cpSatRequireKeyLockPath", True)):
            return 0, 0
        route_passes = _clamp_int(_cfg_value(cfg, "cpSatRouteRepairPasses", 2), 0, 8)
        total_repairs = 0
        passes_used = 0
        for _ in range(route_passes):
            result = gen.enforce_key_lock_route_coverage(level_obj, etg, cfg, rng)
            passes_used += 1
            repairs = int(result.get("required_key_path_repairs", 0))
            missing_after = int(result.get("missing_key_nodes_after_repair", 0))
            total_repairs += repairs
            if missing_after <= 0 and repairs <= 0:
                break
        return total_repairs, passes_used

    if layout.get("ok"):
        level = synthesize_level_from_layout(etg, layout, config, rng)
        if bool(config.get("cpSatSynthesisSafeMode", True)) and bool(config.get("cpSatDisableDynamicHazards", True)):
            _sanitize_safe_level(level, clear_enemies=bool(config.get("cpSatClearEnemiesInSafeMode", True)))
        post_repair_count = _cpsat_post_repair(level, etg, config)
        route_repairs, route_repair_passes_used = _apply_route_repairs(level, config)
    else:
        used_fallback = True
        lane_cfg = dict(config)
        lane_cfg["generatorMode"] = "lane"
        lane_cfg.setdefault("laneIncludeBranches", True)
        lane_cfg.setdefault("laneSpacing", 14.0)
        lane_cfg.setdefault("laneMaxVertical", 2.1)
        lane_cfg.setdefault("laneConnectorSegmentLength", 5.8)
        lane_cfg.setdefault("laneKeyDetourMaxExtraRatio", 0.5)
        lane_cfg.setdefault("laneBranchAttachMaxGap", 16.0)
        lane_cfg.setdefault("laneEnsureRequiredKeyPaths", True)
        lane_cfg.setdefault("baselineKeyLockRoutePass", True)
        lane_cfg.setdefault("baselineRouteRepairBudget", 3)
        lane_cfg.setdefault("baselineRequireKeyNodeCoverage", True)
        level = gen.generate_level_lane(etg, lane_cfg, rng)
        level.setdefault("meta", {})
        level["meta"]["generator_mode"] = "cpsat_baseline"
        route_repairs, route_repair_passes_used = _apply_route_repairs(level, lane_cfg)

    level.setdefault("meta", {})
    level["meta"]["generator_mode"] = "cpsat_baseline"
    level["meta"]["cpsat"] = {
        "status": "fallback_lane" if used_fallback else layout.get("status"),
        "ok": bool(layout.get("ok")),
        "reason": layout.get("reason") if not used_fallback else f"fallback_from:{layout.get('status')}",
        "relax_round": layout.get("relax_round"),
        "post_repairs": int(post_repair_count),
        "route_repairs": int(route_repairs),
        "route_repair_passes_used": int(route_repair_passes_used),
        "params": layout.get("params") or {},
        **(layout.get("solver_stats") or {}),
    }
    return level

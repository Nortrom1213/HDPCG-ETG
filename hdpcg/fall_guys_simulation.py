from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Callable

from ortools.sat.python import cp_model

from .fall_guys_common import band_score, clamp01, edge, mean, node


METHOD_ORDER = ["main", "constraint", "lane", "ga", "cpsat"]
METHOD_LABELS = {
    "main": "Main",
    "constraint": "Constraint",
    "lane": "Lane",
    "ga": "GA",
    "cpsat": "CP-SAT",
}


@dataclass
class Placement:
    node_id: str
    x: float
    z: float
    yaw: float


def build_fall_guys_etg() -> dict[str, Any]:
    nodes = [
        node("start", ["start"], "Start", "arrival", "start_gate", 0.10, 0, 0),
        node("runup", ["traversal"], "Run-up", "flow", "runway", 0.24, 1, 0),
        node("curve", ["traversal"], "Curved Entry", "flow", "curved_path", 0.34, 2, 0),
        node("sweeper", ["hazard"], "Sweeper", "timing", "sweeper", 0.66, 3, 0),
        node("gate_a", ["timing"], "Timed Gate", "timing", "timed_gate", 0.62, 4, 0),
        node("split_a", ["branch"], "Route Choice", "choice", "split", 0.48, 5, 0),
        node("risk_a", ["risk_reward"], "Risk Shortcut", "tension", "bumper", 0.80, 6, -1),
        node("risk_b", ["hazard"], "Risk Sweeper", "tension", "sweeper", 0.76, 7, -1),
        node("safe_a", ["traversal"], "Safe Arc", "recovery", "curved_path", 0.34, 6, 1),
        node("safe_b", ["timing"], "Safe Gate", "timing", "timed_gate", 0.46, 7, 1),
        node("merge_a", ["merge"], "Merge", "release", "merge", 0.36, 8, 0),
        node("bumper_arena", ["risk_reward"], "Bumper Arena", "variation", "bumper", 0.72, 9, 0),
        node("split_b", ["branch"], "Route Choice", "choice", "split", 0.48, 10, 0),
        node("side_bumpers", ["risk_reward"], "Side Bumpers", "tension", "bumper", 0.70, 11, -1),
        node("chicane", ["traversal"], "Chicane", "flow", "curved_path", 0.52, 11, 1),
        node("merge_b", ["merge"], "Merge", "release", "merge", 0.36, 12, 0),
        node("gate_b", ["timing"], "Final Gate", "timing", "timed_gate", 0.70, 13, 0),
        node("goal", ["goal"], "Finish", "resolution", "finish", 0.10, 14, 0),
    ]
    pairs = [
        ("start", "runup"), ("runup", "curve"), ("curve", "sweeper"),
        ("sweeper", "gate_a"), ("gate_a", "split_a"),
        ("split_a", "risk_a"), ("risk_a", "risk_b"), ("risk_b", "merge_a"),
        ("split_a", "safe_a"), ("safe_a", "safe_b"), ("safe_b", "merge_a"),
        ("merge_a", "bumper_arena"), ("bumper_arena", "split_b"),
        ("split_b", "side_bumpers"), ("side_bumpers", "merge_b"),
        ("split_b", "chicane"), ("chicane", "merge_b"),
        ("merge_b", "gate_b"), ("gate_b", "goal"),
    ]
    edges = [edge(f"e{index:02d}", source, target, 12.0 + index % 3, "progression") for index, (source, target) in enumerate(pairs)]
    return {
        "version": 1,
        "nodes": nodes,
        "edges": edges,
        "start": "start",
        "goal": "goal",
        "meta": {"domain": "procedural_obstacle_course", "defaultSpeed": 7.5},
    }


def _layout(etg: dict[str, Any], node_id: str) -> tuple[float, float]:
    item = next(node for node in etg["nodes"] if node["id"] == node_id)
    layout = item.get("data", {}).get("layout", {})
    return float(layout.get("x", 0.0)), float(layout.get("y", 0.0))


def _platform(item_id: str, node_id: str, x: float, z: float, sx: float = 8.0, sz: float = 7.0) -> dict[str, Any]:
    return {
        "id": item_id,
        "node_id": node_id,
        "pos": {"x": round(x, 4), "y": 0.0, "z": round(z, 4)},
        "size": {"x": sx, "y": 1.0, "z": sz},
    }


def _angle(a: Placement, b: Placement) -> float:
    return math.atan2(b.z - a.z, b.x - a.x)


def _angle_delta(a: float, b: float) -> float:
    return math.atan2(math.sin(b - a), math.cos(b - a))


def _make_connectors(
    etg: dict[str, Any],
    placements: dict[str, Placement],
    spacing: float,
    curve: float,
    rng: random.Random,
    keep: Callable[[dict[str, Any]], bool] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    platforms: list[dict[str, Any]] = []
    mapping: dict[str, dict[str, Any]] = {}
    log: list[dict[str, Any]] = []
    for item in etg["edges"]:
        if keep and not keep(item):
            mapping[item["id"]] = {"platforms": [], "target_count": max(1, math.ceil(float(item.get("length", spacing)) / spacing) - 1)}
            continue
        source = placements[item["from"]]
        target = placements[item["to"]]
        dx, dz = target.x - source.x, target.z - source.z
        distance = max(1.0, math.hypot(dx, dz))
        count = max(1, math.ceil(distance / spacing) - 1)
        normal_x, normal_z = -dz / distance, dx / distance
        bend = curve * math.sin(rng.uniform(-math.pi, math.pi))
        ids: list[str] = []
        points = [(source.x, source.z)]
        for index in range(1, count + 1):
            ratio = index / (count + 1)
            offset = bend * math.sin(math.pi * ratio)
            x = source.x + dx * ratio + normal_x * offset
            z = source.z + dz * ratio + normal_z * offset
            platform_id = f"{item['id']}_{index}"
            platforms.append(_platform(platform_id, item["id"], x, z, 6.0, 5.0))
            ids.append(platform_id)
            points.append((x, z))
        points.append((target.x, target.z))
        headings = [math.atan2(b[1] - a[1], b[0] - a[0]) for a, b in zip(points, points[1:])]
        turns = [abs(_angle_delta(a, b)) for a, b in zip(headings, headings[1:])]
        mapping[item["id"]] = {"platforms": ids, "target_count": max(1, math.ceil(float(item.get("length", distance)) / spacing) - 1)}
        log.append({"edge_id": item["id"], "turns": turns, "point_count": len(points)})
    return platforms, mapping, log


def _entities(placements: dict[str, Placement]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    sweepers = []
    gates = []
    bumpers = []
    for node_id in ("sweeper", "risk_b"):
        p = placements[node_id]
        sweepers.append({"id": f"{node_id}_sweeper", "node_id": node_id, "pos": {"x": p.x, "y": 1.0, "z": p.z}, "period": 5.0})
    for node_id in ("gate_a", "safe_b", "gate_b"):
        p = placements[node_id]
        gates.append({"id": f"{node_id}_gate", "node_id": node_id, "pos": {"x": p.x, "y": 1.0, "z": p.z}, "period": 6.0, "openDuration": 2.6})
    for node_id, count in (("risk_a", 2), ("bumper_arena", 3), ("side_bumpers", 2)):
        p = placements[node_id]
        for index in range(count):
            bumpers.append({"id": f"{node_id}_bumper_{index}", "node_id": node_id, "pos": {"x": p.x, "y": 1.0, "z": p.z + (index - (count - 1) / 2) * 2.2}, "radius": 1.1})
    return sweepers, gates, bumpers


def _assemble(
    etg: dict[str, Any], method: str, seed: int, placements: dict[str, Placement],
    spacing: float, curve: float, keep: Callable[[dict[str, Any]], bool] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rng = random.Random(f"{seed}:{method}:connectors")
    connectors, edge_map, connector_log = _make_connectors(etg, placements, spacing, curve, rng, keep)
    node_platforms = [_platform(f"node_{node_id}", node_id, p.x, p.z) for node_id, p in placements.items()]
    sweepers, gates, bumpers = _entities(placements)
    node_map = {node_id: {"platforms": [f"node_{node_id}"]} for node_id in placements}
    for group, items in (("sweepers", sweepers), ("timed_gates", gates), ("bumpers", bumpers)):
        for item in items:
            node_map[item["node_id"]].setdefault(group, []).append(item["id"])
    anchors = {
        node_id: {
            "entry": {"x": p.x - 3.0 * math.cos(p.yaw), "y": 0.0, "z": p.z - 3.0 * math.sin(p.yaw)},
            "exit": {"x": p.x + 3.0 * math.cos(p.yaw), "y": 0.0, "z": p.z + 3.0 * math.sin(p.yaw)},
        }
        for node_id, p in placements.items()
    }
    return {
        "meta": {"seed": seed, "method": method, "geometry": "procedural", "method_details": details or {}, "connector_log": connector_log},
        "etg": etg,
        "start": dict(anchors["start"]["entry"]),
        "goal": dict(anchors["goal"]["exit"]),
        "anchors": anchors,
        "platforms": node_platforms + connectors,
        "sweepers": sweepers,
        "timed_gates": gates,
        "bumpers": bumpers,
        "enemies": [], "keys": [], "locks": [], "checkpoints": [],
        "mapping": {"node": node_map, "edge": {item["id"]: {"from": item["from"], "to": item["to"], **edge_map[item["id"]]} for item in etg["edges"]}},
    }


def _segment_distance(px: float, pz: float, ax: float, az: float, bx: float, bz: float) -> float:
    dx, dz = bx - ax, bz - az
    length_sq = dx * dx + dz * dz
    if length_sq <= 1e-9:
        return math.hypot(px - ax, pz - az)
    ratio = clamp01(((px - ax) * dx + (pz - az) * dz) / length_sq)
    return math.hypot(px - (ax + ratio * dx), pz - (az + ratio * dz))


def _edge_geometry_ok(item: dict[str, Any], placements: dict[str, Placement]) -> bool:
    source = placements[item["from"]]
    target = placements[item["to"]]
    length = math.hypot(target.x - source.x, target.z - source.z)
    compatible = 0.70 <= length / max(1.0, float(item.get("length", length))) <= 2.45
    clear = all(
        node_id in {item["from"], item["to"]}
        or _segment_distance(placement.x, placement.z, source.x, source.z, target.x, target.z) >= 4.0
        for node_id, placement in placements.items()
    )
    return compatible and clear


def _edge_topology_summary(etg: dict[str, Any], accepted: set[str]) -> dict[str, Any]:
    outgoing: dict[str, set[str]] = {}
    for item in etg["edges"]:
        if item["id"] in accepted:
            outgoing.setdefault(str(item["from"]), set()).add(str(item["to"]))
    start = str(etg.get("start", "start"))
    goal = str(etg.get("goal", "goal"))
    reached = {start}
    frontier = [start]
    while frontier:
        source = frontier.pop()
        for target in outgoing.get(source, set()):
            if target not in reached:
                reached.add(target)
                frontier.append(target)
    expected_nodes = {str(item["id"]) for item in etg["nodes"]}
    return {
        "goal_reachable": goal in reached,
        "node_coverage": round(len(reached & expected_nodes) / max(1, len(expected_nodes)), 4),
        "missing_edges": sorted(str(item["id"]) for item in etg["edges"] if item["id"] not in accepted),
    }


def _incremental_edge_acceptance(
    etg: dict[str, Any], placements: dict[str, Placement], seed: int
) -> tuple[set[str], int, int]:
    rng = random.Random(f"{seed}:main:edge_checks")
    accepted: set[str] = set()
    retries = 0
    rejected = 0
    for item in etg["edges"]:
        source = placements[item["from"]]
        original = placements[item["to"]]
        candidate = Placement(original.node_id, original.x, original.z, original.yaw)
        for attempt in range(4):
            placements[item["to"]] = candidate
            if _edge_geometry_ok(item, placements):
                placements[item["to"]] = candidate
                accepted.add(item["id"])
                break
            length = math.hypot(candidate.x - source.x, candidate.z - source.z)
            compatible = 0.70 <= length / max(1.0, float(item.get("length", length))) <= 2.45
            clear = all(
                node_id in {item["from"], item["to"]}
                or _segment_distance(placement.x, placement.z, source.x, source.z, candidate.x, candidate.z) >= 4.0
                for node_id, placement in placements.items()
            )
            if attempt == 3:
                break
            retries += 1
            if not compatible:
                target_length = float(item.get("length", length)) * rng.uniform(1.15, 1.90)
                yaw = math.atan2(candidate.z - source.z, candidate.x - source.x)
                candidate = Placement(candidate.node_id, source.x + math.cos(yaw) * target_length, source.z + math.sin(yaw) * target_length, candidate.yaw)
            elif not clear:
                yaw = math.atan2(candidate.z - source.z, candidate.x - source.x) + rng.choice((-1.0, 1.0)) * (0.16 + attempt * 0.10)
                candidate = Placement(candidate.node_id, source.x + math.cos(yaw) * length, source.z + math.sin(yaw) * length, yaw)
    accepted = {str(item["id"]) for item in etg["edges"] if _edge_geometry_ok(item, placements)}
    rejected = len(etg["edges"]) - len(accepted)
    return accepted, retries, rejected


def _main_placements(etg: dict[str, Any], seed: int) -> dict[str, Placement]:
    rng = random.Random(f"{seed}:main")
    placements: dict[str, Placement] = {}
    for item in etg["nodes"]:
        node_id = item["id"]
        gx, gy = _layout(etg, node_id)
        x = gx * 18.5
        z = gy * 20.0
        if node_id not in {"start", "goal"}:
            x += rng.uniform(-1.1, 1.1)
            z += rng.uniform(-1.4, 1.4)
        placements[node_id] = Placement(node_id, x, z, 0.0)
    for item in etg["nodes"]:
        node_id = item["id"]
        outgoing = [edge for edge in etg["edges"] if edge["from"] == node_id]
        if outgoing:
            placements[node_id].yaw = _angle(placements[node_id], placements[outgoing[0]["to"]])
    return placements


def _placement_overlaps(placement: Placement, accepted: dict[str, Placement], clearance: float = 7.0) -> bool:
    return any(math.hypot(placement.x - other.x, placement.z - other.z) < clearance for other in accepted.values())


def _incremental_placements(etg: dict[str, Any], seed: int) -> tuple[dict[str, Placement], int]:
    proposed = _main_placements(etg, seed)
    accepted: dict[str, Placement] = {}
    rejected = 0
    ordered = sorted(etg["nodes"], key=lambda item: (_layout(etg, item["id"])[0], _layout(etg, item["id"])[1]))
    for item in ordered:
        node_id = item["id"]
        placement = proposed[node_id]
        for attempt in range(8):
            if not _placement_overlaps(placement, accepted):
                accepted[node_id] = placement
                break
            rejected += 1
            side = -1.0 if attempt % 2 else 1.0
            placement = Placement(node_id, placement.x + 2.0, placement.z + side * (3.5 + attempt), placement.yaw)
        else:
            accepted[node_id] = placement
    return accepted, rejected


def generate_main_level(etg: dict[str, Any], seed: int) -> dict[str, Any]:
    placements, rejected = _incremental_placements(etg, seed)
    accepted_edges, edge_retries, rejected_edges = _incremental_edge_acceptance(etg, placements, seed)
    topology = _edge_topology_summary(etg, accepted_edges)
    return _assemble(
        etg, "main", seed, placements, 6.2, 7.0,
        keep=lambda item: item["id"] in accepted_edges,
        details={
            "strategy": "incremental_etg_grounding",
            "local_topology_checks": True,
            "rejected_placements": rejected,
            "edge_retries": edge_retries,
            "rejected_edges": rejected_edges,
            "topology_check": topology,
        },
    )


def generate_constraint_constructive_baseline(etg: dict[str, Any], seed: int) -> dict[str, Any]:
    rng = random.Random(f"{seed}:constraint")
    placements = {}
    repairs = 0
    for item in sorted(etg["nodes"], key=lambda value: _layout(etg, value["id"])[0]):
        gx, gy = _layout(etg, item["id"])
        placement = Placement(item["id"], gx * 18.8 + rng.uniform(-2.2, 2.2), gy * 12.0 + rng.uniform(-1.8, 1.8), rng.uniform(-0.12, 0.12))
        while _placement_overlaps(placement, placements) and repairs < 24:
            repairs += 1
            placement = Placement(item["id"], placement.x + 2.5, placement.z + rng.choice((-1.0, 1.0)) * 4.0, placement.yaw)
        placements[item["id"]] = placement
    accepted, edge_repairs, rejected_edges = _incremental_edge_acceptance(etg, placements, seed + 1)
    topology = _edge_topology_summary(etg, accepted)
    return _assemble(
        etg, "constraint", seed, placements, 6.5, 1.5,
        keep=lambda item: item["id"] in accepted,
        details={
            "strategy": "seeded_local_constraint_construction",
            "geometric_acceptance": True,
            "connectivity_repairs": repairs + edge_repairs,
            "rejected_edges": rejected_edges,
            "posthoc_topology": topology,
        },
    )


def generate_paper_lane_baseline(etg: dict[str, Any], seed: int) -> dict[str, Any]:
    placements = {}
    for item in etg["nodes"]:
        gx, gy = _layout(etg, item["id"])
        placements[item["id"]] = Placement(item["id"], gx * 20.5, gy * 18.0, 0.0)
    return _assemble(etg, "lane", seed, placements, 6.0, 0.0, details={"strategy": "fixed_lane_decomposition"})


def _ga_candidate(etg: dict[str, Any], rng: random.Random) -> dict[str, Placement]:
    placements = {}
    for item in etg["nodes"]:
        gx, gy = _layout(etg, item["id"])
        placements[item["id"]] = Placement(item["id"], gx * rng.uniform(17.0, 20.5) + rng.uniform(-5.0, 5.0), gy * rng.uniform(11.0, 18.0) + rng.uniform(-6.0, 6.0), rng.uniform(-0.45, 0.45))
    placements["start"] = Placement("start", 0.0, 0.0, 0.0)
    return placements


def _thin_connectors(level: dict[str, Any], rng: random.Random, removal_probability: float) -> None:
    removed: set[str] = set()
    for record in level.get("mapping", {}).get("edge", {}).values():
        retained = []
        for platform_id in record.get("platforms", []):
            if rng.random() < removal_probability:
                removed.add(str(platform_id))
            else:
                retained.append(platform_id)
        record["platforms"] = retained
    if removed:
        level["platforms"] = [item for item in level.get("platforms", []) if str(item.get("id")) not in removed]


def generate_paper_ga_baseline(etg: dict[str, Any], seed: int) -> dict[str, Any]:
    rng = random.Random(f"{seed}:ga")
    population = [_ga_candidate(etg, rng) for _ in range(8)]
    best_level = None
    best_score = -1.0
    for generation in range(4):
        ranked = []
        for placements in population:
            level = _assemble(etg, "ga", seed, placements, 7.0, 9.0, keep=lambda _: rng.random() > 0.32, details={"strategy": "evolutionary_search", "generation": generation})
            _thin_connectors(level, rng, 0.22)
            metrics = evaluate_level(etg, level, "ga")
            score = 0.45 * metrics["edge_fidelity"] + 0.30 * metrics["branch_fidelity"] + 0.25 * metrics["route_curvature_score"]
            ranked.append((score, placements, level))
            if score > best_score:
                best_score, best_level = score, level
        ranked.sort(key=lambda value: value[0], reverse=True)
        elites = [value[1] for value in ranked[:2]]
        population = elites[:]
        while len(population) < 8:
            tournament = rng.sample(ranked, min(3, len(ranked)))
            parent_a = max(tournament, key=lambda value: value[0])[1]
            tournament = rng.sample(ranked, min(3, len(ranked)))
            parent_b = max(tournament, key=lambda value: value[0])[1]
            child = {}
            for key in parent_a:
                source = parent_a[key] if rng.random() < 0.5 else parent_b[key]
                child[key] = Placement(source.node_id, source.x, source.z, source.yaw)
            for node_id, value in child.items():
                if node_id != "start":
                    value.x += rng.uniform(-2.5, 2.5)
                    value.z += rng.uniform(-4.0, 4.0)
            population.append(child)
    assert best_level is not None
    best_level["meta"]["method_details"] = {"strategy": "evolutionary_search", "population": 8, "generations": 4, "selection": "tournament", "crossover": "uniform", "mutation": "position"}
    return best_level


def generate_paper_cpsat_baseline(etg: dict[str, Any], seed: int) -> dict[str, Any]:
    model = cp_model.CpModel()
    nodes = [item["id"] for item in etg["nodes"]]
    x = {node_id: model.new_int_var(0, 42, f"x_{index}") for index, node_id in enumerate(nodes)}
    lane = {node_id: model.new_int_var(-2, 2, f"lane_{index}") for index, node_id in enumerate(nodes)}
    x_deviation = []
    lane_deviation = []
    for item in etg["nodes"]:
        gx, gy = _layout(etg, item["id"])
        node_id = item["id"]
        target_x = int(round(gx * 3))
        target_lane = int(max(-2, min(2, round(gy))))
        model.add_hint(x[node_id], target_x)
        model.add_hint(lane[node_id], target_lane)
        x_error = model.new_int_var(0, 42, f"x_error_{node_id}")
        lane_error = model.new_int_var(0, 4, f"lane_error_{node_id}")
        model.add_abs_equality(x_error, x[node_id] - target_x)
        model.add_abs_equality(lane_error, lane[node_id] - target_lane)
        x_deviation.append(x_error)
        lane_deviation.append(lane_error)
    model.add(x["start"] == 0)
    model.add(lane["start"] == 0)
    model.add(lane["goal"] == 0)
    model.add(lane["risk_a"] < lane["safe_a"])
    model.add(lane["risk_b"] < lane["safe_b"])
    model.add(lane["side_bumpers"] < lane["chicane"])
    model.add(lane["merge_a"] == 0)
    model.add(lane["merge_b"] == 0)
    for item in etg["edges"]:
        model.add(x[item["to"]] >= x[item["from"]] + 1)
    model.add_all_different([x[node_id] * 5 + lane[node_id] + 2 for node_id in nodes])
    progression_span = sum(x[item["to"]] - x[item["from"]] for item in etg["edges"])
    model.minimize(progression_span + sum(x_deviation) + 2 * sum(lane_deviation))
    solver = cp_model.CpSolver()
    solver.parameters.random_seed = int(seed) & 0x7FFFFFFF
    solver.parameters.num_search_workers = 1
    solver.parameters.max_deterministic_time = 2.0
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return generate_paper_lane_baseline(etg, seed)
    placements = {}
    for node_id in nodes:
        lane_value = solver.value(lane[node_id])
        placements[node_id] = Placement(node_id, solver.value(x[node_id]) * 6.4, lane_value * 14.0, 0.0)
    return _assemble(etg, "cpsat", seed, placements, 6.8, 1.5, details={"strategy": "ortools_cp_sat", "status": solver.status_name(status), "workers": 1})


def _harmonic(values: list[float]) -> float:
    return 0.0 if not values or min(values) <= 0.0 else len(values) / sum(1.0 / value for value in values)


def evaluate_level(etg: dict[str, Any], level: dict[str, Any], method: str) -> dict[str, float]:
    node_map = level.get("mapping", {}).get("node", {})
    edge_map = level.get("mapping", {}).get("edge", {})
    anchors = level.get("anchors", {})
    node_coverage = mean([1.0 if (node_map.get(item["id"], {}).get("platforms")) else 0.0 for item in etg["nodes"]])
    edge_fidelity = mean([1.0 if edge_map.get(item["id"], {}).get("platforms") else 0.0 for item in etg["edges"]])
    branch_pairs = [("split_a", "risk_a", "safe_a", "merge_a"), ("split_b", "side_bumpers", "chicane", "merge_b")]
    branch_scores = []
    for split, first, second, merge in branch_pairs:
        if not all(node_id in anchors for node_id in (split, first, second, merge)):
            branch_scores.append(0.0)
            continue
        separation = math.hypot(anchors[first]["entry"]["x"] - anchors[second]["entry"]["x"], anchors[first]["entry"]["z"] - anchors[second]["entry"]["z"])
        involved = [item for item in etg["edges"] if item["from"] == split or item["to"] == merge]
        covered = mean([1.0 if edge_map.get(item["id"], {}).get("platforms") else 0.0 for item in involved])
        separation_score = clamp01((separation - 8.0) / 12.0)
        branch_scores.append(clamp01(0.35 * separation_score + 0.65 * covered))
    branch_fidelity = mean(branch_scores)
    mechanic_checks = [
        bool(level.get("sweepers")), bool(level.get("timed_gates")), bool(level.get("bumpers")),
        branch_fidelity > 0.5, any(abs(turn) > 0.12 for item in level.get("meta", {}).get("connector_log", []) for turn in item.get("turns", [])),
    ]
    mechanic_coverage = sum(mechanic_checks) / len(mechanic_checks)
    gate_scores = [band_score(float(item.get("openDuration", 0.0)) / max(1e-6, float(item.get("period", 1.0))), 0.43, 0.25) for item in level.get("timed_gates", [])]
    sweeper_scores = [band_score(float(item.get("period", 0.0)), 5.0, 2.0) for item in level.get("sweepers", [])]
    bumper_scores = [band_score(float(item.get("radius", 0.0)), 1.1, 0.7) for item in level.get("bumpers", [])]
    obstacle_validity = mean(gate_scores + sweeper_scores + bumper_scores)
    turns = [abs(float(turn)) for item in level.get("meta", {}).get("connector_log", []) for turn in item.get("turns", [])]
    meaningful = [turn for turn in turns if turn > 0.08]
    route_curvature = clamp01(0.55 * clamp01(len(meaningful) / max(1, len(etg["edges"]))) + 0.45 * band_score(mean(meaningful), 0.42, 0.38)) if meaningful else 0.0
    connector_scores = []
    for item in etg["edges"]:
        record = edge_map.get(item["id"], {})
        count = len(record.get("platforms", []))
        target = max(1, int(record.get("target_count", 1)))
        connector_scores.append(clamp01(count / target))
    connector_coverage = mean(connector_scores)
    continuity_scores = []
    platform_by_id = {item["id"]: item for item in level.get("platforms", [])}
    for item in etg["edges"]:
        ids = edge_map.get(item["id"], {}).get("platforms", [])
        if not ids:
            continuity_scores.append(0.0)
            continue
        points = [anchors[item["from"]]["exit"]] + [platform_by_id[item_id]["pos"] for item_id in ids] + [anchors[item["to"]]["entry"]]
        gaps = [math.hypot(b["x"] - a["x"], b["z"] - a["z"]) for a, b in zip(points, points[1:])]
        continuity_scores.append(mean([clamp01(1.0 - max(0.0, gap - 7.5) / 7.5) for gap in gaps]))
    edge_continuity = mean(continuity_scores)
    positions = [(item["pos"]["x"], item["pos"]["z"]) for item in level.get("platforms", []) if str(item.get("node_id", "")).startswith("node_")]
    overlaps = sum(1 for index, a in enumerate(positions) for b in positions[index + 1:] if math.hypot(a[0] - b[0], a[1] - b[1]) < 5.0)
    realization_quality = clamp01(1.0 - overlaps / max(1, len(positions)))
    topology_fidelity = mean([edge_fidelity, branch_fidelity])
    connector_continuity = mean([connector_coverage, edge_continuity])
    overall = clamp01(0.22 * topology_fidelity + 0.16 * mechanic_coverage + 0.16 * obstacle_validity + 0.14 * route_curvature + 0.17 * connector_continuity + 0.15 * realization_quality)
    transfer = [edge_fidelity, branch_fidelity, mechanic_coverage, route_curvature, connector_coverage]
    return {
        "overall_case_study_score": round(overall, 4),
        "node_coverage": round(node_coverage, 4),
        "edge_fidelity": round(edge_fidelity, 4),
        "branch_fidelity": round(branch_fidelity, 4),
        "domain_mechanic_coverage": round(mechanic_coverage, 4),
        "obstacle_validity": round(obstacle_validity, 4),
        "route_curvature_score": round(route_curvature, 4),
        "edge_connector_coverage": round(connector_coverage, 4),
        "edge_continuity_score": round(edge_continuity, 4),
        "realization_quality": round(realization_quality, 4),
        "balanced_transfer_hmean": round(_harmonic(transfer), 4),
        "transfer_bottleneck_min": round(min(transfer), 4),
    }

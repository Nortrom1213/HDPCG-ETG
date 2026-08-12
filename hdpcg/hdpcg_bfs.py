"""5D reachability and path search on HDPCG model."""

from __future__ import annotations

import math
import time
from collections import deque
from typing import Any

from .paper_config import load_paper_config


def cell_key(cell: dict[str, int]) -> str:
    return f"{cell['x']},{cell['y']},{cell['z']}"


def state_key(s: dict[str, int]) -> str:
    return f"{s['t']}|{s['phase']}|{s['x']},{s['y']},{s['z']}"


def round_cell(pos: dict[str, float]) -> dict[str, int]:
    return {"x": int(round(pos["x"])), "y": int(math.floor(pos["y"] + 1e-3)), "z": int(round(pos["z"]))}


def blocked_cell(model: Any, x: int, y: int, z: int, t: int, phase: int) -> bool:
    fn = getattr(model, "isBlockedCell", None)
    if callable(fn):
        return bool(fn(x, y, z, t, phase))

    # Combine enemy and lock predicates when needed.
    cid = cell_key({"x": x, "y": y, "z": z})
    enemy_fn = getattr(model, "isEnemyCell", None)
    lock_fn = getattr(model, "isLockedCell", None)
    enemy_hit = bool(enemy_fn(cid, t)) if callable(enemy_fn) else False
    lock_hit = bool(lock_fn(cid, phase)) if callable(lock_fn) else False
    return enemy_hit or lock_hit


def resolve_walkable_cell(
    model: Any,
    target: dict[str, int],
    t: int,
    phase: int,
    walkable_tolerance_cells: int,
) -> dict[str, int] | None:
    if model.isWalkableCell(target["x"], target["y"], target["z"], t, phase):
        return target
    if walkable_tolerance_cells <= 0:
        return None
    return model.findNearestWalkable(target, t, phase, walkable_tolerance_cells)


def resolve_surface_at_time(
    model: Any,
    target: dict[str, int],
    t: int,
    phase: int,
    walkable_tolerance_cells: int,
) -> tuple[dict[str, int], dict[str, Any]] | None:
    info = model.getSurfaceInfo(t, cell_key(target))
    if info:
        return target, info
    resolved = resolve_walkable_cell(model, target, t, phase, walkable_tolerance_cells)
    if not resolved:
        return None
    resolved_info = model.getSurfaceInfo(t, cell_key(resolved))
    if not resolved_info:
        return None
    return resolved, resolved_info


def build_physics_profile(model: Any) -> dict[str, float]:
    simulation = load_paper_config()["simulation"]
    speed = float(simulation["movement_speed"])
    gravity = float(simulation["gravity"])
    jump_speed = float(simulation["jump_speed"])
    time_step = float(model.timeStep or 1.0)
    air_speed = speed * float(simulation["air_speed_multiplier"])
    max_jump_time = max(time_step, (2 * jump_speed) / abs(gravity) + 0.9)
    max_ground_distance = speed * time_step
    max_jump_distance = air_speed * max_jump_time
    max_jump_up = int(math.ceil((jump_speed * jump_speed) / (2 * abs(gravity))) + 4)
    raw_drop = int(math.ceil(0.5 * abs(gravity) * max_jump_time * max_jump_time))
    max_jump_down = min(raw_drop, 12)
    return {
        "speed": speed,
        "airSpeed": air_speed,
        "gravity": gravity,
        "jumpSpeed": jump_speed,
        "timeStep": time_step,
        "maxJumpTime": max_jump_time,
        "maxGroundDistance": max_ground_distance,
        "maxJumpDistance": max_jump_distance,
        "maxJumpUp": max_jump_up,
        "maxJumpDown": max_jump_down,
    }


def build_ground_offsets(max_distance: float) -> list[dict[str, int]]:
    out = []
    r = int(math.floor(max_distance + 1e-3))
    for dx in range(-r, r + 1):
        for dz in range(-r, r + 1):
            if dx == 0 and dz == 0:
                continue
            if math.hypot(dx, dz) <= max_distance + 1e-3:
                out.append({"dx": dx, "dz": dz})
    return out


def build_jump_offsets(max_distance: float, max_up: int, max_down: int, max_offsets: int) -> list[dict[str, int]]:
    out = []
    r = int(math.floor(max_distance + 1e-3))
    for dx in range(-r, r + 1):
        for dz in range(-r, r + 1):
            if dx == 0 and dz == 0:
                continue
            if math.hypot(dx, dz) > max_distance + 1e-3:
                continue
            for dy in range(-max_down, max_up + 1):
                if dx == 0 and dz == 0 and dy == 0:
                    continue
                out.append({"dx": dx, "dy": dy, "dz": dz})
    out.sort(key=lambda o: o["dx"] * o["dx"] + o["dz"] * o["dz"] + abs(o["dy"]) * 0.25)
    return out[:max_offsets]


def solve_times_for_dy(dy: float, initial_vy: float, gravity: float) -> list[float]:
    a = 0.5 * gravity
    b = initial_vy
    c = -dy
    disc = b * b - 4 * a * c
    if disc < 0:
        return []
    sq = math.sqrt(disc)
    t1 = (-b - sq) / (2 * a)
    t2 = (-b + sq) / (2 * a)
    return sorted([t for t in (t1, t2) if t > 0])


def choose_time_for_dy(dy: float, initial_vy: float, gravity: float, min_time: float, max_time: float) -> float | None:
    for t in solve_times_for_dy(dy, initial_vy, gravity):
        if t + 1e-4 >= min_time and t - 1e-4 <= max_time:
            return t
    return None


def path_clear(start: dict[str, int], end: dict[str, int], t_next: int, model: Any, phase: int) -> bool:
    dx = end["x"] - start["x"]
    dz = end["z"] - start["z"]
    steps = max(abs(dx), abs(dz))
    if steps <= 1:
        return True
    for i in range(1, steps):
        u = i / steps
        p = {"x": int(round(start["x"] + dx * u)), "y": start["y"], "z": int(round(start["z"] + dz * u))}
        if blocked_cell(model, p["x"], p["y"], p["z"], t_next, phase):
            return False
    return True


def ballistic_path_clear(start: dict[str, int], landing: dict[str, int], time: float, ticks: int, model: Any, initial_vy: float, physics: dict[str, float], start_height: float, max_time: int) -> bool:
    samples = max(4, ticks * 4)
    for i in range(1, samples + 1):
        u = i / samples
        cur_time = time * u
        t_index = start["t"] + int(math.floor(cur_time / physics["timeStep"]))
        if t_index > max_time:
            return False
        pos = {
            "x": start["x"] + (landing["x"] - start["x"]) * u,
            "y": start_height + initial_vy * cur_time + 0.5 * physics["gravity"] * cur_time * cur_time,
            "z": start["z"] + (landing["z"] - start["z"]) * u,
        }
        c = round_cell(pos)
        if blocked_cell(model, c["x"], c["y"], c["z"], t_index, start["phase"]):
            return False
    return True


def try_ballistic_move(
    state: dict[str, int],
    offset: dict[str, int],
    model: Any,
    initial_vy: float,
    physics: dict[str, float],
    max_time: int,
    walkable_tolerance_cells: int,
) -> dict[str, int] | None:
    landing = {"x": state["x"] + offset["dx"], "y": state["y"] + offset["dy"], "z": state["z"] + offset["dz"]}
    horiz = math.hypot(offset["dx"], offset["dz"])
    if horiz < 0.01 and offset["dy"] == 0:
        return None

    start_info = model.getSurfaceInfo(state["t"], cell_key(state))
    if not start_info:
        return None

    t_land = state["t"] + 1
    if t_land > max_time:
        return None
    resolved = resolve_surface_at_time(model, landing, t_land, state["phase"], walkable_tolerance_cells)
    if not resolved:
        return None
    landing, land_info = resolved

    dy = float(land_info["surfaceY"]) - float(start_info["surfaceY"])
    horiz = math.hypot(float(landing["x"] - state["x"]), float(landing["z"] - state["z"]))
    min_time = horiz / physics["airSpeed"]
    time = choose_time_for_dy(dy, initial_vy, physics["gravity"], min_time, physics["maxJumpTime"])
    if time is None:
        return None

    ticks = max(1, int(math.ceil(time / physics["timeStep"])))
    t_land = state["t"] + ticks
    if t_land > max_time:
        return None

    resolved = resolve_surface_at_time(model, landing, t_land, state["phase"], walkable_tolerance_cells)
    if not resolved:
        return None
    landing, land_info = resolved
    dy = float(land_info["surfaceY"]) - float(start_info["surfaceY"])
    horiz = math.hypot(float(landing["x"] - state["x"]), float(landing["z"] - state["z"]))
    min_time_2 = horiz / physics["airSpeed"]
    time = choose_time_for_dy(dy, initial_vy, physics["gravity"], min_time_2, physics["maxJumpTime"])
    if time is None:
        return None
    ticks = max(1, int(math.ceil(time / physics["timeStep"])))
    t_land = state["t"] + ticks
    if t_land > max_time:
        return None

    resolved_landing = resolve_walkable_cell(model, landing, t_land, state["phase"], walkable_tolerance_cells)
    if not resolved_landing:
        return None
    landing = resolved_landing

    if not ballistic_path_clear(state, landing, time, ticks, model, initial_vy, physics, float(start_info["surfaceY"]), max_time):
        return None

    cid = cell_key(landing)
    next_phase = model.applyKeyPhase(state["phase"], cid)
    return {"x": landing["x"], "y": landing["y"], "z": landing["z"], "t": t_land, "phase": next_phase}


def ride_with_platform(
    state: dict[str, int],
    surface_info: dict[str, Any],
    model: Any,
    t_next: int,
    walkable_tolerance_cells: int,
) -> dict[str, int] | None:
    pid = surface_info.get("platformId")
    if not pid or not surface_info.get("moving"):
        return None
    p = model.platformById.get(pid)
    pos = model.getPlatformPos(pid, t_next)
    if not p or not pos:
        return None
    cx = int(round(float(pos["x"]) / model.cellSize))
    cz = int(round(float(pos["z"]) / model.cellSize))
    tx = cx + int(surface_info.get("localOffset", {}).get("x", 0))
    tz = cz + int(surface_info.get("localOffset", {}).get("z", 0))
    top_y = float(pos["y"]) + float(p["size"]["y"]) * 0.5
    ty = int(round(top_y / model.cellSize))
    resolved = resolve_walkable_cell(
        model,
        {"x": tx, "y": ty, "z": tz},
        t_next,
        state["phase"],
        walkable_tolerance_cells,
    )
    if not resolved:
        return None
    return {"x": resolved["x"], "y": resolved["y"], "z": resolved["z"], "t": t_next, "phase": state["phase"]}


def collect_neighbors(
    state: dict[str, int],
    model: Any,
    physics: dict[str, float],
    ground_offsets: list[dict[str, int]],
    jump_offsets: list[dict[str, int]],
    allow_jump: bool,
    allow_drop: bool,
    max_time: int,
    walkable_tolerance_cells: int,
) -> list[dict[str, int]]:
    nxt = []
    phase_count = model.phaseCount
    t_next = state["t"] + 1
    if t_next > max_time:
        return nxt

    def add_move(x: int, y: int, z: int, t: int, phase: int) -> None:
        cid = cell_key({"x": x, "y": y, "z": z})
        np = min(model.applyKeyPhase(phase, cid), phase_count - 1)
        nxt.append({"x": x, "y": y, "z": z, "t": t, "phase": np})

    if model.isWalkableCell(state["x"], state["y"], state["z"], t_next, state["phase"]):
        add_move(state["x"], state["y"], state["z"], t_next, state["phase"])

    for off in ground_offsets:
        x, y, z = state["x"] + off["dx"], state["y"], state["z"] + off["dz"]
        resolved = resolve_walkable_cell(
            model,
            {"x": x, "y": y, "z": z},
            t_next,
            state["phase"],
            walkable_tolerance_cells,
        )
        if not resolved:
            continue
        if not path_clear(state, resolved, t_next, model, state["phase"]):
            continue
        add_move(resolved["x"], resolved["y"], resolved["z"], t_next, state["phase"])

    s_info = model.getSurfaceInfo(state["t"], cell_key(state))
    if s_info and s_info.get("moving"):
        c = ride_with_platform(state, s_info, model, t_next, walkable_tolerance_cells)
        if c:
            add_move(c["x"], c["y"], c["z"], c["t"], c["phase"])

    if allow_jump or allow_drop:
        for off in jump_offsets:
            jump = (
                try_ballistic_move(
                    state,
                    off,
                    model,
                    physics["jumpSpeed"],
                    physics,
                    max_time,
                    walkable_tolerance_cells,
                )
                if allow_jump
                else None
            )
            if jump:
                nxt.append(jump)
                continue
            if allow_drop:
                drop = try_ballistic_move(state, off, model, 0.0, physics, max_time, walkable_tolerance_cells)
                if drop:
                    nxt.append(drop)

    return nxt


def estimate_max_time(model: Any) -> int:
    speed = 7.5
    padding = 40
    hard_min = 120
    phase_count = max(1, int(model.phaseCount or 1))
    s = model.startCell or {"x": 0, "y": 0, "z": 0}
    g = model.goalCell
    if g:
        dist = math.hypot(g["x"] - s["x"], g["z"] - s["z"])
    elif model.bounds:
        span_x = model.bounds["max"]["x"] - model.bounds["min"]["x"]
        span_z = model.bounds["max"]["z"] - model.bounds["min"]["z"]
        dist = math.hypot(span_x, span_z)
    else:
        dist = 0
    base = int(math.ceil(dist / speed) + padding)
    phase_budget = (phase_count - 1) * 90
    horizon_budget = max(0, int(model.timeHorizon) - 1) * 3
    est = base + max(phase_budget, horizon_budget)
    hard_max = max(360, base + phase_budget + horizon_budget)
    return max(hard_min, min(hard_max, est))


def compute_reachable(model: Any, options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options or {}
    allow_jump = bool(options.get("allowJump", True))
    allow_drop = bool(options.get("allowDrop", True))
    compress_time = bool(options.get("compressTime", True))
    walkable_tolerance_cells = max(0, min(2, int(options.get("walkableToleranceCells", 1))))
    max_time_cap = max(600, int(model.timeHorizon) * (int(model.phaseCount) + 2) * 2)
    raw_max_time = options.get("maxTime")
    max_time_input = estimate_max_time(model) if raw_max_time is None else int(raw_max_time)
    max_time = max(0, min(max_time_cap, max_time_input))
    max_states = max(1, min(1_200_000, int(options.get("maxStates", 250000))))
    max_queue = max(1, min(900_000, int(options.get("maxQueue", 200000))))
    max_jump_offsets = max(1, min(6000, int(options.get("maxJumpOffsets", 1400))))
    max_wall_time_sec = options.get("maxWallTimeSec")
    wall_limit = float(max_wall_time_sec) if max_wall_time_sec is not None else None
    wall_start = time.perf_counter()

    start_cell = model.findNearestWalkable(model.startCell, 0, 0) or model.startCell
    start = {"x": start_cell["x"], "y": start_cell["y"], "z": start_cell["z"], "t": 0, "phase": 0}
    horizon = max(1, int(getattr(model, "timeHorizon", 1) or 1))

    def visit_key(s: dict[str, int]) -> str:
        if not compress_time:
            return state_key(s)
        return f"{s['phase']}|{s['x']},{s['y']},{s['z']}|{int(s['t']) % horizon}"

    reachable = [[set() for _ in range(model.phaseCount)] for _ in range(max_time + 1)]
    q = deque([start])
    vis = {visit_key(start)}
    head_count = 0
    trunc = False

    physics = build_physics_profile(model)
    raw_ground = options.get("maxGroundDistance", physics["maxGroundDistance"])
    raw_jump = options.get("maxJumpDistance", physics["maxJumpDistance"])
    max_ground_distance = float(physics["maxGroundDistance"] if raw_ground is None else raw_ground)
    max_jump_distance = float(physics["maxJumpDistance"] if raw_jump is None else raw_jump)
    ground = build_ground_offsets(min(physics["maxGroundDistance"], max_ground_distance))
    jumps = (
        build_jump_offsets(
            min(physics["maxJumpDistance"], max_jump_distance),
            int(physics["maxJumpUp"]),
            int(physics["maxJumpDown"]),
            max_jump_offsets,
        )
        if allow_jump
        else []
    )

    while q:
        if wall_limit is not None and (time.perf_counter() - wall_start) > wall_limit:
            trunc = True
            break
        s = q.popleft()
        head_count += 1
        if head_count > max_states or len(q) > max_queue:
            trunc = True
            break
        reachable[s["t"]][s["phase"]].add(cell_key(s))
        for n in collect_neighbors(
            s,
            model,
            physics,
            ground,
            jumps,
            allow_jump,
            allow_drop,
            max_time,
            walkable_tolerance_cells,
        ):
            k = visit_key(n)
            if k in vis:
                continue
            vis.add(k)
            q.append(n)

    cumulative = [[set() for _ in range(model.phaseCount)] for _ in range(max_time + 1)]
    cumulative_union = [set() for _ in range(max_time + 1)]
    for t in range(max_time + 1):
        if t > 0:
            cumulative_union[t].update(cumulative_union[t - 1])
        for p in range(model.phaseCount):
            if t > 0:
                cumulative[t][p].update(cumulative[t - 1][p])
            cumulative[t][p].update(reachable[t][p])
            cumulative_union[t].update(cumulative[t][p])

    last_growth = 0
    for t in range(1, max_time + 1):
        if any(len(cumulative[t][p]) > len(cumulative[t - 1][p]) for p in range(model.phaseCount)):
            last_growth = t

    last_union_growth = 0
    for t in range(1, max_time + 1):
        if len(cumulative_union[t]) > len(cumulative_union[t - 1]):
            last_union_growth = t

    return {
        "reachableByTimePhase": reachable,
        "reachableCumulativeByTimePhase": cumulative,
        "reachableCumulativeByTimeUnion": cumulative_union,
        "visitedCount": len(vis),
        "expanded": head_count,
        "truncated": trunc,
        "startCell": start_cell,
        "maxTime": max_time,
        "maxTimeUsed": last_growth,
        "lastReachableCellTime": last_union_growth,
        "elapsedSec": time.perf_counter() - wall_start,
        "walkableToleranceCells": walkable_tolerance_cells,
    }


def search_shortest_goal_path(model: Any, options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options or {}
    allow_jump = bool(options.get("allowJump", True))
    allow_drop = bool(options.get("allowDrop", True))
    raw_max_time = options.get("maxTime")
    max_time = int(estimate_max_time(model) if raw_max_time is None else raw_max_time)
    max_states = int(options.get("maxStates", 450000))
    max_queue = int(options.get("maxQueue", 350000))
    max_jump_offsets = int(options.get("maxJumpOffsets", 1400))
    compress_time = bool(options.get("compressTime", True))
    walkable_tolerance_cells = max(0, min(2, int(options.get("walkableToleranceCells", 1))))
    max_wall_time_sec = options.get("maxWallTimeSec")
    wall_limit = float(max_wall_time_sec) if max_wall_time_sec is not None else None
    wall_start = time.perf_counter()

    if not model.goalCell:
        return {"ok": False, "reason": "missing_goal"}

    horizon = max(1, int(getattr(model, "timeHorizon", 1) or 1))
    start_cell = model.findNearestWalkable(model.startCell, 0, 0) or model.startCell
    start = {"x": start_cell["x"], "y": start_cell["y"], "z": start_cell["z"], "t": 0, "phase": 0}
    goal_base = model.goalCell
    goal_candidates = [goal_base]
    for phase in range(max(1, int(getattr(model, "phaseCount", 1) or 1))):
        snapped = model.findNearestWalkable(goal_base, 0, phase)
        if snapped:
            goal_candidates.append(snapped)
    dedup: dict[str, dict[str, int]] = {}
    for c in goal_candidates:
        dedup[cell_key(c)] = c
    goal_cells = list(dedup.values())
    goal_ids = set(dedup.keys())
    goal_cell = min(
        goal_cells,
        key=lambda c: math.hypot(float(c["x"] - goal_base["x"]), float(c["z"] - goal_base["z"])) + 0.5 * abs(float(c["y"] - goal_base["y"])),
    )

    def visit_key(s: dict[str, int]) -> str:
        if not compress_time:
            return state_key(s)
        return f"{s['phase']}|{s['x']},{s['y']},{s['z']}|{int(s['t']) % horizon}"

    def score_to_goal(s: dict[str, int]) -> float:
        dx = float(goal_cell["x"] - s["x"])
        dy = float(goal_cell["y"] - s["y"])
        dz = float(goal_cell["z"] - s["z"])
        return math.hypot(dx, dz) + 0.5 * abs(dy)

    q = deque([start])
    start_visit_key = visit_key(start)
    vis = {start_visit_key}
    prev: dict[str, str] = {}
    state_by_key = {start_visit_key: start}

    physics = build_physics_profile(model)
    raw_ground = options.get("maxGroundDistance", physics["maxGroundDistance"])
    raw_jump = options.get("maxJumpDistance", physics["maxJumpDistance"])
    max_ground_distance = float(physics["maxGroundDistance"] if raw_ground is None else raw_ground)
    max_jump_distance = float(physics["maxJumpDistance"] if raw_jump is None else raw_jump)
    ground = build_ground_offsets(min(physics["maxGroundDistance"], max_ground_distance))
    jumps = (
        build_jump_offsets(
            min(physics["maxJumpDistance"], max_jump_distance),
            int(physics["maxJumpUp"]),
            int(physics["maxJumpDown"]),
            max_jump_offsets,
        )
        if allow_jump
        else []
    )

    expanded = 0
    goal_state = None
    best_key = start_visit_key
    best_score = score_to_goal(start)

    def reconstruct_path(last_key: str) -> list[dict[str, int]]:
        trail = []
        cur = last_key
        while True:
            trail.append(state_by_key[cur])
            if cur not in prev:
                break
            cur = prev[cur]
        trail.reverse()
        return trail

    while q:
        if wall_limit is not None and (time.perf_counter() - wall_start) > wall_limit:
            return {
                "ok": False,
                "reason": "wall_time_exceeded",
                "expanded": expanded,
                "visited": len(vis),
                "path": reconstruct_path(best_key),
                "partial": True,
                "elapsedSec": time.perf_counter() - wall_start,
            }
        s = q.popleft()
        expanded += 1
        if expanded > max_states or len(q) > max_queue:
            return {
                "ok": False,
                "reason": "budget_exceeded",
                "expanded": expanded,
                "visited": len(vis),
                "path": reconstruct_path(best_key),
                "partial": True,
                "elapsedSec": time.perf_counter() - wall_start,
            }
        if cell_key(s) in goal_ids:
            goal_state = s
            break
        cur_score = score_to_goal(s)
        if cur_score + 1e-9 < best_score or (abs(cur_score - best_score) <= 1e-9 and s["t"] > state_by_key[best_key]["t"]):
            best_score = cur_score
            best_key = visit_key(s)
        for n in collect_neighbors(
            s,
            model,
            physics,
            ground,
            jumps,
            allow_jump,
            allow_drop,
            max_time,
            walkable_tolerance_cells,
        ):
            k = visit_key(n)
            if k in vis:
                continue
            vis.add(k)
            prev[k] = visit_key(s)
            state_by_key[k] = n
            q.append(n)

    if not goal_state:
        return {
            "ok": False,
            "reason": "goal_unreachable",
            "expanded": expanded,
            "visited": len(vis),
            "path": reconstruct_path(best_key),
            "partial": True,
            "elapsedSec": time.perf_counter() - wall_start,
        }

    goal_key = visit_key(goal_state)
    trail = reconstruct_path(goal_key)

    return {
        "ok": True,
        "path": trail,
        "expanded": expanded,
        "visited": len(vis),
        "time": goal_state["t"],
        "phase": goal_state["phase"],
        "elapsedSec": time.perf_counter() - wall_start,
    }

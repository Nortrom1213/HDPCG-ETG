"""Build 5D HDPCG model (x,y,z,time,phase) from level JSON."""

from __future__ import annotations

import math
from typing import Any

from .paper_config import load_paper_config

DEFAULT_PADDING = 4
LOCK_PADDING = 0.6
LOCK_PLAYER_RADIUS = 0.6


def cell_key(cell: dict[str, int]) -> str:
    return f"{cell['x']},{cell['y']},{cell['z']}"


def to_cell_coord(pos: dict[str, float], cell_size: float) -> dict[str, int]:
    return {
        "x": int(round(float(pos["x"]) / cell_size)),
        "y": int(math.floor(float(pos["y"]) / cell_size + 1e-3)),
        "z": int(round(float(pos["z"]) / cell_size)),
    }


def gcd(a: int, b: int) -> int:
    x, y = abs(int(a)), abs(int(b))
    while y:
        x, y = y, x % y
    return x


def lcm(a: int, b: int) -> int:
    return abs(a * b) // max(1, gcd(a, b))


def lcm_array(values: list[int]) -> int:
    out = 1
    for v in values:
        out = lcm(out, max(1, int(v)))
    return out


def extract_number(value: str) -> float:
    import re

    m = re.search(r"\d+", str(value or ""))
    if not m:
        return float("inf")
    return float(m.group(0))


def build_key_order(keys: list[dict[str, Any]], locks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for key in keys or []:
        kid = key.get("key_id")
        if kid and kid not in by_id:
            by_id[kid] = key
    for lock in locks or []:
        kid = lock.get("key_id")
        if kid and kid not in by_id:
            by_id[kid] = {"key_id": kid, "_virtual": True}
    out = list(by_id.values())
    out.sort(key=lambda x: (extract_number(x.get("key_id")), str(x.get("key_id"))))
    return out


def sample_platform_pos(platform: dict[str, Any], t: int, time_step: float) -> dict[str, float]:
    pos = dict(platform.get("pos") or {})
    motion = platform.get("motion") or {}
    axis = motion.get("axis")
    if platform.get("kind") != "moving" or not motion or axis not in {"x", "z"}:
        return pos
    ticks = max(1, int(round(float(motion.get("period", 1.0)) / time_step)))
    omega = (2 * math.pi) / ticks
    offset = math.sin(omega * t + float(motion.get("phase", 0.0))) * float(motion.get("amplitude", 0.0))
    pos[axis] = float(platform["pos"][axis]) + offset
    return pos


def sample_enemy_pos(enemy: dict[str, Any], t: int, time_step: float) -> dict[str, float] | None:
    patrol = enemy.get("patrol")
    if not patrol:
        return enemy.get("pos")
    span = float(patrol["to"]["x"]) - float(patrol["from"]["x"])
    total = abs(span)
    if total <= 0:
        return enemy.get("pos")
    speed = max(1e-4, float(enemy.get("speed", 1.0)))
    step = speed * time_step
    offset = (t * step) % (2 * total)
    if offset > total:
        offset = 2 * total - offset
    direction = 1 if span >= 0 else -1
    return {
        "x": float(patrol["from"]["x"]) + direction * offset,
        "y": float(patrol["from"]["y"]),
        "z": float(patrol["from"]["z"]),
    }


def surface_cells_for_platform(platform: dict[str, Any], pos: dict[str, float], cell_size: float) -> list[dict[str, Any]]:
    half_x = float(platform["size"]["x"]) * 0.5
    half_z = float(platform["size"]["z"]) * 0.5
    top_y = float(pos["y"]) + float(platform["size"]["y"]) * 0.5
    gy = int(math.floor(top_y / cell_size + 1e-3))

    min_x = (float(pos["x"]) - half_x) / cell_size
    max_x = (float(pos["x"]) + half_x) / cell_size
    min_z = (float(pos["z"]) - half_z) / cell_size
    max_z = (float(pos["z"]) + half_z) / cell_size

    sx, ex = int(math.ceil(min_x)), int(math.floor(max_x))
    sz, ez = int(math.ceil(min_z)), int(math.floor(max_z))

    cx, cz = int(round(float(pos["x"]) / cell_size)), int(round(float(pos["z"]) / cell_size))

    cells = []
    for x in range(sx, ex + 1):
        for z in range(sz, ez + 1):
            cells.append(
                {
                    "x": x,
                    "y": gy,
                    "z": z,
                    "platformId": platform.get("id"),
                    "moving": platform.get("kind") == "moving",
                    "surfaceY": top_y,
                    "localOffset": {"x": x - cx, "z": z - cz},
                }
            )
    return cells


def compute_time_horizon(
    level: dict[str, Any],
    time_step: float,
    *,
    max_horizon: int = 180,
    max_period_ticks: int = 180,
) -> int:
    horizon_cap = max(1, int(max_horizon))
    period_cap = max(1, int(max_period_ticks))
    periods: list[int] = []
    for p in level.get("platforms") or []:
        if p.get("kind") != "moving" or not p.get("motion"):
            continue
        ticks = max(1, int(round(float((p.get("motion") or {}).get("period", 1.0)) / time_step)))
        ticks = min(period_cap, ticks)
        periods.append(ticks)
    for e in level.get("enemies") or []:
        if not e.get("patrol"):
            continue
        span = abs(float(e["patrol"]["to"]["x"]) - float(e["patrol"]["from"]["x"]))
        speed = max(1e-4, float(e.get("speed", 1.0)))
        ticks = max(1, int(round((2 * span) / (speed * time_step))))
        ticks = min(period_cap, ticks)
        periods.append(ticks)
    if not periods:
        return 1
    out = 1
    for v in periods:
        out = lcm(out, max(1, int(v)))
        if out >= horizon_cap:
            return horizon_cap
    return max(1, min(horizon_cap, out))


def compute_bounds(level: dict[str, Any], cell_size: float, padding: int) -> dict[str, dict[str, int]]:
    mn = {"x": float("inf"), "y": float("inf"), "z": float("inf")}
    mx = {"x": float("-inf"), "y": float("-inf"), "z": float("-inf")}

    def expand(x: float, y: float, z: float) -> None:
        mn["x"] = min(mn["x"], x)
        mn["y"] = min(mn["y"], y)
        mn["z"] = min(mn["z"], z)
        mx["x"] = max(mx["x"], x)
        mx["y"] = max(mx["y"], y)
        mx["z"] = max(mx["z"], z)

    for p in level.get("platforms") or []:
        sx, sy, sz = float(p["size"]["x"]), float(p["size"]["y"]), float(p["size"]["z"])
        px, py, pz = float(p["pos"]["x"]), float(p["pos"]["y"]), float(p["pos"]["z"])
        half_x, half_y, half_z = sx * 0.5, sy * 0.5, sz * 0.5
        min_x, max_x = px - half_x, px + half_x
        min_z, max_z = pz - half_z, pz + half_z
        if p.get("kind") == "moving" and p.get("motion"):
            amp = abs(float((p.get("motion") or {}).get("amplitude", 0.0)))
            axis = (p.get("motion") or {}).get("axis")
            if axis == "x":
                min_x -= amp
                max_x += amp
            elif axis == "z":
                min_z -= amp
                max_z += amp
        expand(min_x, py - half_y, min_z)
        expand(max_x, py + half_y, max_z)

    for e in level.get("enemies") or []:
        if e.get("patrol"):
            expand(float(e["patrol"]["from"]["x"]), float(e["patrol"]["from"]["y"]), float(e["patrol"]["from"]["z"]))
            expand(float(e["patrol"]["to"]["x"]), float(e["patrol"]["to"]["y"]), float(e["patrol"]["to"]["z"]))
        elif e.get("pos"):
            expand(float(e["pos"]["x"]), float(e["pos"]["y"]), float(e["pos"]["z"]))

    for k in level.get("keys") or []:
        expand(float(k["pos"]["x"]), float(k["pos"]["y"]), float(k["pos"]["z"]))
    for l in level.get("locks") or []:
        expand(float(l["pos"]["x"]), float(l["pos"]["y"]), float(l["pos"]["z"]))
    if level.get("start"):
        expand(float(level["start"]["x"]), float(level["start"]["y"]), float(level["start"]["z"]))
    if level.get("goal"):
        expand(float(level["goal"]["x"]), float(level["goal"]["y"]), float(level["goal"]["z"]))

    if mn["x"] == float("inf"):
        mn, mx = {"x": -4, "y": -4, "z": -4}, {"x": 4, "y": 4, "z": 4}

    return {
        "min": {"x": int(math.floor(mn["x"] / cell_size) - padding), "y": int(math.floor(mn["y"] / cell_size) - padding), "z": int(math.floor(mn["z"] / cell_size) - padding)},
        "max": {"x": int(math.ceil(mx["x"] / cell_size) + padding), "y": int(math.ceil(mx["y"] / cell_size) + padding), "z": int(math.ceil(mx["z"] / cell_size) + padding)},
    }


def build_surface_column_map(surface_map: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for c in surface_map.values():
        k = f"{c['x']},{c['z']}"
        out.setdefault(k, []).append(c)
    return out


def snap_to_surface_cell(pos: dict[str, float], surface_columns: dict[str, list[dict[str, Any]]], cell_size: float) -> dict[str, int] | None:
    bx = int(round(float(pos["x"]) / cell_size))
    bz = int(round(float(pos["z"]) / cell_size))
    best = None
    best_dist = float("inf")
    for dx in range(-1, 2):
        for dz in range(-1, 2):
            col = surface_columns.get(f"{bx + dx},{bz + dz}")
            if not col:
                continue
            for c in col:
                d = abs(float(c.get("surfaceY", 0.0)) - float(pos["y"]))
                if d < best_dist:
                    best_dist = d
                    best = c
    if not best:
        return None
    return {"x": best["x"], "y": best["y"], "z": best["z"]}


def expand_lock_volume(lock: dict[str, Any], cell_size: float, padding: float) -> list[dict[str, int]]:
    size = lock.get("size") or {"x": 2, "y": 3, "z": 0.6}
    half = {"x": float(size["x"]) * 0.5 + padding, "y": float(size["y"]) * 0.5 + padding, "z": float(size["z"]) * 0.5 + padding}
    min_x = int(math.floor((float(lock["pos"]["x"]) - half["x"]) / cell_size))
    max_x = int(math.floor((float(lock["pos"]["x"]) + half["x"]) / cell_size))
    min_y = int(math.floor((float(lock["pos"]["y"]) - half["y"]) / cell_size))
    max_y = int(math.floor((float(lock["pos"]["y"]) + half["y"]) / cell_size))
    min_z = int(math.floor((float(lock["pos"]["z"]) - half["z"]) / cell_size))
    max_z = int(math.floor((float(lock["pos"]["z"]) + half["z"]) / cell_size))
    cells = []
    for x in range(min_x, max_x + 1):
        for y in range(min_y, max_y + 1):
            for z in range(min_z, max_z + 1):
                cells.append({"x": x, "y": y, "z": z})
    return cells


def expand_lock_footprint(
    lock: dict[str, Any],
    surface_map: dict[str, dict[str, Any]],
    surface_columns: dict[str, list[dict[str, Any]]],
    cell_size: float,
    padding: float,
    player_radius: float,
) -> list[dict[str, int]]:
    if not surface_map:
        return []
    size = lock.get("size") or {"x": 2, "y": 3, "z": 0.6}
    thin_axis = "x" if float(size["x"]) <= float(size["z"]) else "z"
    band = (float(size[thin_axis]) * 0.5) + padding + player_radius
    min_y = float(lock["pos"]["y"]) - float(size["y"]) * 0.5 - padding - player_radius
    max_y = float(lock["pos"]["y"]) + float(size["y"]) * 0.5 + padding + player_radius
    min_y_cell = int(math.floor(min_y / cell_size))
    max_y_cell = int(math.floor(max_y / cell_size))

    seed = snap_to_surface_cell(lock.get("pos") or {"x": 0, "y": 0, "z": 0}, surface_columns, cell_size)
    if not seed:
        return []

    visited: set[str] = set()
    queue: list[dict[str, Any]] = []

    def push(cell: dict[str, Any]) -> None:
        cid = cell_key(cell)
        if cid in visited:
            return
        visited.add(cid)
        queue.append(cell)

    seed_surface = surface_map.get(cell_key(seed))
    if seed_surface:
        push(seed_surface)
    else:
        push(seed)

    component: list[dict[str, Any]] = []
    neighbor_deltas = [{"dx": 1, "dz": 0}, {"dx": -1, "dz": 0}, {"dx": 0, "dz": 1}, {"dx": 0, "dz": -1}]
    y_offsets = [0, 1, -1]

    head = 0
    while head < len(queue):
        current = queue[head]
        head += 1
        component.append(current)
        for delta in neighbor_deltas:
            for dy in y_offsets:
                neighbor = {"x": current["x"] + delta["dx"], "y": current["y"] + dy, "z": current["z"] + delta["dz"]}
                surface = surface_map.get(cell_key(neighbor))
                if not surface:
                    continue
                push(surface)

    cells: list[dict[str, int]] = []
    for cell in component:
        world_x = float(cell["x"]) * cell_size
        world_z = float(cell["z"]) * cell_size
        axis_dist = world_x - float(lock["pos"]["x"]) if thin_axis == "x" else world_z - float(lock["pos"]["z"])
        if abs(axis_dist) > band + 1e-3:
            continue
        surface_y = float(cell.get("surfaceY", float(cell["y"]) * cell_size))
        if surface_y < min_y or surface_y > max_y:
            continue
        for y in range(min_y_cell, max_y_cell + 1):
            cells.append({"x": int(cell["x"]), "y": y, "z": int(cell["z"])})
    return cells


def expand_pickup_cells(pos: dict[str, float], fallback: dict[str, int], cell_size: float, radius: float, surface_columns: dict[str, list[dict[str, Any]]]) -> list[dict[str, int]]:
    cells = []
    seen = set()
    max_off = max(1, int(math.ceil(radius / cell_size) + 1))
    bx = int(round(float(pos["x"]) / cell_size))
    bz = int(round(float(pos["z"]) / cell_size))
    for dx in range(-max_off, max_off + 1):
        for dz in range(-max_off, max_off + 1):
            col = surface_columns.get(f"{bx + dx},{bz + dz}")
            if not col:
                continue
            for c in col:
                wx, wy, wz = c["x"] * cell_size, float(c.get("surfaceY", c["y"] * cell_size)), c["z"] * cell_size
                d = math.hypot(wx - float(pos["x"]), wy - float(pos["y"]), wz - float(pos["z"]))
                if d > radius + 1e-3:
                    continue
                cid = cell_key(c)
                if cid in seen:
                    continue
                seen.add(cid)
                cells.append({"x": c["x"], "y": c["y"], "z": c["z"]})
    if cell_key(fallback) not in seen:
        cells.append(fallback)
    return cells


class HDPCGModel:
    def __init__(self, data: dict[str, Any]) -> None:
        self.__dict__.update(data)


def build_hdpcg_model(level: dict[str, Any], options: dict[str, Any] | None = None) -> HDPCGModel:
    options = options or {}
    paper = load_paper_config()
    state = paper["state_model"]
    simulation = paper["simulation"]
    cell_size = float(options.get("cellSize", state["cell_size"]))
    time_step = float(options.get("timeStep", state["time_step_seconds"]))
    padding = int(options.get("padding", state["global_padding_cells"]))
    max_time_horizon = int(options.get("maxTimeHorizon", state["max_time_horizon"]))
    max_period_ticks = int(options.get("maxPeriodTicks", state["max_period_ticks"]))

    key_order = build_key_order(level.get("keys") or [], level.get("locks") or [])
    key_index = {k.get("key_id"): i for i, k in enumerate(key_order)}
    phase_count = len(key_order) + 1

    platform_by_id = {p.get("id"): p for p in level.get("platforms") or []}
    moving_platform_ids = {p.get("id") for p in level.get("platforms") or [] if p.get("kind") == "moving" and p.get("motion")}

    time_horizon = compute_time_horizon(
        level,
        time_step,
        max_horizon=max_time_horizon,
        max_period_ticks=max_period_ticks,
    )
    bounds = compute_bounds(level, cell_size, padding)

    surface_by_time = [dict() for _ in range(time_horizon)]
    static_platforms = [p for p in level.get("platforms") or [] if p.get("kind") != "moving" or not p.get("motion")]
    moving_platforms = [p for p in level.get("platforms") or [] if p.get("kind") == "moving" and p.get("motion")]

    static_cells = []
    for p in static_platforms:
        static_cells.extend(surface_cells_for_platform(p, p.get("pos") or {"x": 0, "y": 0, "z": 0}, cell_size))

    for t in range(time_horizon):
        m = surface_by_time[t]
        for c in static_cells:
            m[cell_key(c)] = c
        for p in moving_platforms:
            pos = sample_platform_pos(p, t, time_step)
            for c in surface_cells_for_platform(p, pos, cell_size):
                m[cell_key(c)] = c

    enemies_by_time = [set() for _ in range(time_horizon)]
    for t in range(time_horizon):
        st = enemies_by_time[t]
        for e in level.get("enemies") or []:
            pos = sample_enemy_pos(e, t, time_step)
            if not pos:
                continue
            st.add(cell_key(to_cell_coord(pos, cell_size)))

    surface_columns = build_surface_column_map(surface_by_time[0])
    key_cells: dict[str, int] = {}
    key_pickup_cells: dict[str, int] = {}
    lock_cells: dict[str, int] = {}

    for k in level.get("keys") or []:
        snapped = snap_to_surface_cell(k.get("pos") or {"x": 0, "y": 0, "z": 0}, surface_columns, cell_size)
        c = snapped or to_cell_coord(k.get("pos") or {"x": 0, "y": 0, "z": 0}, cell_size)
        idx = key_index.get(k.get("key_id"))
        if idx is None:
            continue
        key_cells[cell_key(c)] = idx
        for pcell in expand_pickup_cells(
            k.get("pos") or {"x": 0, "y": 0, "z": 0},
            c,
            cell_size,
            float(simulation["key_pickup_radius"]),
            surface_columns,
        ):
            pid = cell_key(pcell)
            old = key_pickup_cells.get(pid)
            if old is None or idx < old:
                key_pickup_cells[pid] = idx

    def add_lock_cell(c: dict[str, int], idx: int) -> None:
        cid = cell_key(c)
        old = lock_cells.get(cid)
        if old is None or (old < 0 and idx >= 0) or (idx >= 0 and idx < old):
            lock_cells[cid] = idx

    for lock in level.get("locks") or []:
        idx = key_index.get(lock.get("key_id"), -1)
        lock_padding = float(simulation["lock_padding"])
        player_radius = float(simulation["lock_player_radius"])
        for c in expand_lock_volume(lock, cell_size, lock_padding):
            add_lock_cell(c, idx)
        for c in expand_lock_footprint(
            lock,
            surface_by_time[0] if surface_by_time else {},
            surface_columns,
            cell_size,
            lock_padding,
            player_radius,
        ):
            add_lock_cell(c, idx)

    start_cell = to_cell_coord(level.get("start") or {"x": 0, "y": 0, "z": 0}, cell_size)
    goal_cell = to_cell_coord(level.get("goal"), cell_size) if level.get("goal") else None

    def wrap_time(t: int) -> int:
        if time_horizon <= 0:
            return 0
        return int(t) % time_horizon

    def is_locked_cell(cell_id: str, phase: int) -> bool:
        if cell_id not in lock_cells:
            return False
        idx = lock_cells[cell_id]
        if idx < 0:
            return False
        return phase <= idx

    def is_enemy_cell(cell_id: str, t: int) -> bool:
        return cell_id in enemies_by_time[wrap_time(t)]

    def is_walkable_cell(x: int, y: int, z: int, t: int, phase: int) -> bool:
        cid = cell_key({"x": x, "y": y, "z": z})
        if cid not in surface_by_time[wrap_time(t)]:
            return False
        if is_enemy_cell(cid, t):
            return False
        if is_locked_cell(cid, phase):
            return False
        return True

    def is_blocked_cell(x: int, y: int, z: int, t: int, phase: int) -> bool:
        cid = cell_key({"x": x, "y": y, "z": z})
        return is_enemy_cell(cid, t) or is_locked_cell(cid, phase)

    def apply_key_phase(phase: int, cell_id: str) -> int:
        if cell_id not in key_pickup_cells:
            return phase
        idx = key_pickup_cells[cell_id]
        if phase == idx:
            return min(phase + 1, phase_count - 1)
        return phase

    def find_nearest_walkable(cell: dict[str, int], t: int, phase: int, max_radius: int = 6) -> dict[str, int] | None:
        if is_walkable_cell(cell["x"], cell["y"], cell["z"], t, phase):
            return dict(cell)
        for r in range(1, max_radius + 1):
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    for dz in range(-r, r + 1):
                        c = {"x": cell["x"] + dx, "y": cell["y"] + dy, "z": cell["z"] + dz}
                        if is_walkable_cell(c["x"], c["y"], c["z"], t, phase):
                            return c
        return None

    def get_surface_info(t: int, cell_id: str) -> dict[str, Any] | None:
        return surface_by_time[wrap_time(t)].get(cell_id)

    def get_platform_pos(platform_id: str, t: int) -> dict[str, float] | None:
        p = platform_by_id.get(platform_id)
        if not p:
            return None
        if p.get("kind") != "moving" or not p.get("motion"):
            return dict(p.get("pos") or {})
        return sample_platform_pos(p, wrap_time(t), time_step)

    return HDPCGModel(
        {
            "cellSize": cell_size,
            "timeStep": time_step,
            "timeHorizon": time_horizon,
            "phaseCount": phase_count,
            "bounds": bounds,
            "platformById": platform_by_id,
            "movingPlatformIds": moving_platform_ids,
            "keyCells": key_cells,
            "keyPickupCells": key_pickup_cells,
            "lockCells": lock_cells,
            "surfaceByTime": surface_by_time,
            "enemiesByTime": enemies_by_time,
            "startCell": start_cell,
            "goalCell": goal_cell,
            "isWalkableCell": is_walkable_cell,
            "isBlockedCell": is_blocked_cell,
            "isLockedCell": is_locked_cell,
            "isEnemyCell": is_enemy_cell,
            "wrapTime": wrap_time,
            "applyKeyPhase": apply_key_phase,
            "findNearestWalkable": find_nearest_walkable,
            "getSurfaceInfo": get_surface_info,
            "getPlatformPos": get_platform_pos,
        }
    )

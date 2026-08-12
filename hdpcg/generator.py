"""Python ETG->Level generators (lane, incremental, constraint-based, GA, CP-SAT)."""

from __future__ import annotations

import math
import copy
import heapq
from dataclasses import dataclass
from typing import Any, Callable

from .component_rules import check_component_hard_constraints
from .component_sampling import build_candidate_pool
from .component_scoring import score_candidate, select_candidate_order
from .etg_core import NODE_TYPES, compute_canonical_route
from .random_utils import Mulberry32, rand_range

DEFAULT_EDGE_LENGTH = 30.0
PLATFORM_SIZE = {"x": 3.0, "y": 1.0, "z": 3.0}
LOCK_GATE_SPAN = 18.0
LOCK_GATE_WIDTH = 4.2
LOCK_GATE_HEIGHT = 7.0
ENEMY_CLEARANCE_Y = 1.2


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def clamp_int(v: Any, lo: int, hi: int) -> int:
    try:
        n = int(round(float(v)))
    except Exception:
        n = lo
    return max(lo, min(hi, n))


def node_has_type(node: dict[str, Any], t: str) -> bool:
    types = node.get("types") if isinstance(node.get("types"), list) and node.get("types") else ([node.get("type")] if node.get("type") else [])
    return t in types


def normalize_heading(h: dict[str, float]) -> dict[str, float]:
    l = math.hypot(h.get("x", 0.0), h.get("z", 0.0)) or 1.0
    return {"x": h.get("x", 0.0) / l, "z": h.get("z", 0.0) / l}


def snap_heading_to_axis(h: dict[str, float]) -> dict[str, float]:
    n = normalize_heading(h)
    if abs(n["x"]) >= abs(n["z"]):
        return {"x": 1 if n["x"] >= 0 else -1, "z": 0}
    return {"x": 0, "z": 1 if n["z"] >= 0 else -1}


def undirected_pair_key(a: str, b: str) -> str:
    x, y = str(a), str(b)
    return f"{x}|{y}" if x < y else f"{y}|{x}"


def directed_pair_key(a: str, b: str) -> str:
    return f"{a}->{b}"


def pick_sector_index(node_state: dict[str, Any], sector_count: int, attempt: int) -> int:
    count = max(1, int(sector_count))
    shift = abs(int(round(float(node_state.get("sector_shift", 0))))) % count
    preferred = (shift + abs(int(round(float(node_state.get("outgoing", 0))))) ) % count
    start = (preferred + abs(int(round(float(attempt))))) % count
    used = node_state.get("used")
    if isinstance(used, set) and len(used) < count:
        for k in range(count):
            idx = (start + k) % count
            if idx not in used:
                return idx
    return start


def sample_heading_from_sector(
    node_state: dict[str, Any],
    sector_index: int,
    sector_count: int,
    rng: Mulberry32,
    jitter_ratio: float = 0.35,
) -> dict[str, float]:
    count = max(1, int(sector_count))
    idx = abs(int(round(float(sector_index)))) % count
    base = ((idx / count) * math.pi * 2.0) + float(node_state.get("base_angle", 0.0))
    r = clamp(float(jitter_ratio), 0.0, 1.2)
    jitter = rand_range(rng, -r, r) * (math.pi * 2.0 / count)
    a = base + jitter
    return normalize_heading({"x": math.cos(a), "z": math.sin(a)})


@dataclass
class LevelBuilder:
    level: dict[str, Any]
    p: int = 0
    e: int = 0
    k: int = 0
    l: int = 0
    c: int = 0

    def ensure_map(self, node_id: str) -> dict[str, list[str]]:
        m = self.level["mapping"]["node"]
        if node_id not in m:
            m[node_id] = {"platforms": [], "enemies": [], "keys": [], "locks": [], "checkpoints": []}
        return m[node_id]

    def add_platform(self, pos: dict[str, float], size: dict[str, float], node_id: str, tags: list[str] | None = None) -> dict[str, Any]:
        item = {
            "id": f"P{self.p}",
            "pos": {"x": float(pos["x"]), "y": float(pos["y"]), "z": float(pos["z"])} ,
            "size": {"x": float(size["x"]), "y": float(size["y"]), "z": float(size["z"])} ,
            "kind": "static",
            "motion": None,
            "tags": list(tags or []),
            "node_id": node_id,
        }
        self.p += 1
        self.level["platforms"].append(item)
        self.ensure_map(node_id)["platforms"].append(item["id"])
        return item

    def add_enemy(self, pos: dict[str, float], patrol: dict[str, Any], node_id: str, speed: float = 1.2) -> dict[str, Any]:
        item = {
            "id": f"E{self.e}",
            "pos": {"x": float(pos["x"]), "y": float(pos["y"]), "z": float(pos["z"])} ,
            "radius": 0.6,
            "patrol": patrol,
            "speed": float(speed),
            "node_id": node_id,
        }
        self.e += 1
        self.level["enemies"].append(item)
        self.ensure_map(node_id)["enemies"].append(item["id"])
        return item

    def add_key(self, pos: dict[str, float], key_id: str, node_id: str) -> dict[str, Any]:
        item = {
            "id": f"K{self.k}",
            "key_id": key_id,
            "pos": {"x": float(pos["x"]), "y": float(pos["y"]), "z": float(pos["z"])} ,
            "radius": 0.4,
            "node_id": node_id,
        }
        self.k += 1
        self.level["keys"].append(item)
        self.ensure_map(node_id)["keys"].append(item["id"])
        return item

    def add_lock(self, pos: dict[str, float], lock_id: str, key_id: str, node_id: str, size: dict[str, float]) -> dict[str, Any]:
        item = {
            "id": f"L{self.l}",
            "lock_id": lock_id,
            "key_id": key_id,
            "pos": {"x": float(pos["x"]), "y": float(pos["y"]), "z": float(pos["z"])} ,
            "size": size,
            "node_id": node_id,
            "locked": True,
        }
        self.l += 1
        self.level["locks"].append(item)
        self.ensure_map(node_id)["locks"].append(item["id"])
        return item


def make_level(etg: dict[str, Any], config: dict[str, Any], mode: str) -> tuple[dict[str, Any], LevelBuilder]:
    strategy = str(config.get("componentStrategy", "diverse")).strip() or "diverse"
    level = {
        "meta": {
            "seed": config.get("seed"),
            "config": dict(config),
            "etg_version": 2,
            "generator_mode": mode,
            "component_generation": {
                "version": "di-hdpcg-v1",
                "strategy": strategy,
                "family_usage": {},
                "selection_stats": {
                    "candidate_total": 0,
                    "candidate_accepted": 0,
                    "rejected_constraints": 0,
                    "rejected_overlap": 0,
                    "rejected_validation": 0,
                    "rejected_risk": 0,
                    "fallback_uses": 0,
                    "requeued_canonical": 0,
                    "canonical_rescue_relax": 0,
                    "post_edge_repairs": 0,
                    "key_lock_precheck_delays": 0,
                    "key_lock_repairs": 0,
                    "main_spine_edge_attempts": 0,
                    "main_spine_edge_success": 0,
                    "main_spine_edge_fail": 0,
                    "main_spine_rollbacks": 0,
                    "main_spine_repairs": 0,
                    "main_spine_lock_precheck_delays": 0,
                    "main_spine_forced_linear": 0,
                    "main_spine_infill_edges": 0,
                    "main_infill_diversity_checks": 0,
                    "main_infill_diversity_target_hits": 0,
                    "main_infill_diversity_target_hit_rate": 0.0,
                    "main_infill_edge_coverage_ratio": 0.0,
                    "main_infill_edges_built": 0,
                    "noncanonical_edges_built": 0,
                    "family_usage_legacy_updates": 0,
                    "event_pacing_adjustments": 0,
                    "local_validation_calls": 0,
                    "local_validation_failures": 0,
                    "local_validation_quick_failures": 0,
                    "local_validation_quick_soft_failures": 0,
                    "local_validation_skips": 0,
                    "required_key_path_repairs": 0,
                    "missing_key_nodes_before_repair": 0,
                    "missing_key_nodes_after_repair": 0,
                    "main_route_repairs": 0,
                },
            },
        },
        "etg": etg,
        "platforms": [], "enemies": [], "keys": [], "locks": [], "checkpoints": [],
        "start": None, "goal": None,
        "mapping": {"node": {}, "edge": {}},
        "anchors": {},
    }
    return level, LevelBuilder(level)


def add_connector(
    edge: dict[str, Any],
    a: dict[str, float],
    b: dict[str, float],
    builder: LevelBuilder,
    rng: Mulberry32,
    style: dict[str, Any] | None = None,
    segment_length: float = 6.0,
) -> dict[str, Any]:
    edge_key = f"edge:{edge.get('id')}"
    dist = math.hypot(b["x"] - a["x"], b["z"] - a["z"])
    step_span = clamp(float(segment_length), 2.5, 14.0)
    steps = clamp_int(round(dist / step_span), 1, 48)
    family = (style or {}).get("family", "linear_bridge")
    lat_amp = clamp(float((style or {}).get("lateralAmplitude", 1.0)), 0.0, 3.5)
    vert_amp = clamp(float((style or {}).get("verticalAmplitude", 0.8)), 0.0, 3.0)
    zig_period = clamp(float((style or {}).get("zigzagPeriod", 4.5)), 1.5, 9.0)
    stair_step = clamp(float((style or {}).get("stairStep", 0.6)), 0.2, 1.5)
    moving_rate = clamp(float((style or {}).get("movingRate", 0.35)), 0.0, 1.0)
    hazard_density = clamp(float((style or {}).get("hazardDensity", 0.25)), 0.0, 1.0)
    axis = normalize_heading({"x": b["x"] - a["x"], "z": b["z"] - a["z"]})
    right = {"x": -axis["z"], "z": axis["x"]}
    size = {
        "x": 6.8 + lat_amp * 0.9,
        "y": 0.8,
        "z": 5.8 + lat_amp * 0.6,
    }
    entry = None
    last = None
    for i in range(1, steps + 1):
        t = i / (steps + 1)
        local = t * dist
        wave = math.sin((local / zig_period) * math.pi * 2.0)
        lateral = 0.0
        vertical = 0.0
        if family == "zigzag_bridge":
            lateral = wave * lat_amp
        if family == "arc_bridge":
            vertical = math.sin(t * math.pi) * vert_amp
        if family == "stair_bridge":
            vertical = math.floor(t * (steps + 1) * 0.5) * stair_step * 0.45
        if family == "vertical_lift_bridge":
            vertical = (t if t < 0.5 else (1 - t)) * vert_amp * 2.0
        if family == "hazard_chicane_bridge":
            lateral = wave * lat_amp * 0.65
        if family == "split_merge_bridge":
            lateral = math.sin(t * math.pi) * lat_amp * 0.8
        pos = {
            "x": a["x"] + (b["x"] - a["x"]) * t + right["x"] * lateral,
            "y": a["y"] + (b["y"] - a["y"]) * t + vertical,
            "z": a["z"] + (b["z"] - a["z"]) * t + right["z"] * lateral,
        }
        p = builder.add_platform(pos, size, edge_key, ["connector", family])
        if (
            family == "moving_shuttle_bridge"
            and steps > 2
            and i > 1
            and i < steps
            and rng.random() < moving_rate
        ):
            p["kind"] = "moving"
            p["motion"] = {
                "axis": "x" if abs(axis["x"]) >= abs(axis["z"]) else "z",
                "amplitude": clamp(1.2 + lat_amp * 0.4, 0.8, 2.6),
                "period": clamp(2.6 + rng.random() * 2.2, 1.4, 5.5),
                "phase": rng.random() * math.pi * 2,
            }
        if (
            family == "hazard_chicane_bridge"
            and i > 1
            and i < steps
            and rng.random() < hazard_density * 0.4
        ):
            patrol = {
                "from": {"x": pos["x"] - axis["x"] * 1.8, "y": pos["y"] + ENEMY_CLEARANCE_Y, "z": pos["z"] - axis["z"] * 1.8},
                "to": {"x": pos["x"] + axis["x"] * 1.8, "y": pos["y"] + ENEMY_CLEARANCE_Y, "z": pos["z"] + axis["z"] * 1.8},
            }
            builder.add_enemy(
                {"x": pos["x"], "y": pos["y"] + ENEMY_CLEARANCE_Y, "z": pos["z"]},
                patrol,
                edge_key,
                speed=1.0 + rng.random() * 1.2,
            )
        if entry is None:
            entry = dict(pos)
        last = dict(pos)
    return {"entry": entry or dict(a), "exit": last or dict(b)}


def build_lock_gate(
    node: dict[str, Any],
    entry: dict[str, float],
    heading: dict[str, float],
    builder: LevelBuilder,
    rng: Mulberry32,
    style: dict[str, Any] | None = None,
) -> dict[str, Any]:
    h = snap_heading_to_axis(heading)
    span = clamp(node.get("gate_span", LOCK_GATE_SPAN), 10, 60)
    width = clamp(node.get("gate_width", LOCK_GATE_WIDTH), 2.4, 12)
    height = clamp(node.get("gate_height", LOCK_GATE_HEIGHT), 3.5, 18)
    family = (style or {}).get("family", "center_gate")
    exit_pos = {"x": entry["x"] + h["x"] * span, "y": entry["y"], "z": entry["z"] + h["z"] * span}
    mid = {"x": (entry["x"] + exit_pos["x"]) * 0.5, "y": entry["y"], "z": (entry["z"] + exit_pos["z"]) * 0.5}
    corridor_size = {"x": span + 8, "y": 1, "z": width} if h["x"] != 0 else {"x": width, "y": 1, "z": span + 8}
    builder.add_platform(mid, corridor_size, node["id"], [NODE_TYPES["NONE"], "walkable", "lock_gate"])
    lock_size = {"x": 0.85, "y": height, "z": width + 1.6} if h["x"] != 0 else {"x": width + 1.6, "y": height, "z": 0.85}
    top_y = mid["y"] + corridor_size["y"] * 0.5
    side = {"x": -h["z"], "z": h["x"]}
    side_offset = width * 0.22 if family == "offset_gate" else 0.0
    lock_pos = {"x": mid["x"], "y": top_y + lock_size["y"] * 0.5, "z": mid["z"]}
    lock_pos["x"] += side["x"] * side_offset
    lock_pos["z"] += side["z"] * side_offset
    builder.add_lock(lock_pos, node.get("lock_id") or "L1", node.get("requires_key_id") or "K1", node["id"], lock_size)
    if family == "double_gate_hall":
        guard_pos = {"x": lock_pos["x"] + h["x"] * 2.4, "y": lock_pos["y"], "z": lock_pos["z"] + h["z"] * 2.4}
        patrol = {
            "from": {"x": guard_pos["x"] - side["x"] * 2.5, "y": guard_pos["y"] - lock_size["y"] * 0.5 + ENEMY_CLEARANCE_Y, "z": guard_pos["z"] - side["z"] * 2.5},
            "to": {"x": guard_pos["x"] + side["x"] * 2.5, "y": guard_pos["y"] - lock_size["y"] * 0.5 + ENEMY_CLEARANCE_Y, "z": guard_pos["z"] + side["z"] * 2.5},
        }
        builder.add_enemy(
            {"x": guard_pos["x"], "y": guard_pos["y"] - lock_size["y"] * 0.5 + ENEMY_CLEARANCE_Y, "z": guard_pos["z"]},
            patrol,
            node["id"],
            speed=1.25 + rng.random() * 0.4,
        )
    return {
        "entry": dict(entry),
        "exit": exit_pos,
        "heading": h,
        "gate": {
            "pos": lock_pos,
            "size": lock_size,
            "requires_key_id": node.get("requires_key_id") or "K1",
            "lock_id": node.get("lock_id") or "L1",
        },
    }

def build_node_chunk(
    node: dict[str, Any],
    entry: dict[str, float],
    heading: dict[str, float],
    rng: Mulberry32,
    builder: LevelBuilder,
    max_vertical: float,
    style: dict[str, Any] | None = None,
) -> dict[str, Any]:
    types = node.get("types") if isinstance(node.get("types"), list) and node.get("types") else ([node.get("type")] if node.get("type") else [NODE_TYPES["NONE"]])
    has = lambda t: t in types

    if has(NODE_TYPES["LOCK"]):
        return build_lock_gate(node, entry, heading, builder, rng, style)

    if has(NODE_TYPES["START"]):
        ground = NODE_TYPES["START"]
    elif has(NODE_TYPES["GOAL"]):
        ground = NODE_TYPES["GOAL"]
    elif has(NODE_TYPES["JUMP"]):
        ground = NODE_TYPES["JUMP"]
    elif has(NODE_TYPES["DROP"]):
        ground = NODE_TYPES["DROP"]
    elif has(NODE_TYPES["PLATFORM"]):
        ground = NODE_TYPES["PLATFORM"]
    else:
        ground = NODE_TYPES["NONE"]
    if bool((style or {}).get("safeGround", False)) and ground in {NODE_TYPES["JUMP"], NODE_TYPES["DROP"]}:
        ground = NODE_TYPES["PLATFORM"]

    intensity = clamp(float(node.get("intensity", 0.5)), 0.0, 1.0)
    family = (style or {}).get("family")
    challenge_scale = clamp(float((style or {}).get("challengeScale", 1.0)), 0.35, 1.4)
    count = clamp_int(2 + round(intensity * 4), 1, 10)
    gap = 2.2 + intensity * 1.8
    size = dict(PLATFORM_SIZE)
    tags = [ground]

    vertical_step = 0.0
    vertical_jitter = 0.0
    if ground in {NODE_TYPES["START"], NODE_TYPES["GOAL"], NODE_TYPES["NONE"]}:
        count = 1
        gap = 0
        size = {"x": 9, "y": 1, "z": 7}
        tags = [ground, "walkable"]
    elif ground == NODE_TYPES["PLATFORM"]:
        vertical_jitter = 0.05 + 0.15 * intensity
    elif ground == NODE_TYPES["JUMP"]:
        vertical_step = min(max_vertical, 0.7 + intensity * 2.0)
    elif ground == NODE_TYPES["DROP"]:
        vertical_step = -min(max_vertical, 0.7 + intensity * 2.0)

    if has(NODE_TYPES["ENEMY"]) and ground == NODE_TYPES["NONE"]:
        count = clamp_int(2 + round(intensity * 2), 2, 5)
        gap = 0.4
        size = {"x": 7, "y": 1, "z": 6}
    if (has(NODE_TYPES["KEY"]) or has(NODE_TYPES["LOCK"])) and ground == NODE_TYPES["NONE"]:
        count = 1
        gap = 0
        size = {"x": 8, "y": 1, "z": 6}

    if family in {"start_plaza", "goal_platform"}:
        count = 1
        gap = 0
        size = {"x": 11, "y": 1, "z": 9}
    elif family == "start_ramp":
        count = 3
        gap = 0.6
        size = {"x": 6.5, "y": 1, "z": 6.8}
        vertical_step = 0.5
    elif family == "goal_tower":
        count = 3
        gap = 0.9
        size = {"x": 6.5, "y": 1, "z": 6.5}
        vertical_step = 0.8
    elif family == "serpentine_room":
        count = clamp_int(count + 1, 2, 10)
        gap = clamp(gap * 0.6, 0.4, 3.0)
        vertical_jitter = max(vertical_jitter, 0.08)
    elif family == "dual_lane_room":
        count = clamp_int(count + 1, 2, 10)
        gap = clamp(gap * 0.7, 0.4, 3.2)
        size = {"x": size["x"] * 0.9, "y": size["y"], "z": size["z"] * 0.9}
    elif family == "arena_room":
        count = clamp_int(count, 1, 10)
        gap = clamp(gap * 0.4, 0.2, 2.2)
        size = {"x": 8.8, "y": 1, "z": 8.8}
    elif family == "gap_chain":
        count = clamp_int(count + 1, 3, 10)
        gap = clamp(gap * 1.35, 1.8, 4.6)
        size = {"x": 3.4, "y": 1, "z": 3.2}
        vertical_jitter = max(vertical_jitter, 0.1)
    elif family == "offset_islands":
        count = clamp_int(count + 1, 3, 10)
        gap = clamp(gap * 1.2, 1.6, 4.2)
        size = {"x": 3.8, "y": 1, "z": 3.6}
        vertical_jitter = max(vertical_jitter, 0.12)
    elif family == "ascending_jumps":
        count = clamp_int(count, 3, 10)
        gap = clamp(gap * 1.05, 1.2, 4.2)
        vertical_step = max(vertical_step, 0.65)
    elif family == "drop_well":
        count = clamp_int(count, 3, 10)
        gap = clamp(gap * 0.9, 1.0, 3.4)
        vertical_step = min(vertical_step if vertical_step != 0 else -0.65, -0.65)
    elif family == "stepped_drop":
        count = clamp_int(count, 3, 10)
        gap = clamp(gap * 0.8, 0.9, 3.2)
        vertical_step = min(vertical_step if vertical_step != 0 else -0.5, -0.5)
    elif family == "spiral_drop":
        count = clamp_int(count + 1, 3, 10)
        gap = clamp(gap * 0.85, 1.0, 3.3)
        vertical_step = min(vertical_step if vertical_step != 0 else -0.45, -0.45)
        vertical_jitter = max(vertical_jitter, 0.08)

    gap = max(0.0, gap * challenge_scale)
    if vertical_step != 0:
        vertical_step *= challenge_scale
    if vertical_jitter > 0:
        vertical_jitter *= challenge_scale

    fwd = normalize_heading(heading)
    step = size["x"] + max(0.0, gap)
    x, y, z = entry["x"], entry["y"], entry["z"]
    first = None
    last = None
    for i in range(count):
        pos = {"x": x, "y": y, "z": z}
        builder.add_platform(pos, size, node["id"], tags)
        if first is None:
            first = dict(pos)
        last = dict(pos)
        advance_x = fwd["x"] * step
        advance_z = fwd["z"] * step
        if family in {"dual_lane_room", "offset_islands", "spiral_drop"}:
            sway = ((1 if i % 2 == 0 else -1) * float((style or {}).get("scaleZ", 1.0))) * 2.0
            advance_x += (-fwd["z"]) * sway * 0.2
            advance_z += (fwd["x"]) * sway * 0.2
        x += advance_x
        z += advance_z
        if vertical_step != 0:
            y += vertical_step
        elif vertical_jitter > 0:
            y += rand_range(rng, -vertical_jitter, vertical_jitter)

    if has(NODE_TYPES["ENEMY"]):
        axis = normalize_heading({"x": last["x"] - first["x"], "z": last["z"] - first["z"]})
        mid = {"x": (first["x"] + last["x"]) * 0.5, "y": first["y"] + ENEMY_CLEARANCE_Y, "z": (first["z"] + last["z"]) * 0.5}
        enemy_boost = 2 if family == "cross_patrol" else 1 if family == "choke_guard" else 0
        n_enemy = clamp_int(1 + int(intensity * 3) + enemy_boost, 1, 6)
        patrol_len = 3.5 + intensity * 6.0
        for i in range(n_enemy):
            off = (i - (n_enemy - 1) / 2.0) * 1.2
            cx = mid["x"] + axis["x"] * off
            cz = mid["z"] + axis["z"] * off
            patrol = {
                "from": {"x": cx - axis["x"] * patrol_len * 0.5, "y": mid["y"], "z": cz - axis["z"] * patrol_len * 0.5},
                "to": {"x": cx + axis["x"] * patrol_len * 0.5, "y": mid["y"], "z": cz + axis["z"] * patrol_len * 0.5},
            }
            builder.add_enemy(
                {"x": cx, "y": mid["y"], "z": cz},
                patrol,
                node["id"],
                speed=1.0 + intensity * 2.5 + rng.random() * 0.4 + (0.4 if family == "choke_guard" else 0.0),
            )

    if has(NODE_TYPES["KEY"]):
        key_pos = (
            {"x": last["x"], "y": last["y"] + 1.1, "z": last["z"]}
            if family == "risk_key_room"
            else {"x": first["x"], "y": first["y"] + 1.0, "z": first["z"]}
        )
        builder.add_key(key_pos, node.get("key_id") or "K1", node["id"])
        if family == "timed_key_bridge":
            for p in reversed(builder.level["platforms"]):
                if p.get("node_id") == node["id"]:
                    p["kind"] = "moving"
                    p["motion"] = {
                        "axis": "z",
                        "amplitude": 1.8,
                        "period": 3.2 + rng.random() * 1.4,
                        "phase": rng.random() * math.pi * 2,
                    }
                    break

    return {"entry": first or dict(entry), "exit": last or dict(entry)}


def _assign_lock_ports_by_neighbors(level: dict[str, Any], edges: list[dict[str, Any]]) -> None:
    anchors = level.get("anchors") or {}
    neighbors: dict[str, set[str]] = {}
    for edge in edges:
        a = edge.get("from")
        b = edge.get("to")
        if not a or not b or a == b:
            continue
        neighbors.setdefault(str(a), set()).add(str(b))
        neighbors.setdefault(str(b), set()).add(str(a))

    def _anchor_point(node_id: str) -> dict[str, float] | None:
        anchor = anchors.get(node_id) or {}
        return anchor.get("entry") or anchor.get("exit")

    def _dist(a: dict[str, float], b: dict[str, float]) -> float:
        return math.hypot(float(a.get("x", 0.0)) - float(b.get("x", 0.0)), float(a.get("z", 0.0)) - float(b.get("z", 0.0)))

    for node_id, anchor in anchors.items():
        if not isinstance(anchor, dict) or not anchor.get("gate"):
            continue
        neigh = sorted(list(neighbors.get(str(node_id), set())))
        if len(neigh) < 2:
            continue
        entry = anchor.get("entry")
        exit_pos = anchor.get("exit")
        if not isinstance(entry, dict) or not isinstance(exit_pos, dict):
            continue
        left = neigh[0]
        right = neigh[1]
        left_pos = _anchor_point(left)
        right_pos = _anchor_point(right)
        if not isinstance(left_pos, dict) or not isinstance(right_pos, dict):
            continue
        keep_score = _dist(left_pos, entry) + _dist(right_pos, exit_pos)
        swap_score = _dist(left_pos, exit_pos) + _dist(right_pos, entry)
        if keep_score <= swap_score:
            anchor["portsByNeighbor"] = {left: dict(entry), right: dict(exit_pos)}
        else:
            anchor["portsByNeighbor"] = {left: dict(exit_pos), right: dict(entry)}


def _safe_edge_length(edge: dict[str, Any] | None) -> float:
    if not isinstance(edge, dict):
        return DEFAULT_EDGE_LENGTH
    return max(4.0, float(edge.get("length", DEFAULT_EDGE_LENGTH) or DEFAULT_EDGE_LENGTH))


def _build_etg_graph(edges: list[dict[str, Any]]) -> tuple[dict[str, list[tuple[str, str, float]]], dict[str, str]]:
    graph: dict[str, list[tuple[str, str, float]]] = {}
    best_edge_for_pair: dict[str, tuple[str, float]] = {}
    for edge in edges:
        edge_id = edge.get("id")
        a = edge.get("from")
        b = edge.get("to")
        if not edge_id or not a or not b or a == b:
            continue
        length = _safe_edge_length(edge)
        graph.setdefault(str(a), []).append((str(b), str(edge_id), length))
        graph.setdefault(str(b), [])
        pair_key = directed_pair_key(str(a), str(b))
        prev = best_edge_for_pair.get(pair_key)
        if prev is None or length < prev[1]:
            best_edge_for_pair[pair_key] = (str(edge_id), length)
    return graph, {k: v[0] for k, v in best_edge_for_pair.items()}


def _shortest_node_path(
    graph: dict[str, list[tuple[str, str, float]]],
    start_id: str,
    goal_id: str,
) -> list[str]:
    start = str(start_id)
    goal = str(goal_id)
    if start == goal:
        return [start]
    if start not in graph or goal not in graph:
        return []
    pq: list[tuple[float, str]] = [(0.0, start)]
    prev: dict[str, str | None] = {start: None}
    dist: dict[str, float] = {start: 0.0}
    while pq:
        cur_cost, cur = heapq.heappop(pq)
        if cur == goal:
            break
        if cur_cost > dist.get(cur, float("inf")):
            continue
        for nxt, _, w in graph.get(cur, []):
            cand = cur_cost + max(1.0, float(w))
            if cand + 1e-9 >= dist.get(nxt, float("inf")):
                continue
            dist[nxt] = cand
            prev[nxt] = cur
            heapq.heappush(pq, (cand, nxt))
    if goal not in prev:
        return []
    path: list[str] = []
    cur: str | None = goal
    while cur is not None:
        path.append(cur)
        cur = prev.get(cur)
    path.reverse()
    return path


def _path_length_by_graph(path: list[str], graph: dict[str, list[tuple[str, str, float]]]) -> float:
    total = 0.0
    for i in range(len(path) - 1):
        a = path[i]
        b = path[i + 1]
        w = next((float(length) for (nxt, _, length) in graph.get(a, []) if nxt == b), DEFAULT_EDGE_LENGTH)
        total += max(1.0, w)
    return total


def _required_key_lock_node_paths(
    etg: dict[str, Any],
    *,
    include_start_to_key: bool,
    max_extra_ratio: float | None = None,
) -> tuple[list[list[str]], set[str], set[str]]:
    nodes = [n for n in (etg.get("nodes") or []) if n.get("id")]
    edges = [e for e in (etg.get("edges") or []) if e]
    graph, _ = _build_etg_graph(edges)
    start_node = next((n for n in nodes if node_has_type(n, NODE_TYPES["START"])), None)
    start_id = str(start_node.get("id")) if start_node and start_node.get("id") else None
    key_node_by_key_id: dict[str, str] = {}
    for node in nodes:
        if not node_has_type(node, NODE_TYPES["KEY"]):
            continue
        key_id = node.get("key_id")
        if key_id and str(key_id) not in key_node_by_key_id:
            key_node_by_key_id[str(key_id)] = str(node["id"])

    canonical = compute_canonical_route(etg, {"defaultSpeed": (etg.get("meta") or {}).get("defaultSpeed")})
    canonical_len = float(canonical.get("totalLength", 0.0) or 0.0)
    max_allow_len = (
        canonical_len * (1.0 + max(0.0, float(max_extra_ratio)))
        if (canonical_len > 1e-6 and max_extra_ratio is not None)
        else None
    )

    paths: list[list[str]] = []
    required_key_nodes: set[str] = set()
    required_lock_nodes: set[str] = set()
    seen: set[tuple[str, ...]] = set()

    for lock in nodes:
        if not node_has_type(lock, NODE_TYPES["LOCK"]):
            continue
        req = lock.get("requires_key_id")
        if not req:
            continue
        lock_id = str(lock["id"])
        key_id = key_node_by_key_id.get(str(req))
        if not key_id:
            continue
        required_key_nodes.add(key_id)
        required_lock_nodes.add(lock_id)

        if include_start_to_key and start_id:
            p_start = _shortest_node_path(graph, start_id, key_id)
            if p_start:
                if max_allow_len is None or _path_length_by_graph(p_start, graph) <= max_allow_len:
                    key = tuple(p_start)
                    if key not in seen:
                        seen.add(key)
                        paths.append(p_start)
        p_key_lock = _shortest_node_path(graph, key_id, lock_id)
        if p_key_lock:
            key = tuple(p_key_lock)
            if key not in seen:
                seen.add(key)
                paths.append(p_key_lock)
    return paths, required_key_nodes, required_lock_nodes


def _node_safe_style(node: dict[str, Any], *, challenge_scale: float = 0.45) -> dict[str, Any]:
    style = {"challengeScale": clamp(float(challenge_scale), 0.35, 1.0), "safeGround": True}
    if node_has_type(node, NODE_TYPES["KEY"]):
        style["family"] = "safe_key_pocket"
    elif node_has_type(node, NODE_TYPES["LOCK"]):
        style["family"] = "center_gate"
    elif node_has_type(node, NODE_TYPES["GOAL"]):
        style["family"] = "goal_platform"
    elif node_has_type(node, NODE_TYPES["START"]):
        style["family"] = "start_plaza"
    else:
        style["family"] = "open_room"
    return style


def _builder_from_level(level: dict[str, Any]) -> LevelBuilder:
    return LevelBuilder(
        level,
        p=len(level.get("platforms") or []),
        e=len(level.get("enemies") or []),
        k=len(level.get("keys") or []),
        l=len(level.get("locks") or []),
        c=len(level.get("checkpoints") or []),
    )


def _anchor_port(level: dict[str, Any], node_id: str, neighbor_id: str, *, as_exit: bool) -> dict[str, float]:
    anchors = level.get("anchors") or {}
    anchor = anchors.get(node_id) or {}
    ports = anchor.get("portsByNeighbor")
    if isinstance(ports, dict) and neighbor_id in ports:
        return dict(ports[neighbor_id])
    fallback_key = "exit" if as_exit else "entry"
    fallback = anchor.get(fallback_key) or anchor.get("entry") or anchor.get("exit") or level.get("start") or {"x": 0.0, "y": 0.0, "z": 0.0}
    return dict(fallback)


def _materialize_edge_safe(
    *,
    level: dict[str, Any],
    builder: LevelBuilder,
    edge: dict[str, Any],
    node_by_id: dict[str, dict[str, Any]],
    from_id: str,
    to_id: str,
    rng: Mulberry32,
    max_vertical: float,
    segment_length: float,
    challenge_scale: float,
) -> bool:
    anchors = level.setdefault("anchors", {})
    if from_id not in anchors and to_id not in anchors:
        return False
    if from_id not in anchors and to_id in anchors:
        from_id, to_id = to_id, from_id
    if from_id not in anchors:
        return False

    from_exit = _anchor_port(level, from_id, to_id, as_exit=True)
    to_exists = to_id in anchors
    if to_exists:
        target = _anchor_port(level, to_id, from_id, as_exit=False)
        heading = normalize_heading({"x": target["x"] - from_exit["x"], "z": target["z"] - from_exit["z"]})
    else:
        base_heading = normalize_heading((anchors.get(from_id) or {}).get("heading") or {"x": 1.0, "z": 0.0})
        if abs(base_heading["x"]) + abs(base_heading["z"]) < 1e-6:
            base_heading = {"x": 1.0, "z": 0.0}
        heading = base_heading
        target = {
            "x": from_exit["x"] + heading["x"] * _safe_edge_length(edge),
            "y": from_exit["y"],
            "z": from_exit["z"] + heading["z"] * _safe_edge_length(edge),
        }

    connector_style = {
        "family": "linear_bridge",
        "lateralAmplitude": 0.30,
        "verticalAmplitude": 0.30,
        "zigzagPeriod": 5.6,
        "stairStep": 0.45,
        "movingRate": 0.0,
        "hazardDensity": 0.0,
    }
    con = add_connector(edge, from_exit, target, builder, rng, connector_style, segment_length=segment_length)
    level.setdefault("mapping", {}).setdefault("edge", {})[str(edge.get("id"))] = {
        "from": edge.get("from"),
        "to": edge.get("to"),
        "entry": dict(con.get("entry") or from_exit),
        "exit": dict(con.get("exit") or target),
        "constraints": {
            "length": _safe_edge_length(edge),
            "connector_family": "baseline_route_repair",
            "node_family": "baseline_route_repair",
        },
    }

    if not to_exists:
        node = node_by_id.get(to_id)
        if not node:
            return False
        style = _node_safe_style(node, challenge_scale=challenge_scale)
        chunk = build_node_chunk(node, target, heading, rng, builder, max_vertical, style)
        if node_has_type(node, NODE_TYPES["LOCK"]):
            level["anchors"][to_id] = {
                "entry": dict(chunk["entry"]),
                "exit": dict(chunk["exit"]),
                "heading": dict(chunk.get("heading") or heading),
                "portsByNeighbor": {},
                "gate": chunk.get("gate"),
            }
        else:
            level["anchors"][to_id] = {
                "entry": dict(chunk["entry"]),
                "exit": dict(chunk["exit"]),
                "heading": dict(chunk.get("heading") or heading),
            }
        if node_has_type(node, NODE_TYPES["GOAL"]):
            level["goal"] = dict(chunk["exit"])
    return True


def enforce_key_lock_route_coverage(
    level: dict[str, Any],
    etg: dict[str, Any],
    config: dict[str, Any],
    rng: Mulberry32 | None = None,
) -> dict[str, int]:
    enabled = bool(config.get("baselineKeyLockRoutePass", True))
    if not enabled:
        return {
            "required_key_path_repairs": 0,
            "missing_key_nodes_before_repair": 0,
            "missing_key_nodes_after_repair": 0,
        }
    nodes = [n for n in (etg.get("nodes") or []) if n.get("id")]
    edges = [e for e in (etg.get("edges") or []) if e.get("id")]
    if not nodes or not edges:
        return {
            "required_key_path_repairs": 0,
            "missing_key_nodes_before_repair": 0,
            "missing_key_nodes_after_repair": 0,
        }
    node_by_id = {str(n["id"]): n for n in nodes}
    edge_by_id = {str(e["id"]): e for e in edges}
    _, pair_to_edge = _build_etg_graph(edges)
    include_start_to_key = bool(config.get("baselineRequireKeyNodeCoverage", True))
    max_extra_ratio = config.get("laneKeyDetourMaxExtraRatio", None)
    paths, required_key_nodes, _ = _required_key_lock_node_paths(
        etg,
        include_start_to_key=include_start_to_key,
        max_extra_ratio=(float(max_extra_ratio) if max_extra_ratio is not None else None),
    )
    anchors = level.get("anchors") or {}
    missing_before = sum(1 for node_id in required_key_nodes if node_id not in anchors)
    if not paths:
        return {
            "required_key_path_repairs": 0,
            "missing_key_nodes_before_repair": missing_before,
            "missing_key_nodes_after_repair": missing_before,
        }

    budget_per_pair = clamp_int(config.get("baselineRouteRepairBudget", 3), 0, 12)
    total_budget = max(0, budget_per_pair * max(1, len(paths)))
    if total_budget <= 0:
        return {
            "required_key_path_repairs": 0,
            "missing_key_nodes_before_repair": missing_before,
            "missing_key_nodes_after_repair": sum(1 for node_id in required_key_nodes if node_id not in (level.get("anchors") or {})),
        }
    challenge_scale = clamp(float(config.get("baselineRepairChallengeScale", 0.45)), 0.35, 1.0)
    max_gap = clamp(float(config.get("baselineConnectivityBridgeMaxGap", 18.0)), 10.0, 42.0)
    segment_length = clamp(min(float(config.get("connectorSegmentLength", 6.0)), max_gap * 0.42), 3.4, 9.5)
    max_vertical = min(2.0, float(config.get("maxVerticalCap", 2.0)))
    builder = _builder_from_level(level)
    local_rng = rng or Mulberry32(1)

    mapping_edges = (level.get("mapping") or {}).setdefault("edge", {})
    repairs = 0
    for path in paths:
        for i in range(len(path) - 1):
            if repairs >= total_budget:
                break
            a = str(path[i])
            b = str(path[i + 1])
            edge_id = pair_to_edge.get(directed_pair_key(a, b))
            if not edge_id:
                continue
            if edge_id in mapping_edges:
                continue
            edge = edge_by_id.get(edge_id)
            if not edge:
                continue
            ok = _materialize_edge_safe(
                level=level,
                builder=builder,
                edge=edge,
                node_by_id=node_by_id,
                from_id=a,
                to_id=b,
                rng=local_rng,
                max_vertical=max_vertical,
                segment_length=segment_length,
                challenge_scale=challenge_scale,
            )
            if ok:
                repairs += 1
        if repairs >= total_budget:
            break

    _assign_lock_ports_by_neighbors(level, edges)
    anchors_after = level.get("anchors") or {}
    missing_after = sum(1 for node_id in required_key_nodes if node_id not in anchors_after)
    stats = (((level.get("meta") or {}).get("component_generation") or {}).get("selection_stats") or {})
    stats["required_key_path_repairs"] = int(stats.get("required_key_path_repairs", 0)) + int(repairs)
    stats["missing_key_nodes_before_repair"] = int(stats.get("missing_key_nodes_before_repair", 0)) + int(missing_before)
    stats["missing_key_nodes_after_repair"] = int(stats.get("missing_key_nodes_after_repair", 0)) + int(missing_after)
    return {
        "required_key_path_repairs": int(repairs),
        "missing_key_nodes_before_repair": int(missing_before),
        "missing_key_nodes_after_repair": int(missing_after),
    }


def lane_allocator() -> Callable[[], int]:
    state = {"k": 1, "sign": 1}
    def alloc() -> int:
        out = state["sign"] * state["k"]
        if state["sign"] == 1:
            state["sign"] = -1
        else:
            state["sign"] = 1
            state["k"] += 1
        return out
    return alloc


def assign_canonical_lanes(c_nodes: list[dict[str, Any]], lane_by_node: dict[str, int], alloc: Callable[[], int]) -> None:
    first_idx: dict[str, int] = {}
    for i, n in enumerate(c_nodes):
        nid = n.get("id")
        if not nid:
            continue
        if nid not in first_idx:
            first_idx[nid] = i
            lane_by_node[nid] = 0
            continue
        lane = alloc()
        for j in range(first_idx[nid] + 1, i):
            mid = c_nodes[j].get("id")
            if mid and lane_by_node.get(mid, 0) == 0:
                lane_by_node[mid] = lane


def generate_level_lane(etg: dict[str, Any], config: dict[str, Any], rng: Mulberry32) -> dict[str, Any]:
    level, builder = make_level(etg, config, "lane")
    difficulty = float(config.get("difficulty", 0.5))
    lane_safe_mode = bool(config.get("laneSafeMode", False))
    lane_spacing = clamp(float(config.get("laneSpacing", 16.0 if lane_safe_mode else 22.0)), 10.0, 28.0)
    max_vertical = clamp(
        float(config.get("laneMaxVertical", config.get("maxVerticalCap", (1.8 if lane_safe_mode else (2.6 + difficulty * 0.6))))),
        0.8,
        3.8,
    )
    lane_force_key_detour = bool(config.get("laneForceKeyDetour", False))
    lane_ensure_required_key_paths = bool(config.get("laneEnsureRequiredKeyPaths", True))
    lane_key_detour_max_extra_ratio = clamp(float(config.get("laneKeyDetourMaxExtraRatio", 0.35)), 0.0, 1.2)
    lane_branch_attach_max_gap = clamp(float(config.get("laneBranchAttachMaxGap", 16.0)), 8.0, 40.0)
    include_branches = bool(config.get("laneIncludeBranches", True)) or lane_force_key_detour
    connector_segment_length = clamp(float(config.get("laneConnectorSegmentLength", 5.0 if lane_safe_mode else 6.0)), 3.0, 9.0)
    lane_safe_linear_connectors = bool(config.get("laneSafeLinearConnectors", True))
    safe_lane_connector_style = None
    if lane_safe_mode and lane_safe_linear_connectors:
        safe_lane_connector_style = {
            "family": "linear_bridge",
            "lateralAmplitude": 0.2,
            "verticalAmplitude": 0.2,
            "zigzagPeriod": 6.2,
            "stairStep": 0.35,
            "movingRate": 0.0,
            "hazardDensity": 0.0,
        }

    nodes = etg.get("nodes") or []
    edges = etg.get("edges") or []
    node_by_id = {n.get("id"): n for n in nodes if n.get("id")}
    edge_by_id = {e.get("id"): e for e in edges if e.get("id")}

    canonical = compute_canonical_route(etg, {"defaultSpeed": (etg.get("meta") or {}).get("defaultSpeed")})
    level["meta"]["canonical"] = {
        "ok": bool(canonical.get("ok")),
        "totalLength": canonical.get("totalLength", 0.0),
        "totalEtaSeconds": canonical.get("totalEtaSeconds", 0.0),
        "nodes": list(canonical.get("nodes") or []),
        "edges": list(canonical.get("edges") or []),
        "defaultSpeed": canonical.get("defaultSpeed"),
        "reason": canonical.get("reason"),
    }

    if not canonical.get("ok"):
        s = next((n for n in nodes if node_has_type(n, NODE_TYPES["START"])), None) or {"id": "Start", "type": NODE_TYPES["START"], "intensity": 0.1}
        p = builder.add_platform({"x": 0, "y": 0, "z": 0}, PLATFORM_SIZE, s["id"], [NODE_TYPES["START"]])
        level["anchors"][s["id"]] = {"entry": dict(p["pos"]), "exit": dict(p["pos"]), "heading": {"x": 1, "z": 0}}
        level["start"] = dict(p["pos"])
        level["goal"] = {"x": p["pos"]["x"] + 12, "y": p["pos"]["y"], "z": p["pos"]["z"]}
        return level

    c_nodes = [node_by_id[nid] for nid in canonical.get("nodes") if nid in node_by_id]
    c_edges = [edge_by_id[eid] for eid in canonical.get("edges") if eid in edge_by_id]
    built = set()
    lane_by_node: dict[str, int] = {}
    assign_canonical_lanes(c_nodes, lane_by_node, lane_allocator())
    cursor = {"x": 0.0, "y": 0.0, "z": 0.0}
    fwd = {"x": 1, "z": 0}

    for i, node in enumerate(c_nodes):
        lane = lane_by_node.get(node["id"], 0)
        arrival = {"x": cursor["x"], "y": cursor["y"], "z": lane * lane_spacing}
        if node["id"] not in built:
            style = None
            if lane_safe_mode:
                style = {"challengeScale": 0.5, "safeGround": True}
                if node_has_type(node, NODE_TYPES["KEY"]):
                    style["family"] = "safe_key_pocket"
                elif node_has_type(node, NODE_TYPES["LOCK"]):
                    style["family"] = "center_gate"
                elif node_has_type(node, NODE_TYPES["GOAL"]):
                    style["family"] = "goal_platform"
                else:
                    style["family"] = "open_room"
            chunk = build_node_chunk(node, arrival, fwd, rng, builder, max_vertical, style)
            level["anchors"][node["id"]] = {"entry": chunk["entry"], "exit": chunk["exit"], "heading": dict(fwd)}
            built.add(node["id"])
            if node_has_type(node, NODE_TYPES["START"]):
                level["start"] = dict(chunk["entry"])
            if node_has_type(node, NODE_TYPES["GOAL"]):
                level["goal"] = dict(chunk["exit"])
            cursor = dict(chunk["exit"])
        else:
            cursor = dict(level["anchors"][node["id"]]["exit"])

        if i >= len(c_edges) or i + 1 >= len(c_nodes):
            continue
        edge = c_edges[i]
        nxt = c_nodes[i + 1]
        l_next = lane_by_node.get(nxt["id"], 0)
        target_z = l_next * lane_spacing
        target = dict(level["anchors"][nxt["id"]]["entry"]) if nxt["id"] in built else {
            "x": cursor["x"] + float(edge.get("length", DEFAULT_EDGE_LENGTH)),
            "y": cursor["y"],
            "z": target_z,
        }
        con = add_connector(edge, cursor, target, builder, rng, safe_lane_connector_style, segment_length=connector_segment_length)
        level["mapping"]["edge"][edge["id"]] = {"from": edge["from"], "to": edge["to"], "entry": con["entry"], "exit": con["exit"], "constraints": {"length": float(edge.get("length", DEFAULT_EDGE_LENGTH))}}
        cursor = dict(target)

    build_all_remaining = include_branches
    remaining = [e for e in edges if e and e.get("id") not in level["mapping"]["edge"]] if build_all_remaining else []
    if lane_ensure_required_key_paths:
        _, pair_to_edge = _build_etg_graph(edges)
        required_paths, _, _ = _required_key_lock_node_paths(
            etg,
            include_start_to_key=True,
            max_extra_ratio=lane_key_detour_max_extra_ratio,
        )
        required_edge_ids: set[str] = set()
        for path in required_paths:
            for i in range(len(path) - 1):
                eid = pair_to_edge.get(directed_pair_key(str(path[i]), str(path[i + 1])))
                if eid:
                    required_edge_ids.add(str(eid))
        for edge in edges:
            edge_id = str(edge.get("id") or "")
            if not edge_id or edge_id in level["mapping"]["edge"] or edge_id not in required_edge_ids:
                continue
            if edge not in remaining:
                remaining.append(edge)
    if lane_force_key_detour and remaining:
        key_nodes = {str(n.get("id")) for n in nodes if node_has_type(n, NODE_TYPES["KEY"]) and n.get("id")}
        lock_nodes = {str(n.get("id")) for n in nodes if node_has_type(n, NODE_TYPES["LOCK"]) and n.get("id")}

        def _edge_priority(item: dict[str, Any]) -> tuple[int, float]:
            a = str(item.get("from"))
            b = str(item.get("to"))
            if a in key_nodes or b in key_nodes:
                return (0, float(item.get("length", DEFAULT_EDGE_LENGTH)))
            if a in lock_nodes or b in lock_nodes:
                return (2, float(item.get("length", DEFAULT_EDGE_LENGTH)))
            return (1, float(item.get("length", DEFAULT_EDGE_LENGTH)))

        remaining = sorted(remaining, key=_edge_priority)
    for edge in remaining:
        a = node_by_id.get(edge.get("from"))
        b = node_by_id.get(edge.get("to"))
        if not a or not b or a["id"] not in built:
            continue
        from_exit = level["anchors"][a["id"]]["exit"]
        lane_a = lane_by_node.get(a["id"], 0)
        lane_b = lane_by_node.get(b["id"], lane_a + 1)
        max_lane_delta = max(1, int(round(lane_branch_attach_max_gap / max(1.0, lane_spacing))))
        lane_b = max(lane_a - max_lane_delta, min(lane_a + max_lane_delta, lane_b))
        lane_by_node[b["id"]] = lane_b
        target = dict(level["anchors"][b["id"]]["entry"]) if b["id"] in built else {
            "x": from_exit["x"] + float(edge.get("length", DEFAULT_EDGE_LENGTH)),
            "y": from_exit["y"],
            "z": lane_b * lane_spacing,
        }
        con = add_connector(edge, from_exit, target, builder, rng, safe_lane_connector_style, segment_length=connector_segment_length)
        level["mapping"]["edge"][edge["id"]] = {"from": edge["from"], "to": edge["to"], "entry": con["entry"], "exit": con["exit"], "constraints": {"length": float(edge.get("length", DEFAULT_EDGE_LENGTH))}}
        if b["id"] not in built:
            style = None
            if lane_safe_mode:
                style = {"challengeScale": 0.5, "safeGround": True}
                if node_has_type(b, NODE_TYPES["KEY"]):
                    style["family"] = "safe_key_pocket"
                elif node_has_type(b, NODE_TYPES["LOCK"]):
                    style["family"] = "center_gate"
                elif node_has_type(b, NODE_TYPES["GOAL"]):
                    style["family"] = "goal_platform"
                else:
                    style["family"] = "open_room"
            chunk = build_node_chunk(b, target, fwd, rng, builder, max_vertical, style)
            level["anchors"][b["id"]] = {"entry": chunk["entry"], "exit": chunk["exit"], "heading": dict(fwd)}
            built.add(b["id"])
            if node_has_type(b, NODE_TYPES["GOAL"]):
                level["goal"] = dict(chunk["exit"])

    _assign_lock_ports_by_neighbors(level, edges)
    if lane_safe_mode and bool(config.get("laneDisableDynamicHazards", True)):
        for platform in level.get("platforms") or []:
            if platform.get("kind") == "moving":
                platform["kind"] = "static"
                platform["motion"] = None
        if bool(config.get("laneClearEnemiesInSafeMode", True)):
            level["enemies"] = []
            node_map = (level.get("mapping") or {}).get("node") or {}
            for node_rec in node_map.values():
                if isinstance(node_rec, dict):
                    node_rec["enemies"] = []
    if not level.get("goal") and level.get("start"):
        level["goal"] = {"x": level["start"]["x"] + 12, "y": level["start"]["y"], "z": level["start"]["z"]}
    return level


def _near(a: dict[str, float], b: dict[str, float], margin: float) -> bool:
    return math.hypot(a["x"] - b["x"], a["z"] - b["z"]) < margin


def _collect_bounds_delta(platforms: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, float]]]:
    out: dict[str, dict[str, dict[str, float]]] = {}
    for p in platforms:
        node_id = p.get("node_id")
        if not node_id:
            continue
        if node_id not in out:
            out[node_id] = {
                "min": {"x": float("inf"), "y": float("inf"), "z": float("inf")},
                "max": {"x": float("-inf"), "y": float("-inf"), "z": float("-inf")},
            }
        b = out[node_id]
        half_x = float(p["size"]["x"]) * 0.5
        half_y = float(p["size"]["y"]) * 0.5
        half_z = float(p["size"]["z"]) * 0.5
        b["min"]["x"] = min(b["min"]["x"], float(p["pos"]["x"]) - half_x)
        b["max"]["x"] = max(b["max"]["x"], float(p["pos"]["x"]) + half_x)
        b["min"]["y"] = min(b["min"]["y"], float(p["pos"]["y"]) - half_y)
        b["max"]["y"] = max(b["max"]["y"], float(p["pos"]["y"]) + half_y)
        b["min"]["z"] = min(b["min"]["z"], float(p["pos"]["z"]) - half_z)
        b["max"]["z"] = max(b["max"]["z"], float(p["pos"]["z"]) + half_z)
    return out


def _merge_bounds(a: dict[str, dict[str, float]] | None, b: dict[str, dict[str, float]] | None) -> dict[str, dict[str, float]] | None:
    if a is None:
        return b
    if b is None:
        return a
    return {
        "min": {
            "x": min(float(a["min"]["x"]), float(b["min"]["x"])),
            "y": min(float(a["min"]["y"]), float(b["min"]["y"])),
            "z": min(float(a["min"]["z"]), float(b["min"]["z"])),
        },
        "max": {
            "x": max(float(a["max"]["x"]), float(b["max"]["x"])),
            "y": max(float(a["max"]["y"]), float(b["max"]["y"])),
            "z": max(float(a["max"]["z"]), float(b["max"]["z"])),
        },
    }


def _aabb_distance(a: dict[str, dict[str, float]], b: dict[str, dict[str, float]]) -> float:
    dx = max(0.0, max(float(b["min"]["x"]) - float(a["max"]["x"]), float(a["min"]["x"]) - float(b["max"]["x"])))
    dy = max(0.0, max(float(b["min"]["y"]) - float(a["max"]["y"]), float(a["min"]["y"]) - float(b["max"]["y"])))
    dz = max(0.0, max(float(b["min"]["z"]) - float(a["max"]["z"]), float(a["min"]["z"]) - float(b["max"]["z"])))
    return math.hypot(dx, math.hypot(dy, dz))


def _evaluate_safety_margin(
    level: dict[str, Any],
    snapshot: dict[str, Any],
    node_bounds: dict[str, dict[str, dict[str, float]]],
    connector_node_id: str,
    connector_touch_nodes: set[str],
    safety_margin: float,
) -> dict[str, Any]:
    new_platforms = level["platforms"][snapshot["p"] :]
    new_bounds_by_node = _collect_bounds_delta(new_platforms)
    proposed_bounds: dict[str, dict[str, dict[str, float]]] = {}
    for node_id, bounds in new_bounds_by_node.items():
        existing = node_bounds.get(node_id)
        proposed_bounds[node_id] = _merge_bounds(existing, bounds) or bounds

    for node_id, bounds in proposed_bounds.items():
        for other_id, other_bounds in node_bounds.items():
            if other_id == node_id:
                continue
            if (
                (node_id == connector_node_id and other_id in connector_touch_nodes)
                or (other_id == connector_node_id and node_id in connector_touch_nodes)
            ):
                continue
            compare = proposed_bounds.get(other_id, other_bounds)
            if _aabb_distance(bounds, compare) < safety_margin:
                return {"ok": False}

    entries = list(proposed_bounds.items())
    for i in range(len(entries)):
        node_id, bounds = entries[i]
        for j in range(i + 1, len(entries)):
            other_id, other_bounds = entries[j]
            if node_id == other_id:
                continue
            if (
                (node_id == connector_node_id and other_id in connector_touch_nodes)
                or (other_id == connector_node_id and node_id in connector_touch_nodes)
            ):
                continue
            if _aabb_distance(bounds, other_bounds) < safety_margin:
                return {"ok": False}

    return {
        "ok": True,
        "proposed_bounds": proposed_bounds,
        "delta_bounds": new_bounds_by_node,
    }


def generate_level_incremental(
    etg: dict[str, Any],
    config: dict[str, Any],
    rng: Mulberry32,
    validate_local_placement: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    mode_name: str = "hdpcg_incremental",
) -> dict[str, Any]:
    level, builder = make_level(etg, config, mode_name)
    is_main_mode = str(mode_name or "").strip() in {"hdpcg_incremental", "incremental"}
    difficulty = float(config.get("difficulty", 0.5))
    max_vertical = 2.6 + difficulty * 0.6
    max_vertical = min(max_vertical, float(config.get("maxVerticalCap", max_vertical)))
    heading_jitter = float(config.get("headingJitterRange", 0.35))
    lateral_jitter_min = float(config.get("lateralJitterMin", 1.0))
    lateral_jitter_max = float(config.get("lateralJitterMax", 2.2))
    if lateral_jitter_max < lateral_jitter_min:
        lateral_jitter_min, lateral_jitter_max = lateral_jitter_max, lateral_jitter_min
    component_strategy = str(config.get("componentStrategy", "diverse")).strip() or "diverse"
    use_diverse_strategy = component_strategy != "legacy"
    candidate_pool_size = clamp_int(config.get("candidatePoolSize", 12), 1, 48)
    selection_top_p = clamp(float(config.get("selectionTopP", 0.70)), 0.05, 1.0)
    selection_temperature = clamp(float(config.get("selectionTemperature", 0.80)), 0.05, 4.0)
    max_local_rejects = clamp_int(config.get("maxLocalRejects", 24), 1, 120)
    fallback_enabled = bool(config.get("fallbackEnabled", True))
    canonical_linear_mode = bool(config.get("canonicalLinearMode", False))
    family_balance_window = clamp_int(config.get("familyBalanceWindow", 40), 4, 200)
    connector_segment_length = clamp(float(config.get("connectorSegmentLength", 6.0)), 2.5, 14.0)
    disallow_connector_families = {str(v) for v in (config.get("disallowConnectorFamilies") or []) if v}
    disallow_node_families = {str(v) for v in (config.get("disallowNodeFamilies") or []) if v}
    raw_max_candidate_complexity = config.get("maxCandidateComplexity")
    max_candidate_complexity = (
        None
        if raw_max_candidate_complexity is None
        else clamp(float(raw_max_candidate_complexity), 0.2, 2.0)
    )
    key_lock_precheck_mode = str(config.get("keyLockPrecheckMode", "all")).strip().lower()
    if key_lock_precheck_mode not in {"all", "main_only", "off"}:
        key_lock_precheck_mode = "all"
    main_canonical_safe_mode = bool(config.get("mainCanonicalSafeMode", is_main_mode))
    main_canonical_max_complexity = clamp(float(config.get("mainCanonicalMaxComplexity", 0.55)), 0.2, 2.0)
    main_canonical_force_legacy_on_fail = bool(config.get("mainCanonicalForceLegacyOnFail", True))
    main_post_edge_repair = bool(config.get("mainPostEdgeRepair", True))
    main_key_lock_precheck = bool(config.get("mainKeyLockPrecheck", True))
    main_limit_dynamic_on_canonical = bool(config.get("mainLimitDynamicOnCanonical", True))
    baseline_canonical_safe_mode = bool(config.get("baselineCanonicalSafeMode", not is_main_mode))
    baseline_canonical_max_complexity = clamp(float(config.get("baselineCanonicalMaxComplexity", 0.72)), 0.2, 2.0)
    baseline_limit_dynamic_on_canonical = bool(config.get("baselineLimitDynamicOnCanonical", True))
    main_canonical_jitter_scale = clamp(float(config.get("mainCanonicalJitterScale", 0.45)), 0.0, 1.0)
    baseline_canonical_jitter_scale = clamp(float(config.get("baselineCanonicalJitterScale", 0.55)), 0.0, 1.0)
    main_canonical_challenge_scale = clamp(float(config.get("mainCanonicalChallengeScale", 0.5)), 0.35, 1.4)
    baseline_canonical_challenge_scale = clamp(float(config.get("baselineCanonicalChallengeScale", 0.45)), 0.35, 1.4)
    main_spine_first_mode = bool(config.get("mainSpineFirstMode", True)) if is_main_mode else False
    main_spine_repair_budget = clamp_int(config.get("mainSpineRepairBudget", 6), 0, 48)
    main_spine_max_detour = clamp(float(config.get("mainSpineMaxDetour", 0.18)), 0.0, 0.65)
    main_spine_edge_segment_length = clamp(float(config.get("mainSpineEdgeSegmentLength", 5.2)), 2.5, 14.0)
    main_spine_safe_ground = bool(config.get("mainSpineSafeGround", True))
    main_spine_local_check_stride = clamp_int(config.get("mainSpineLocalCheckStride", 1), 1, 8)
    main_spine_rollback_on_fail = bool(config.get("mainSpineRollbackOnFail", True))
    main_infill_skip_local_validation = bool(config.get("mainInfillSkipLocalValidation", True))
    main_spine_forced_linear_per_edge_cap = clamp_int(config.get("mainSpineForcedLinearPerEdgeCap", 2), 0, 12)
    main_canonical_validation_scale = clamp(
        float(config.get("mainCanonicalValidationScale", config.get("mainLocalValidationScaleCanonical", 0.55))),
        0.15,
        1.0,
    )
    main_infill_validation_scale = clamp(
        float(config.get("mainInfillValidationScale", config.get("mainLocalValidationScaleInfill", 0.35))),
        0.15,
        1.0,
    )
    main_validation_min_time = clamp_int(config.get("mainValidationMinTime", 12), 10, 180)
    main_validation_min_states = clamp_int(config.get("mainValidationMinStates", 4500), 3_000, 180_000)
    main_validation_min_queue = clamp_int(config.get("mainValidationMinQueue", 4000), 2_500, 180_000)
    main_validation_min_jump_offsets = clamp_int(config.get("mainValidationMinJumpOffsets", 100), 80, 2400)
    main_infill_max_complexity = clamp(float(config.get("mainInfillMaxComplexity", 0.82)), 0.2, 2.0)
    main_infill_diversity_target = clamp(float(config.get("mainInfillDiversityTarget", 0.34)), 0.05, 0.95)
    main_infill_family_min_count = clamp_int(config.get("mainInfillFamilyMinCount", 5), 1, 24)
    main_infill_max_per_node = clamp_int(config.get("mainInfillMaxPerNode", 2), 1, 8)
    main_infill_coverage_min_ratio = clamp(float(config.get("mainInfillCoverageMinRatio", 0.35)), 0.0, 1.0)
    main_infill_coverage_pass = bool(config.get("mainInfillCoveragePass", True))
    if is_main_mode:
        main_spine_local_check_stride = 1
        main_infill_skip_local_validation = False
    main_quick_hard_fail_reasons_raw = config.get("mainQuickHardFailReasons") or [
        "forbidden_reached",
        "target_not_reachable",
        "lock_gate_leak_no_key",
        "lock_gate_blocks_with_all_keys",
        "lock_bypassed_between_neighbors_no_key",
        "lock_still_blocks_between_neighbors_with_all_keys",
        "missing_anchors",
        "no_walkable_marker",
    ]
    main_quick_hard_fail_reasons = {str(v) for v in main_quick_hard_fail_reasons_raw if v}
    main_quick_treat_budget_as_hard_fail = bool(config.get("mainQuickTreatBudgetAsHardFail", False))
    safe_connector_raw = config.get("mainCanonicalSafeConnectors") or ["linear_bridge", "stair_bridge", "arc_bridge"]
    safe_node_raw = config.get("mainCanonicalSafeNodeFamilies") or [
        "start_plaza",
        "start_ramp",
        "goal_platform",
        "open_room",
        "serpentine_room",
        "safe_key_pocket",
        "center_gate",
        "gap_chain",
        "drop_well",
        "checkpoint_pocket",
    ]
    baseline_safe_connector_raw = config.get("baselineCanonicalSafeConnectors") or [
        "linear_bridge",
        "stair_bridge",
        "arc_bridge",
        "zigzag_bridge",
    ]
    baseline_safe_node_raw = config.get("baselineCanonicalSafeNodeFamilies") or [
        "start_plaza",
        "start_ramp",
        "goal_platform",
        "open_room",
        "serpentine_room",
        "safe_key_pocket",
        "center_gate",
        "gap_chain",
        "drop_well",
        "checkpoint_pocket",
    ]
    main_safe_connectors = {str(v) for v in safe_connector_raw if v}
    main_safe_node_families = {str(v) for v in safe_node_raw if v}
    baseline_safe_connectors = {str(v) for v in baseline_safe_connector_raw if v}
    baseline_safe_node_families = {str(v) for v in baseline_safe_node_raw if v}
    main_score_weights = {
        "alignmentWeight": config.get("mainCanonicalAlignmentWeight", config.get("alignmentWeight", 0.35)),
        "playabilityWeight": config.get("mainCanonicalPlayabilityWeight", config.get("playabilityWeight", 0.30)),
        "noveltyWeight": config.get("mainCanonicalNoveltyWeight", config.get("noveltyWeight", 0.20)),
        "shapeWeight": config.get("mainCanonicalShapeWeight", config.get("shapeWeight", 0.15)),
        "riskWeight": config.get("mainCanonicalRiskWeight", config.get("riskWeight", 0.20)),
    }
    apply_key_lock_precheck = (
        key_lock_precheck_mode == "all"
        or (key_lock_precheck_mode == "main_only" and is_main_mode)
    )
    if is_main_mode and (not main_key_lock_precheck):
        apply_key_lock_precheck = False
    component_meta = (level.setdefault("meta", {})).setdefault("component_generation", {})
    family_usage = component_meta.get("family_usage")
    if not isinstance(family_usage, dict):
        family_usage = {}
        component_meta["family_usage"] = family_usage
    selection_stats = component_meta.get("selection_stats")
    if not isinstance(selection_stats, dict):
        selection_stats = {}
        component_meta["selection_stats"] = selection_stats
    recent_family_window: list[str] = []
    main_infill_family_usage: dict[str, int] = {}
    main_infill_unique_families: set[str] = set()

    nodes = etg.get("nodes") or []
    edges = [e for e in (etg.get("edges") or []) if e]
    node_by_id = {n.get("id"): n for n in nodes if n.get("id")}
    edge_by_id = {e.get("id"): e for e in edges if e.get("id")}
    neighbors_by_node: dict[str, set[str]] = {}
    for e in edges:
        a, b = e.get("from"), e.get("to")
        if a and b and a != b:
            neighbors_by_node.setdefault(a, set()).add(b)
            neighbors_by_node.setdefault(b, set()).add(a)

    canonical = compute_canonical_route(etg, {"defaultSpeed": (etg.get("meta") or {}).get("defaultSpeed")})
    level["meta"]["canonical"] = {
        "ok": bool(canonical.get("ok")),
        "totalLength": canonical.get("totalLength", 0.0),
        "totalEtaSeconds": canonical.get("totalEtaSeconds", 0.0),
        "nodes": list(canonical.get("nodes") or []),
        "edges": list(canonical.get("edges") or []),
        "defaultSpeed": canonical.get("defaultSpeed"),
        "reason": canonical.get("reason"),
    }
    canonical_edges_order = list(canonical.get("edges") or []) if canonical.get("ok") else []
    canonical_edge_set = set(canonical_edges_order)
    noncanonical_edge_set = {str(e.get("id")) for e in edges if e.get("id") and str(e.get("id")) not in canonical_edge_set}
    canonical_edge_rank = {edge_id: idx for idx, edge_id in enumerate(canonical_edges_order)}
    baseline_build_required_edges_only = (not is_main_mode) and bool(config.get("baselineBuildRequiredEdgesOnly", True))
    baseline_required_edge_set: set[str] = set()
    if baseline_build_required_edges_only:
        _, pair_to_edge = _build_etg_graph(edges)
        required_paths, _, _ = _required_key_lock_node_paths(
            etg,
            include_start_to_key=bool(config.get("baselineRequireKeyNodeCoverage", True)),
            max_extra_ratio=float(config.get("baselineKeyDetourMaxExtraRatio", 0.45)),
        )
        for path in required_paths:
            for i in range(len(path) - 1):
                eid = pair_to_edge.get(directed_pair_key(str(path[i]), str(path[i + 1])))
                if eid:
                    baseline_required_edge_set.add(str(eid))
    canonical_total_length = float(canonical.get("totalLength", 0.0) or 0.0)
    canonical_edge_detour_cap = (
        (canonical_total_length * main_spine_max_detour) / max(1, len(canonical_edges_order))
        if canonical_edges_order
        else 0.0
    )

    start = next((n for n in nodes if node_has_type(n, NODE_TYPES["START"])), None) or (nodes[0] if nodes else {"id": "Start", "types": [NODE_TYPES["START"]], "intensity": 0.1})
    root = build_node_chunk(start, {"x": 0, "y": 0, "z": 0}, {"x": 1, "z": 0}, rng, builder, max_vertical)
    level["anchors"][start["id"]] = {"entry": root["entry"], "exit": root["exit"], "heading": {"x": 1, "z": 0}}
    level["start"] = dict(root["entry"])

    placed = {
        start["id"]: {
            "entry": root["entry"],
            "exit": root["exit"],
            "outgoing": 0,
            "used": set(),
            "sector_shift": int(math.floor(rng.random() * 1000000.0)) % 9973,
            "base_angle": rng.random() * math.pi * 2,
            "portsByNeighbor": None,
        }
    }
    node_bounds: dict[str, dict[str, dict[str, float]]] = {}
    start_bounds = _collect_bounds_delta([p for p in level["platforms"] if p.get("node_id") == start["id"]])
    if start_bounds.get(start["id"]):
        node_bounds[start["id"]] = start_bounds[start["id"]]
    built_edges = set()
    built_undirected: dict[str, str] = {}
    spine_failure_counts: dict[str, int] = {}
    spine_forced_linear_counts: dict[str, int] = {}
    noncanonical_edge_count_by_node: dict[str, int] = {}
    spine_wait_cycles = 0
    spine_local_checks = 0
    key_node_by_key_id: dict[str, str] = {}
    for node in nodes:
        if not node_has_type(node, NODE_TYPES["KEY"]):
            continue
        key_id = node.get("key_id")
        node_id = node.get("id")
        if key_id and node_id and key_id not in key_node_by_key_id:
            key_node_by_key_id[str(key_id)] = str(node_id)

    frontier: list[dict[str, Any]] = []
    frontier_keys: set[str] = set()

    def add_frontier(
        edge_id: str,
        from_id: str,
        to_id: str,
        fail_count: int = 0,
        *,
        canonical: bool | None = None,
        relaxed_local: bool = False,
        force_legacy: bool = False,
        spine_repair: bool = False,
    ) -> None:
        if not edge_id or edge_id in built_edges:
            return
        key = f"{edge_id}|{from_id}"
        if key in frontier_keys:
            return
        frontier_keys.add(key)
        frontier.append(
            {
                "edge_id": edge_id,
                "from_id": from_id,
                "to_id": to_id,
                "canonical": (edge_id in canonical_edge_set) if canonical is None else bool(canonical),
                "fail_count": int(fail_count),
                "relaxed_local": bool(relaxed_local),
                "force_legacy": bool(force_legacy),
                "spine_repair": bool(spine_repair),
            }
        )

    def push_frontier_for_node(_: str) -> None:
        for e in edges:
            edge_id = e.get("id")
            if not edge_id or edge_id in built_edges:
                continue
            if baseline_build_required_edges_only and edge_id not in canonical_edge_set and edge_id not in baseline_required_edge_set:
                continue
            edge_from = e.get("from")
            edge_to = e.get("to")
            from_placed = edge_from in placed
            to_placed = edge_to in placed
            if from_placed and (not to_placed):
                add_frontier(edge_id, edge_from, edge_to)
            elif to_placed and (not from_placed):
                add_frontier(edge_id, edge_to, edge_from)
            elif from_placed and to_placed:
                add_frontier(edge_id, edge_from, edge_to)

    push_frontier_for_node(start["id"])

    max_attempts = clamp_int(config.get("maxAttempts", 28), 5, 80)
    max_canonical_retries = clamp_int(config.get("maxCanonicalRetries", 2), 0, 8)
    sector_count = clamp_int(config.get("sectorCount", 8), 4, 32)
    safety_margin = float(config.get("safetyMargin", 1.0))

    def _usage_entropy_norm(counts: dict[str, int]) -> float:
        total = sum(max(0, int(v)) for v in counts.values())
        if total <= 0:
            return 0.0
        denom = math.log2(max(2, len([v for v in counts.values() if int(v) > 0])))
        if denom <= 1e-9:
            return 0.0
        e = 0.0
        for value in counts.values():
            c = max(0, int(value))
            if c <= 0:
                continue
            p = c / total
            e -= p * math.log2(max(1e-12, p))
        return clamp(e / denom, 0.0, 1.0)

    def rollback_to_snapshot(snap: dict[str, Any], node_id_to_cleanup: str | None = None) -> None:
        del level["platforms"][snap["p"]:]
        del level["enemies"][snap["e"]:]
        del level["keys"][snap["k"]:]
        del level["locks"][snap["l"]:]
        level["mapping"]["node"] = snap["maps"]
        level["anchors"] = snap["anchors"]
        level["mapping"]["edge"] = snap["edge_map"]
        if node_id_to_cleanup and node_id_to_cleanup not in snap["anchors"] and node_id_to_cleanup in placed:
            del placed[node_id_to_cleanup]

    guard = 0
    max_steps = max(30, len(edges) * 6)
    if is_main_mode and main_spine_first_mode:
        max_steps = max(
            max_steps,
            len(edges) * 12 + max(0, main_spine_repair_budget) * max(1, len(canonical_edges_order)),
        )
    while frontier and guard < max_steps:
        guard += 1
        pending_canonical = [edge_id for edge_id in canonical_edges_order if edge_id not in built_edges]
        if main_spine_first_mode and pending_canonical:
            pending_set = set(pending_canonical)
            canonical_indices = [i for i, f in enumerate(frontier) if str(f.get("edge_id")) in pending_set]
            if canonical_indices:
                idx = min(canonical_indices, key=lambda i: canonical_edge_rank.get(str(frontier[i].get("edge_id")), 10**9))
                spine_wait_cycles = 0
            else:
                injected = False
                for edge_id in pending_canonical:
                    e = edge_by_id.get(edge_id)
                    if not e:
                        continue
                    edge_from = str(e.get("from"))
                    edge_to = str(e.get("to"))
                    if edge_from in placed and edge_to not in placed:
                        add_frontier(edge_id, edge_from, edge_to, canonical=True)
                        injected = True
                        break
                    if edge_to in placed and edge_from not in placed:
                        add_frontier(edge_id, edge_to, edge_from, canonical=True)
                        injected = True
                        break
                    if edge_from in placed and edge_to in placed:
                        add_frontier(edge_id, edge_from, edge_to, canonical=True)
                        injected = True
                        break
                if injected:
                    continue
                spine_wait_cycles += 1
                if spine_wait_cycles <= 2:
                    continue
                idx = int(math.floor(rng.random() * len(frontier)))
        else:
            idx = next((i for i, f in enumerate(frontier) if f.get("canonical")), -1)
            if idx < 0:
                idx = int(math.floor(rng.random() * len(frontier)))
        work = frontier.pop(idx)
        eid = str(work.get("edge_id"))
        frm = str(work.get("from_id"))
        to = str(work.get("to_id"))
        fail_count = int(work.get("fail_count", 0) or 0)
        relaxed_local = bool(work.get("relaxed_local", False))
        force_legacy = bool(work.get("force_legacy", False))
        spine_repair = bool(work.get("spine_repair", False))
        frontier_keys.discard(f"{eid}|{frm}")

        if eid in built_edges:
            continue
        edge = edge_by_id.get(eid)
        if not edge or frm not in placed:
            continue
        if (
            is_main_mode
            and main_spine_first_mode
            and (eid in canonical_edge_set)
            and force_legacy
            and spine_repair
        ):
            forced_linear_used = int(spine_forced_linear_counts.get(eid, 0))
            if forced_linear_used >= main_spine_forced_linear_per_edge_cap:
                force_legacy = False
                spine_repair = False

        undirected = undirected_pair_key(str(edge.get("from")), str(edge.get("to")))
        if undirected in built_undirected:
            existing_id = built_undirected.get(undirected)
            mapped = level["mapping"]["edge"].get(existing_id, {}) if existing_id else {}
            from_anchor = placed.get(frm)
            to_anchor = placed.get(to)
            fallback_entry = dict(from_anchor["exit"]) if from_anchor else dict(level.get("start") or {"x": 0, "y": 0, "z": 0})
            fallback_exit = dict(to_anchor["entry"]) if to_anchor else dict(fallback_entry)
            level["mapping"]["edge"][edge["id"]] = {
                "from": edge.get("from"),
                "to": edge.get("to"),
                "entry": dict(mapped.get("entry") or fallback_entry),
                "exit": dict(mapped.get("exit") or fallback_exit),
                "constraints": {
                    "length": float(edge.get("length", DEFAULT_EDGE_LENGTH)),
                    "connector_family": (((mapped.get("constraints") or {}).get("connector_family")) or "shared_reuse"),
                    "node_family": (((mapped.get("constraints") or {}).get("node_family")) or "shared_reuse"),
                },
            }
            built_edges.add(eid)
            continue

        from_state = placed[frm]
        from_exit = (
            from_state["portsByNeighbor"].get(to)
            if isinstance(from_state.get("portsByNeighbor"), dict) and to in from_state["portsByNeighbor"]
            else from_state["exit"]
        )
        to_node = node_by_id.get(to)
        if not to_node:
            continue
        is_canonical_edge = eid in canonical_edge_set
        if is_main_mode and main_spine_first_mode and is_canonical_edge:
            selection_stats["main_spine_edge_attempts"] = int(selection_stats.get("main_spine_edge_attempts", 0)) + 1
        if (
            apply_key_lock_precheck
            and is_canonical_edge
            and node_has_type(to_node, NODE_TYPES["LOCK"])
            and not force_legacy
        ):
            required_key_id = to_node.get("requires_key_id")
            required_key_node = key_node_by_key_id.get(str(required_key_id)) if required_key_id else None
            can_construct_required_key = False
            if required_key_node and required_key_node in placed:
                can_construct_required_key = True
            elif required_key_node:
                queue = [nid for nid in placed.keys()]
                seen_nodes = set(queue)
                while queue:
                    cur_node = queue.pop(0)
                    if cur_node == required_key_node:
                        can_construct_required_key = True
                        break
                    for nxt in sorted(neighbors_by_node.get(cur_node, set())):
                        if nxt in seen_nodes:
                            continue
                        edge_between = built_undirected.get(undirected_pair_key(cur_node, nxt))
                        if edge_between:
                            continue
                        seen_nodes.add(nxt)
                        queue.append(nxt)
            if required_key_node and required_key_node not in placed and (not can_construct_required_key):
                add_frontier(
                    eid,
                    frm,
                    to,
                    fail_count=fail_count + 1,
                    canonical=(True if (is_main_mode and main_spine_first_mode) else False),
                    relaxed_local=relaxed_local,
                    force_legacy=force_legacy,
                    spine_repair=spine_repair,
                )
                selection_stats["key_lock_precheck_delays"] = int(selection_stats.get("key_lock_precheck_delays", 0)) + 1
                if is_main_mode and main_spine_first_mode:
                    selection_stats["main_spine_lock_precheck_delays"] = int(selection_stats.get("main_spine_lock_precheck_delays", 0)) + 1
                continue

        existing = to in placed
        candidate_order: list[dict[str, Any]] = []
        if use_diverse_strategy and not force_legacy and not spine_repair:
            raw_candidates = build_candidate_pool(
                edge=edge,
                to_node=to_node,
                rng=rng,
                pool_size=candidate_pool_size,
            )
            selection_stats["candidate_total"] = int(selection_stats.get("candidate_total", 0)) + len(raw_candidates)
            usage_for_score = dict(family_usage)
            if recent_family_window:
                for name in recent_family_window:
                    usage_for_score[name] = int(usage_for_score.get(name, 0)) + 1
            scored: list[dict[str, Any]] = []
            for candidate in raw_candidates:
                connector_family = str(candidate.get("connectorFamily", ""))
                node_family = str(candidate.get("nodeFamily", ""))
                if is_canonical_edge and not force_legacy:
                    if is_main_mode and main_canonical_safe_mode:
                        if connector_family and main_safe_connectors and connector_family not in main_safe_connectors:
                            selection_stats["rejected_risk"] = int(selection_stats.get("rejected_risk", 0)) + 1
                            continue
                        if node_family and main_safe_node_families and node_family not in main_safe_node_families:
                            selection_stats["rejected_risk"] = int(selection_stats.get("rejected_risk", 0)) + 1
                            continue
                        if float(candidate.get("complexity", 0.0)) > float(main_canonical_max_complexity):
                            selection_stats["rejected_risk"] = int(selection_stats.get("rejected_risk", 0)) + 1
                            continue
                    elif (not is_main_mode) and baseline_canonical_safe_mode:
                        if connector_family and baseline_safe_connectors and connector_family not in baseline_safe_connectors:
                            selection_stats["rejected_risk"] = int(selection_stats.get("rejected_risk", 0)) + 1
                            continue
                        if node_family and baseline_safe_node_families and node_family not in baseline_safe_node_families:
                            selection_stats["rejected_risk"] = int(selection_stats.get("rejected_risk", 0)) + 1
                            continue
                        if float(candidate.get("complexity", 0.0)) > float(baseline_canonical_max_complexity):
                            selection_stats["rejected_risk"] = int(selection_stats.get("rejected_risk", 0)) + 1
                            continue
                elif is_main_mode and main_spine_first_mode and (not force_legacy):
                    if float(candidate.get("complexity", 0.0)) > float(main_infill_max_complexity):
                        selection_stats["rejected_risk"] = int(selection_stats.get("rejected_risk", 0)) + 1
                        continue
                    if (
                        int(noncanonical_edge_count_by_node.get(str(frm), 0)) >= main_infill_max_per_node
                        or int(noncanonical_edge_count_by_node.get(str(to), 0)) >= main_infill_max_per_node
                    ):
                        selection_stats["rejected_risk"] = int(selection_stats.get("rejected_risk", 0)) + 1
                        continue
                if (
                    (connector_family and connector_family in disallow_connector_families)
                    or (node_family and node_family in disallow_node_families)
                ):
                    selection_stats["rejected_risk"] = int(selection_stats.get("rejected_risk", 0)) + 1
                    continue
                if max_candidate_complexity is not None and float(candidate.get("complexity", 0.0)) > max_candidate_complexity:
                    selection_stats["rejected_risk"] = int(selection_stats.get("rejected_risk", 0)) + 1
                    continue
                check = check_component_hard_constraints(
                    candidate,
                    edge=edge,
                    to_node=to_node,
                    canonical=is_canonical_edge,
                    config=config,
                )
                if not check.get("ok"):
                    selection_stats["rejected_constraints"] = int(selection_stats.get("rejected_constraints", 0)) + 1
                    continue
                scored_item = score_candidate(
                    candidate,
                    edge_length=float(edge.get("length", DEFAULT_EDGE_LENGTH)),
                    family_usage=usage_for_score,
                    weights=(
                        main_score_weights
                        if (is_main_mode and is_canonical_edge and not force_legacy)
                        else {
                            "alignmentWeight": config.get("alignmentWeight", 0.35),
                            "playabilityWeight": config.get("playabilityWeight", 0.30),
                            "noveltyWeight": config.get("noveltyWeight", 0.20),
                            "shapeWeight": config.get("shapeWeight", 0.15),
                            "riskWeight": config.get("riskWeight", 0.20),
                        }
                    ),
                )
                if is_main_mode and main_spine_first_mode and (not is_canonical_edge):
                    unique_count = len(main_infill_unique_families)
                    entropy_now = _usage_entropy_norm(main_infill_family_usage)
                    under_target = (
                        unique_count < main_infill_family_min_count
                        or entropy_now < main_infill_diversity_target
                    )
                    connector_name = str(candidate.get("connectorFamily") or "")
                    node_name = str(candidate.get("nodeFamily") or "")
                    connector_used = int(main_infill_family_usage.get(connector_name, 0))
                    node_used = int(main_infill_family_usage.get(node_name, 0))
                    total_used = max(1, sum(int(v) for v in main_infill_family_usage.values()))
                    introduces_new = (
                        (connector_name and connector_name not in main_infill_family_usage)
                        or (node_name and node_name not in main_infill_family_usage)
                    )
                    diversity_bonus = 0.0
                    repetition_penalty = 0.0
                    if under_target and introduces_new:
                        diversity_bonus = 0.09
                    if under_target and (not introduces_new):
                        repetition_penalty = 0.05 * ((connector_used + node_used) / total_used)
                    scored_item["score"] = float(scored_item.get("score", 0.0)) + diversity_bonus - repetition_penalty
                    detail = dict(scored_item.get("scoreDetail") or {})
                    detail["mainInfillDiversityBonus"] = float(diversity_bonus)
                    detail["mainInfillRepetitionPenalty"] = float(repetition_penalty)
                    detail["mainInfillUnderTarget"] = bool(under_target)
                    scored_item["scoreDetail"] = detail
                scored.append(scored_item)
            candidate_order = select_candidate_order(
                scored,
                selection_top_p=selection_top_p,
                selection_temperature=selection_temperature,
                rng=rng,
            )
        attempt_plan: list[dict[str, Any] | None]
        if spine_repair:
            attempt_plan = [None]
        elif use_diverse_strategy and not force_legacy:
            attempt_plan = list(candidate_order[:max_local_rejects])
            if fallback_enabled:
                attempt_plan.append(None)
            if not attempt_plan:
                attempt_plan = [None] if fallback_enabled else []
        else:
            attempt_plan = [None] * max_attempts
        success = False
        canonical_repair_requeue = False
        for attempt in range(min(max_attempts, len(attempt_plan))):
            diverse_candidate = attempt_plan[attempt] if (use_diverse_strategy and not spine_repair) else None
            chosen_sector: int | None = None
            if existing:
                target = (
                    placed[to]["portsByNeighbor"].get(frm)
                    if isinstance(placed[to].get("portsByNeighbor"), dict) and frm in placed[to]["portsByNeighbor"]
                    else placed[to]["entry"]
                )
                heading = normalize_heading({"x": target["x"] - from_exit["x"], "z": target["z"] - from_exit["z"]})
            else:
                if spine_repair:
                    chosen_sector = 0
                    seed_heading = level["anchors"].get(frm, {}).get("heading") or {"x": 1.0, "z": 0.0}
                    heading = snap_heading_to_axis(seed_heading)
                elif is_canonical_edge and canonical_linear_mode:
                    chosen_sector = 0
                    heading = {"x": 1.0, "z": 0.0}
                else:
                    chosen_sector = pick_sector_index(from_state, sector_count, attempt)
                    heading = sample_heading_from_sector(from_state, chosen_sector, sector_count, rng, heading_jitter)
                if node_has_type(to_node, NODE_TYPES["LOCK"]):
                    heading = snap_heading_to_axis(heading)
                target = {
                    "x": from_exit["x"] + heading["x"] * float(edge.get("length", DEFAULT_EDGE_LENGTH)),
                    "y": from_exit["y"],
                    "z": from_exit["z"] + heading["z"] * float(edge.get("length", DEFAULT_EDGE_LENGTH)),
                }
                if diverse_candidate:
                    lat = clamp(float((diverse_candidate.get("connector") or {}).get("lateralAmplitude", 1.0)), 0.2, 4.2)
                    jitter = rand_range(rng, lat * 0.45, lat * 1.1)
                else:
                    jitter = rand_range(rng, lateral_jitter_min, lateral_jitter_max)
                if spine_repair or (is_canonical_edge and canonical_linear_mode):
                    jitter = 0.0
                if is_canonical_edge:
                    scale = main_canonical_jitter_scale if is_main_mode else baseline_canonical_jitter_scale
                    jitter *= scale
                    if is_main_mode and main_spine_first_mode:
                        jitter = min(
                            jitter,
                            float(edge.get("length", DEFAULT_EDGE_LENGTH)) * main_spine_max_detour,
                            canonical_edge_detour_cap if canonical_edge_detour_cap > 0.0 else jitter,
                        )
                target["x"] += rand_range(rng, -jitter, jitter) * (-heading["z"])
                target["z"] += rand_range(rng, -jitter, jitter) * (heading["x"])

            if not existing:
                blocked = False
                for nid, st in placed.items():
                    if nid == frm:
                        continue
                    if _near(target, st["entry"], safety_margin) or _near(target, st["exit"], safety_margin):
                        blocked = True
                        break
                if blocked:
                    if use_diverse_strategy:
                        selection_stats["rejected_overlap"] = int(selection_stats.get("rejected_overlap", 0)) + 1
                    continue

            snap = {
                "p": len(level["platforms"]),
                "e": len(level["enemies"]),
                "k": len(level["keys"]),
                "l": len(level["locks"]),
                "maps": copy.deepcopy(level["mapping"]["node"]),
                "anchors": copy.deepcopy(level["anchors"]),
                "edge_map": copy.deepcopy(level["mapping"]["edge"]),
            }
            connector_style = (diverse_candidate or {}).get("connector")
            connector_step = connector_segment_length
            if is_canonical_edge and is_main_mode and main_spine_first_mode:
                connector_step = min(connector_step, main_spine_edge_segment_length)
            if spine_repair:
                connector_style = {
                    "family": "linear_bridge",
                    "lateralAmplitude": 0.25,
                    "verticalAmplitude": 0.25,
                    "zigzagPeriod": 6.0,
                    "stairStep": 0.4,
                    "movingRate": 0.0,
                    "hazardDensity": 0.0,
                }
                connector_step = main_spine_edge_segment_length
                selection_stats["main_spine_forced_linear"] = int(selection_stats.get("main_spine_forced_linear", 0)) + 1
                spine_forced_linear_counts[eid] = int(spine_forced_linear_counts.get(eid, 0)) + 1
            con = add_connector(
                edge,
                from_exit,
                target,
                builder,
                rng,
                connector_style,
                segment_length=connector_step,
            )
            level["mapping"]["edge"][edge["id"]] = {
                "from": edge["from"],
                "to": edge["to"],
                "entry": con["entry"],
                "exit": con["exit"],
                "constraints": {
                    "length": float(edge.get("length", DEFAULT_EDGE_LENGTH)),
                    "connector_family": (diverse_candidate or {}).get("connectorFamily", "legacy_linear"),
                    "node_family": (diverse_candidate or {}).get("nodeFamily", "legacy_default"),
                },
            }

            if not existing:
                node_style = dict((diverse_candidate or {}).get("node") or {})
                if is_canonical_edge:
                    safe_ground_flag = (
                        (main_spine_safe_ground if (is_main_mode and main_spine_first_mode) else bool(config.get("mainCanonicalSafeGround", True)))
                        if is_main_mode
                        else bool(config.get("baselineCanonicalSafeGround", False))
                    )
                    node_style.setdefault(
                        "challengeScale",
                        main_canonical_challenge_scale if is_main_mode else baseline_canonical_challenge_scale,
                    )
                    node_style.setdefault("safeGround", safe_ground_flag)
                    if not node_style.get("family"):
                        if node_has_type(to_node, NODE_TYPES["KEY"]):
                            node_style["family"] = "safe_key_pocket"
                        elif node_has_type(to_node, NODE_TYPES["LOCK"]):
                            node_style["family"] = "center_gate"
                        elif node_has_type(to_node, NODE_TYPES["GOAL"]):
                            node_style["family"] = "goal_platform"
                        else:
                            node_style["family"] = "open_room"
                if is_main_mode and is_canonical_edge and main_spine_first_mode and spine_repair:
                    if node_has_type(to_node, NODE_TYPES["KEY"]):
                        node_style["family"] = "safe_key_pocket"
                    elif node_has_type(to_node, NODE_TYPES["LOCK"]):
                        node_style["family"] = "center_gate"
                    elif node_has_type(to_node, NODE_TYPES["GOAL"]):
                        node_style["family"] = "goal_platform"
                    elif node_has_type(to_node, NODE_TYPES["START"]):
                        node_style["family"] = "start_plaza"
                    else:
                        node_style["family"] = "open_room"
                    node_style["challengeScale"] = min(main_canonical_challenge_scale, 0.42)
                    node_style["safeGround"] = True
                chunk = build_node_chunk(
                    to_node,
                    target,
                    heading,
                    rng,
                    builder,
                    max_vertical,
                    node_style if node_style else None,
                )
                if node_has_type(to_node, NODE_TYPES["LOCK"]):
                    neighbors = sorted(neighbors_by_node.get(to, set()))
                    other_neighbor = next((nid for nid in neighbors if nid and nid != frm), None)
                    ports = {frm: dict(chunk["entry"])}
                    if other_neighbor:
                        ports[other_neighbor] = dict(chunk["exit"])
                    level["anchors"][to] = {
                        "entry": chunk["entry"],
                        "exit": chunk["exit"],
                        "heading": dict(chunk.get("heading") or heading),
                        "portsByNeighbor": ports,
                        "gate": chunk.get("gate"),
                    }
                    placed[to] = {
                        "entry": chunk["entry"],
                        "exit": chunk["exit"],
                        "outgoing": 0,
                        "used": set(),
                        "sector_shift": int(math.floor(rng.random() * 1000000.0)) % 9967,
                        "base_angle": rng.random() * math.pi * 2,
                        "portsByNeighbor": ports,
                    }
                else:
                    level["anchors"][to] = {"entry": chunk["entry"], "exit": chunk["exit"], "heading": dict(heading)}
                    placed[to] = {
                        "entry": chunk["entry"],
                        "exit": chunk["exit"],
                        "outgoing": 0,
                        "used": set(),
                        "sector_shift": int(math.floor(rng.random() * 1000000.0)) % 9967,
                        "base_angle": rng.random() * math.pi * 2,
                        "portsByNeighbor": None,
                    }
                if node_has_type(to_node, NODE_TYPES["GOAL"]):
                    level["goal"] = dict(chunk["exit"])

            if (
                is_canonical_edge
                and (
                    (is_main_mode and main_limit_dynamic_on_canonical)
                    or ((not is_main_mode) and baseline_limit_dynamic_on_canonical)
                )
            ):
                for p in level["platforms"][snap["p"]:]:
                    if p.get("kind") == "moving":
                        p["kind"] = "static"
                        p["motion"] = None
                if len(level["enemies"]) > snap["e"]:
                    del level["enemies"][snap["e"]:]

            connector_node_id = f"edge:{edge.get('id')}"
            connector_touch_nodes = {frm, to}
            overlap_eval = _evaluate_safety_margin(
                level,
                snap,
                node_bounds,
                connector_node_id,
                connector_touch_nodes,
                safety_margin,
            )
            if not overlap_eval.get("ok"):
                rollback_to_snapshot(snap, to)
                if is_main_mode and main_spine_first_mode and is_canonical_edge:
                    selection_stats["main_spine_rollbacks"] = int(selection_stats.get("main_spine_rollbacks", 0)) + 1
                if use_diverse_strategy:
                    selection_stats["rejected_overlap"] = int(selection_stats.get("rejected_overlap", 0)) + 1
                continue

            local_payload = {
                "level": level,
                "etg": etg,
                "fromId": frm,
                "toId": to,
                "edge": edge,
                "boundsDelta": overlap_eval.get("delta_bounds", {}),
                "extraConnectivityPolicy": config.get("extra_connectivity_policy", config.get("extraConnectivityPolicy", "strict_1hop")),
                "cellSize": config.get("validationCellSize", 1),
                "timeStep": config.get("validationTimeStep", 1),
                "modelPadding": config.get("validationModelPadding", 2),
                "localPaddingCells": config.get("validationLocalPaddingCells", 3),
                "maxTime": config.get("validationMaxTime", 160),
                "maxStates": config.get("validationMaxStates", 120000),
                "maxQueue": config.get("validationMaxQueue", 90000),
                "maxJumpOffsets": config.get("validationMaxJumpOffsets", 900),
                "maxTimeHorizon": config.get("validationMaxTimeHorizon", config.get("maxTimeHorizon", 180)),
                "maxPeriodTicks": config.get("validationMaxPeriodTicks", config.get("maxPeriodTicks", 180)),
                "allowJump": config.get("validationAllowJump", True),
                "allowDrop": config.get("validationAllowDrop", True),
                "toleranceRadiusCells": config.get(
                    "validationToleranceRadiusCells",
                    config.get("toleranceRadiusCells", config.get("toleranceRadius", 2)),
                ),
                "allowSiblingTolerance": config.get("validationAllowSiblingTolerance", True),
            }

            if is_main_mode and validate_local_placement and (not relaxed_local):
                local_payload["allowFastBudget"] = bool(config.get("mainAllowFastLocalBudget", True))
                local_scale = main_canonical_validation_scale if is_canonical_edge else main_infill_validation_scale
                local_payload["maxTime"] = max(
                    main_validation_min_time,
                    clamp_int(float(local_payload.get("maxTime") or 160) * local_scale, 10, 500),
                )
                local_payload["maxStates"] = max(
                    main_validation_min_states,
                    clamp_int(float(local_payload.get("maxStates") or 120000) * local_scale, 3_000, 450_000),
                )
                local_payload["maxQueue"] = max(
                    main_validation_min_queue,
                    clamp_int(float(local_payload.get("maxQueue") or 90000) * local_scale, 2_500, 350_000),
                )
                local_payload["maxJumpOffsets"] = max(
                    main_validation_min_jump_offsets,
                    clamp_int(float(local_payload.get("maxJumpOffsets") or 900) * local_scale, 80, 6000),
                )

            run_local_validation = True
            if is_main_mode and main_spine_first_mode and is_canonical_edge:
                spine_local_checks += 1
                if main_spine_local_check_stride > 1 and (spine_local_checks % main_spine_local_check_stride) != 0:
                    run_local_validation = False
            if is_main_mode and main_spine_first_mode and (not is_canonical_edge) and main_infill_skip_local_validation:
                run_local_validation = False
            if validate_local_placement and not relaxed_local and (not run_local_validation):
                selection_stats["local_validation_skips"] = int(selection_stats.get("local_validation_skips", 0)) + 1
            if validate_local_placement and not relaxed_local and run_local_validation:
                selection_stats["local_validation_calls"] = int(selection_stats.get("local_validation_calls", 0)) + 1
                res = validate_local_placement(local_payload)
                if not (res or {}).get("ok", False):
                    rollback_to_snapshot(snap, to)
                    if is_main_mode and main_spine_first_mode and is_canonical_edge:
                        selection_stats["main_spine_rollbacks"] = int(selection_stats.get("main_spine_rollbacks", 0)) + 1
                    if use_diverse_strategy:
                        selection_stats["rejected_validation"] = int(selection_stats.get("rejected_validation", 0)) + 1
                    selection_stats["local_validation_failures"] = int(selection_stats.get("local_validation_failures", 0)) + 1
                    continue
                if is_main_mode and is_canonical_edge and main_post_edge_repair and not force_legacy:
                    quick_payload = dict(local_payload)
                    quick_payload["maxTime"] = config.get("mainQuickMaxTime", min(int(local_payload["maxTime"]), 48))
                    quick_payload["maxStates"] = config.get("mainQuickMaxStates", min(int(local_payload["maxStates"]), 22000))
                    quick_payload["maxQueue"] = config.get("mainQuickMaxQueue", min(int(local_payload["maxQueue"]), 18000))
                    quick_payload["maxJumpOffsets"] = config.get("mainQuickMaxJumpOffsets", min(int(local_payload["maxJumpOffsets"]), 220))
                    quick = validate_local_placement(quick_payload)
                    if not (quick or {}).get("ok", False):
                        quick_reason = str((quick or {}).get("reason") or "unknown")
                        hard_quick_fail = quick_reason in main_quick_hard_fail_reasons
                        if (
                            (not hard_quick_fail)
                            and main_quick_treat_budget_as_hard_fail
                            and quick_reason in {"budget_exceeded", "wall_time_exceeded"}
                        ):
                            hard_quick_fail = True
                        if hard_quick_fail:
                            if main_spine_rollback_on_fail:
                                rollback_to_snapshot(snap, to)
                            else:
                                rollback_to_snapshot(snap, to)
                            if is_main_mode and main_spine_first_mode and is_canonical_edge:
                                selection_stats["main_spine_rollbacks"] = int(selection_stats.get("main_spine_rollbacks", 0)) + 1
                            if use_diverse_strategy:
                                selection_stats["post_edge_repairs"] = int(selection_stats.get("post_edge_repairs", 0)) + 1
                            selection_stats["local_validation_quick_failures"] = int(selection_stats.get("local_validation_quick_failures", 0)) + 1
                            canonical_repair_requeue = True
                            break
                        selection_stats["local_validation_quick_soft_failures"] = int(selection_stats.get("local_validation_quick_soft_failures", 0)) + 1

            built_edges.add(eid)
            built_undirected[undirected] = eid
            if is_main_mode and main_spine_first_mode:
                if is_canonical_edge:
                    selection_stats["main_spine_edge_success"] = int(selection_stats.get("main_spine_edge_success", 0)) + 1
                    spine_failure_counts[eid] = 0
                else:
                    selection_stats["main_spine_infill_edges"] = int(selection_stats.get("main_spine_infill_edges", 0)) + 1
            for node_id, bounds in (overlap_eval.get("proposed_bounds") or {}).items():
                node_bounds[node_id] = bounds
            from_state["outgoing"] += 1
            if chosen_sector is not None:
                from_state["used"].add(chosen_sector)
            edge_constraints = (((level.get("mapping") or {}).get("edge") or {}).get(str(edge.get("id"))) or {}).get("constraints") or {}
            usage_names = [
                str(edge_constraints.get("connector_family") or ""),
                str(edge_constraints.get("node_family") or ""),
            ]
            for name in usage_names:
                if not name:
                    continue
                family_usage[name] = int(family_usage.get(name, 0)) + 1
                if use_diverse_strategy:
                    recent_family_window.append(name)
                if (not use_diverse_strategy) or (not diverse_candidate):
                    selection_stats["family_usage_legacy_updates"] = int(selection_stats.get("family_usage_legacy_updates", 0)) + 1
            if use_diverse_strategy:
                while len(recent_family_window) > family_balance_window:
                    recent_family_window.pop(0)
                if diverse_candidate:
                    selection_stats["candidate_accepted"] = int(selection_stats.get("candidate_accepted", 0)) + 1
                else:
                    selection_stats["fallback_uses"] = int(selection_stats.get("fallback_uses", 0)) + 1
            if eid in noncanonical_edge_set:
                noncanonical_edge_count_by_node[str(frm)] = int(noncanonical_edge_count_by_node.get(str(frm), 0)) + 1
                noncanonical_edge_count_by_node[str(to)] = int(noncanonical_edge_count_by_node.get(str(to), 0)) + 1
            if is_main_mode and main_spine_first_mode and (not is_canonical_edge):
                selection_stats["main_infill_diversity_checks"] = int(selection_stats.get("main_infill_diversity_checks", 0)) + 1
                if diverse_candidate:
                    cname = str(diverse_candidate.get("connectorFamily") or "")
                    nname = str(diverse_candidate.get("nodeFamily") or "")
                    if cname:
                        main_infill_family_usage[cname] = int(main_infill_family_usage.get(cname, 0)) + 1
                        main_infill_unique_families.add(cname)
                    if nname:
                        main_infill_family_usage[nname] = int(main_infill_family_usage.get(nname, 0)) + 1
                        main_infill_unique_families.add(nname)
                if (
                    len(main_infill_unique_families) >= main_infill_family_min_count
                    and _usage_entropy_norm(main_infill_family_usage) >= main_infill_diversity_target
                ):
                    selection_stats["main_infill_diversity_target_hits"] = int(selection_stats.get("main_infill_diversity_target_hits", 0)) + 1
            if not existing:
                push_frontier_for_node(to)
            success = True
            break

        if not success:
            is_canonical_edge = eid in canonical_edge_set
            if is_main_mode and main_spine_first_mode and is_canonical_edge:
                selection_stats["main_spine_edge_fail"] = int(selection_stats.get("main_spine_edge_fail", 0)) + 1
                next_fail = int(spine_failure_counts.get(eid, 0)) + 1
                spine_failure_counts[eid] = next_fail
            else:
                next_fail = int(spine_failure_counts.get(eid, 0))
            if (
                is_main_mode
                and is_canonical_edge
                and canonical_repair_requeue
                and main_canonical_force_legacy_on_fail
            ):
                add_frontier(
                    eid,
                    frm,
                    to,
                    fail_count=fail_count + 1,
                    canonical=(True if (main_spine_first_mode and next_fail <= main_spine_repair_budget) else False),
                    relaxed_local=False,
                    force_legacy=True,
                    spine_repair=(main_spine_first_mode and next_fail <= main_spine_repair_budget),
                )
                if use_diverse_strategy:
                    selection_stats["canonical_rescue_relax"] = int(selection_stats.get("canonical_rescue_relax", 0)) + 1
                if is_main_mode and main_spine_first_mode and next_fail <= main_spine_repair_budget:
                    selection_stats["main_spine_repairs"] = int(selection_stats.get("main_spine_repairs", 0)) + 1
                continue
            if (
                is_main_mode
                and main_spine_first_mode
                and is_canonical_edge
                and next_fail <= main_spine_repair_budget
            ):
                add_frontier(
                    eid,
                    frm,
                    to,
                    fail_count=fail_count + 1,
                    canonical=True,
                    relaxed_local=False,
                    force_legacy=True,
                    spine_repair=True,
                )
                selection_stats["main_spine_repairs"] = int(selection_stats.get("main_spine_repairs", 0)) + 1
                continue
            if is_canonical_edge and fail_count < max_canonical_retries:
                key = f"{eid}|{frm}"
                if key not in frontier_keys:
                    frontier_keys.add(key)
                    frontier.append(
                        {
                            "edge_id": eid,
                            "from_id": frm,
                            "to_id": to,
                            "canonical": (True if (is_main_mode and main_spine_first_mode) else False),
                            "fail_count": fail_count + 1,
                            "relaxed_local": relaxed_local,
                            "force_legacy": force_legacy,
                            "spine_repair": False,
                        }
                    )
                    if use_diverse_strategy:
                        selection_stats["requeued_canonical"] = int(selection_stats.get("requeued_canonical", 0)) + 1
            elif (
                is_canonical_edge
                and fallback_enabled
                and (not relaxed_local)
                and ((not is_main_mode) or main_canonical_force_legacy_on_fail)
            ):
                key = f"{eid}|{frm}"
                if key not in frontier_keys:
                    frontier_keys.add(key)
                    frontier.append(
                        {
                            "edge_id": eid,
                            "from_id": frm,
                            "to_id": to,
                            "canonical": (True if (is_main_mode and main_spine_first_mode) else False),
                            "fail_count": fail_count + 1,
                            "relaxed_local": (False if is_main_mode else True),
                            "force_legacy": True,
                            "spine_repair": bool(is_main_mode and main_spine_first_mode),
                        }
                    )
                    if use_diverse_strategy:
                        selection_stats["canonical_rescue_relax"] = int(selection_stats.get("canonical_rescue_relax", 0)) + 1
            continue

    enable_connectivity_fallback = bool(config.get("forceConnectivityFallback", (not (is_main_mode and main_spine_first_mode))))
    if is_main_mode and main_spine_first_mode:
        length_hint = clamp_int(config.get("length", len(nodes) if nodes else 0), 1, 200)
        remaining_infill_edges = [
            edge
            for edge in edges
            if edge.get("id") not in built_edges and edge.get("id") not in canonical_edge_set
        ]
        total_noncanonical = len(noncanonical_edge_set)
        built_noncanonical = len([eid for eid in built_edges if str(eid) in noncanonical_edge_set])
        pre_coverage_ratio = (built_noncanonical / total_noncanonical) if total_noncanonical > 0 else 1.0
        infill_under_coverage = total_noncanonical > 0 and pre_coverage_ratio < main_infill_coverage_min_ratio
        infill_under_target = len(main_infill_unique_families) < int(main_infill_family_min_count)
        default_infill_fallback = (
            (length_hint <= 8)
            or (infill_under_target and len(remaining_infill_edges) > 0)
            or (main_infill_coverage_pass and infill_under_coverage and len(remaining_infill_edges) > 0)
        )
        enable_connectivity_fallback = bool(
            config.get(
                "mainInfillConnectivityFallback",
                default_infill_fallback,
            )
        )
    if enable_connectivity_fallback:
        max_repair_loops = max(2, len(edges) * 3)
        repair_count = 0
        for _ in range(max_repair_loops):
            repaired_any = False
            for edge in edges:
                edge_id = edge.get("id")
                if not edge_id or edge_id in built_edges:
                    continue
                if baseline_build_required_edges_only and edge_id not in canonical_edge_set and edge_id not in baseline_required_edge_set:
                    continue
                if is_main_mode and main_spine_first_mode and edge_id in canonical_edge_set:
                    continue
                edge_from = str(edge.get("from"))
                edge_to = str(edge.get("to"))
                if edge_from not in placed and edge_to not in placed:
                    continue

                undirected = undirected_pair_key(edge_from, edge_to)
                if undirected in built_undirected:
                    existing_id = built_undirected.get(undirected)
                    mapped = level["mapping"]["edge"].get(existing_id, {}) if existing_id else {}
                    src_anchor = placed.get(edge_from) or placed.get(edge_to)
                    fallback_entry = dict((src_anchor or {}).get("exit") or level.get("start") or {"x": 0, "y": 0, "z": 0})
                    fallback_exit = dict(fallback_entry)
                    level["mapping"]["edge"][edge_id] = {
                        "from": edge.get("from"),
                        "to": edge.get("to"),
                        "entry": dict(mapped.get("entry") or fallback_entry),
                        "exit": dict(mapped.get("exit") or fallback_exit),
                        "constraints": {
                            "length": float(edge.get("length", DEFAULT_EDGE_LENGTH)),
                            "connector_family": "connectivity_fallback",
                            "node_family": "connectivity_fallback",
                        },
                    }
                    built_edges.add(edge_id)
                    family_usage["connectivity_fallback"] = int(family_usage.get("connectivity_fallback", 0)) + 2
                    selection_stats["family_usage_legacy_updates"] = int(selection_stats.get("family_usage_legacy_updates", 0)) + 2
                    if str(edge_id) in noncanonical_edge_set:
                        noncanonical_edge_count_by_node[str(edge_from)] = int(noncanonical_edge_count_by_node.get(str(edge_from), 0)) + 1
                        noncanonical_edge_count_by_node[str(edge_to)] = int(noncanonical_edge_count_by_node.get(str(edge_to), 0)) + 1
                    repaired_any = True
                    repair_count += 1
                    continue

                if edge_from in placed:
                    from_id, to_id = edge_from, edge_to
                else:
                    from_id, to_id = edge_to, edge_from
                from_state = placed[from_id]
                from_exit = (
                    from_state["portsByNeighbor"].get(to_id)
                    if isinstance(from_state.get("portsByNeighbor"), dict) and to_id in from_state["portsByNeighbor"]
                    else from_state["exit"]
                )
                to_existing = to_id in placed
                if to_existing:
                    target = (
                        placed[to_id]["portsByNeighbor"].get(from_id)
                        if isinstance(placed[to_id].get("portsByNeighbor"), dict) and from_id in placed[to_id]["portsByNeighbor"]
                        else placed[to_id]["entry"]
                    )
                    heading = normalize_heading({"x": target["x"] - from_exit["x"], "z": target["z"] - from_exit["z"]})
                else:
                    to_node = node_by_id.get(to_id)
                    if not to_node:
                        continue
                    heading = sample_heading_from_sector(from_state, pick_sector_index(from_state, sector_count, repair_count), sector_count, rng, 0.05)
                    target = {
                        "x": from_exit["x"] + heading["x"] * float(edge.get("length", DEFAULT_EDGE_LENGTH)),
                        "y": from_exit["y"],
                        "z": from_exit["z"] + heading["z"] * float(edge.get("length", DEFAULT_EDGE_LENGTH)),
                    }
                con = add_connector(
                    edge,
                    from_exit,
                    target,
                    builder,
                    rng,
                    {
                        "family": "linear_bridge",
                        "lateralAmplitude": 0.3,
                        "verticalAmplitude": 0.3,
                        "zigzagPeriod": 5.5,
                        "stairStep": 0.5,
                        "movingRate": 0.0,
                        "hazardDensity": 0.0,
                    },
                    segment_length=min(6.0, connector_segment_length),
                )
                level["mapping"]["edge"][edge_id] = {
                    "from": edge.get("from"),
                    "to": edge.get("to"),
                    "entry": con["entry"],
                    "exit": con["exit"],
                    "constraints": {
                        "length": float(edge.get("length", DEFAULT_EDGE_LENGTH)),
                        "connector_family": "connectivity_fallback",
                        "node_family": "connectivity_fallback",
                    },
                }
                if not to_existing:
                    to_node = node_by_id.get(to_id)
                    if not to_node:
                        continue
                    node_style = None
                    if node_has_type(to_node, NODE_TYPES["LOCK"]):
                        node_style = {"family": "center_gate", "challengeScale": baseline_canonical_challenge_scale, "safeGround": True}
                    elif node_has_type(to_node, NODE_TYPES["KEY"]):
                        node_style = {"family": "safe_key_pocket", "challengeScale": baseline_canonical_challenge_scale, "safeGround": True}
                    elif node_has_type(to_node, NODE_TYPES["GOAL"]):
                        node_style = {"family": "goal_platform", "challengeScale": baseline_canonical_challenge_scale, "safeGround": True}
                    else:
                        node_style = {"family": "open_room", "challengeScale": baseline_canonical_challenge_scale, "safeGround": True}
                    chunk = build_node_chunk(to_node, target, heading, rng, builder, max_vertical, node_style)
                    if node_has_type(to_node, NODE_TYPES["LOCK"]):
                        level["anchors"][to_id] = {
                            "entry": chunk["entry"],
                            "exit": chunk["exit"],
                            "heading": dict(chunk.get("heading") or heading),
                            "portsByNeighbor": {},
                            "gate": chunk.get("gate"),
                        }
                        placed[to_id] = {
                            "entry": chunk["entry"],
                            "exit": chunk["exit"],
                            "outgoing": 0,
                            "used": set(),
                            "sector_shift": int(math.floor(rng.random() * 1000000.0)) % 9967,
                            "base_angle": rng.random() * math.pi * 2,
                            "portsByNeighbor": {},
                        }
                    else:
                        level["anchors"][to_id] = {"entry": chunk["entry"], "exit": chunk["exit"], "heading": dict(heading)}
                        placed[to_id] = {
                            "entry": chunk["entry"],
                            "exit": chunk["exit"],
                            "outgoing": 0,
                            "used": set(),
                            "sector_shift": int(math.floor(rng.random() * 1000000.0)) % 9967,
                            "base_angle": rng.random() * math.pi * 2,
                            "portsByNeighbor": None,
                        }
                    if node_has_type(to_node, NODE_TYPES["GOAL"]):
                        level["goal"] = dict(chunk["exit"])
                built_edges.add(edge_id)
                built_undirected[undirected] = edge_id
                family_usage["connectivity_fallback"] = int(family_usage.get("connectivity_fallback", 0)) + 2
                selection_stats["family_usage_legacy_updates"] = int(selection_stats.get("family_usage_legacy_updates", 0)) + 2
                if str(edge_id) in noncanonical_edge_set:
                    noncanonical_edge_count_by_node[str(edge_from)] = int(noncanonical_edge_count_by_node.get(str(edge_from), 0)) + 1
                    noncanonical_edge_count_by_node[str(edge_to)] = int(noncanonical_edge_count_by_node.get(str(edge_to), 0)) + 1
                repaired_any = True
                repair_count += 1
                if is_main_mode and main_spine_first_mode and edge_id not in canonical_edge_set:
                    selection_stats["main_infill_diversity_checks"] = int(selection_stats.get("main_infill_diversity_checks", 0)) + 1
            if not repaired_any:
                break
        if repair_count > 0 and isinstance(selection_stats, dict):
            selection_stats["connectivity_fallback_edges"] = int(selection_stats.get("connectivity_fallback_edges", 0)) + int(repair_count)
            if is_main_mode and main_spine_first_mode:
                selection_stats["main_spine_fallback_edges"] = int(selection_stats.get("main_spine_fallback_edges", 0)) + int(repair_count)

    if not level.get("goal"):
        s = level.get("start") or {"x": 0, "y": 0, "z": 0}
        level["goal"] = {"x": s["x"] + 12, "y": s["y"], "z": s["z"]}

    _assign_lock_ports_by_neighbors(level, edges)

    if use_diverse_strategy:
        processed_edges = max(1, len(built_edges))
        total = int(selection_stats.get("candidate_total", 0))
        accepted = int(selection_stats.get("candidate_accepted", 0))
        selection_stats["processed_edges"] = len(built_edges)
        selection_stats["accept_rate"] = round((accepted / total), 4) if total > 0 else 0.0
        selection_stats["avg_candidates_per_edge"] = round(total / processed_edges, 3)
    if is_main_mode and main_spine_first_mode:
        checks = int(selection_stats.get("main_infill_diversity_checks", 0))
        hits = int(selection_stats.get("main_infill_diversity_target_hits", 0))
        selection_stats["main_infill_diversity_target_hit_rate"] = round((hits / checks), 4) if checks > 0 else 0.0
    noncanonical_total = len(noncanonical_edge_set)
    noncanonical_built = len([eid for eid in built_edges if str(eid) in noncanonical_edge_set])
    selection_stats["noncanonical_edges_built"] = int(noncanonical_built)
    if is_main_mode:
        selection_stats["main_infill_edges_built"] = int(noncanonical_built)
        selection_stats["main_infill_edge_coverage_ratio"] = (
            round(noncanonical_built / noncanonical_total, 4) if noncanonical_total > 0 else 1.0
        )

    return level


def _ensure_key_lock_consistency(level: dict[str, Any], etg: dict[str, Any], rng: Mulberry32 | None = None) -> None:
    keys = level.get("keys")
    if not isinstance(keys, list):
        keys = []
        level["keys"] = keys
    locks = level.get("locks")
    if not isinstance(locks, list):
        locks = []
        level["locks"] = locks
    key_ids = {str(k.get("key_id")) for k in keys if k.get("key_id")}
    existing_ids = {str(k.get("id")) for k in keys if k.get("id")}
    key_node_by_key_id = {
        str(node.get("key_id")): str(node.get("id"))
        for node in etg.get("nodes") or []
        if node.get("id") and node.get("key_id") and node_has_type(node, NODE_TYPES["KEY"])
    }

    def next_key_item_id() -> str:
        idx = len(keys)
        while True:
            cand = f"K{idx}"
            if cand not in existing_ids:
                existing_ids.add(cand)
                return cand
            idx += 1

    repairs = 0
    for lock in locks:
        key_id = lock.get("key_id")
        if not key_id or key_id in key_ids:
            continue
        node_id = key_node_by_key_id.get(str(key_id))
        if not node_id:
            continue
        anchor = ((level.get("anchors") or {}).get(node_id) or {})
        base = anchor.get("entry") or level.get("start") or {"x": 0.0, "y": 0.0, "z": 0.0}
        jx = rand_range(rng, 1.2, 2.6) if rng else 1.6
        jz = rand_range(rng, -1.2, 1.2) if rng else 0.0
        key_item = {
            "id": next_key_item_id(),
            "key_id": key_id,
            "pos": {
                "x": float(base.get("x", 0.0)) + jx,
                "y": float(base.get("y", 0.0)) + ENEMY_CLEARANCE_Y,
                "z": float(base.get("z", 0.0)) + jz,
            },
            "radius": 0.4,
            "node_id": node_id,
        }
        keys.append(key_item)
        mapping_node = (level.setdefault("mapping", {}).setdefault("node", {})).setdefault(
            node_id,
            {"platforms": [], "enemies": [], "keys": [], "locks": [], "checkpoints": []},
        )
        mapping_node.setdefault("keys", []).append(key_item["id"])
        key_ids.add(key_id)
        repairs += 1

    if repairs > 0:
        stats = (((level.get("meta") or {}).get("component_generation") or {}).get("selection_stats") or {})
        stats["key_lock_repairs"] = int(stats.get("key_lock_repairs", 0)) + repairs


def apply_main_event_pacing(
    level: dict[str, Any],
    etg: dict[str, Any],
    config: dict[str, Any],
    rng: Mulberry32 | None = None,
) -> int:
    if not bool(config.get("mainEventPacingPass", True)):
        return 0
    canonical = compute_canonical_route(etg, {"defaultSpeed": (etg.get("meta") or {}).get("defaultSpeed")})
    canonical_nodes = [str(nid) for nid in (canonical.get("nodes") or []) if nid]
    if not canonical_nodes:
        return 0
    mapping_node = ((level.get("mapping") or {}).get("node") or {})
    anchors = level.get("anchors") or {}
    node_ids = [nid for nid in canonical_nodes if nid in mapping_node and nid in anchors]
    if len(node_ids) < 3:
        return 0

    nodes_by_id = {str(n.get("id")): n for n in (etg.get("nodes") or []) if n.get("id")}
    bins = clamp_int(config.get("mainEventBins", 5), 3, 10)
    target_density = clamp(float(config.get("mainEventDensityTarget", 0.08)), 0.03, 0.2)
    tolerance = clamp(float(config.get("mainEventDensityTolerance", 0.05)), 0.01, 0.15)
    path_len = len(node_ids)
    adaptive_target = clamp(target_density + (0.012 if path_len <= 6 else (-0.008 if path_len >= 12 else 0.0)), 0.03, 0.20)
    lower = max(0.0, adaptive_target - tolerance)
    upper = adaptive_target + tolerance

    enemy_by_id = {str(e.get("id")): dict(e) for e in (level.get("enemies") or []) if e.get("id")}

    def _node_event_total(node_id: str) -> int:
        rec = mapping_node.get(node_id) or {}
        return int(len(rec.get("enemies") or [])) + int(len(rec.get("keys") or [])) + int(len(rec.get("locks") or []))

    def _bin_index(pos: int) -> int:
        return min(bins - 1, int((pos / max(1, path_len)) * bins))

    bin_nodes: list[list[str]] = [[] for _ in range(bins)]
    for idx, node_id in enumerate(node_ids):
        bin_nodes[_bin_index(idx)].append(node_id)

    def _bin_event_total(node_group: list[str]) -> int:
        return sum(_node_event_total(nid) for nid in node_group)

    total_events = sum(_node_event_total(nid) for nid in node_ids)
    density = total_events / max(1.0, float(path_len))
    adjustments = 0
    builder = _builder_from_level(level)
    local_rng = rng or Mulberry32(1)

    if density < lower:
        needed = clamp_int(math.ceil((lower * path_len) - total_events), 0, 12)
        for _ in range(needed):
            bin_order = sorted(range(len(bin_nodes)), key=lambda idx: _bin_event_total(bin_nodes[idx]))
            candidate_nodes: list[str] = []
            for bidx in bin_order:
                candidate_nodes = sorted(
                    (
                        nid
                        for nid in bin_nodes[bidx]
                        if not node_has_type(nodes_by_id.get(nid, {}), NODE_TYPES["START"])
                        and not node_has_type(nodes_by_id.get(nid, {}), NODE_TYPES["GOAL"])
                        and not node_has_type(nodes_by_id.get(nid, {}), NODE_TYPES["LOCK"])
                    ),
                    key=lambda nid: (_node_event_total(nid), nid),
                )
                if candidate_nodes:
                    break
            if not candidate_nodes:
                break
            node_id = candidate_nodes[0]
            anchor = anchors.get(node_id) or {}
            base = anchor.get("entry") or anchor.get("exit")
            if not isinstance(base, dict):
                continue
            heading = normalize_heading(anchor.get("heading") or {"x": 1.0, "z": 0.0})
            if abs(heading["x"]) + abs(heading["z"]) < 1e-6:
                heading = {"x": 1.0, "z": 0.0}
            patrol_len = 2.8 + local_rng.random() * 1.6
            patrol = {
                "from": {"x": float(base["x"]) - heading["x"] * patrol_len, "y": float(base["y"]) + ENEMY_CLEARANCE_Y, "z": float(base["z"]) - heading["z"] * patrol_len},
                "to": {"x": float(base["x"]) + heading["x"] * patrol_len, "y": float(base["y"]) + ENEMY_CLEARANCE_Y, "z": float(base["z"]) + heading["z"] * patrol_len},
            }
            builder.add_enemy(
                {"x": float(base["x"]), "y": float(base["y"]) + ENEMY_CLEARANCE_Y, "z": float(base["z"])},
                patrol,
                node_id,
                speed=0.95 + local_rng.random() * 0.25,
            )
            adjustments += 1
    elif density > upper:
        to_remove = clamp_int(math.ceil(total_events - (upper * path_len)), 0, 16)
        removable: list[tuple[int, str, str]] = []
        for bidx in range(len(bin_nodes)):
            bin_weight = _bin_event_total(bin_nodes[bidx])
            for node_id in bin_nodes[bidx]:
                rec = mapping_node.get(node_id) or {}
                for enemy_id in list(rec.get("enemies") or []):
                    removable.append((bin_weight * 100 + _node_event_total(node_id), node_id, str(enemy_id)))
        removable.sort(reverse=True)
        remove_ids: set[str] = set()
        for _, node_id, enemy_id in removable:
            if len(remove_ids) >= to_remove:
                break
            if enemy_id in remove_ids:
                continue
            remove_ids.add(enemy_id)
            rec = mapping_node.get(node_id) or {}
            rec["enemies"] = [eid for eid in (rec.get("enemies") or []) if str(eid) != enemy_id]
            adjustments += 1
        if remove_ids:
            level["enemies"] = [enemy for enemy in (level.get("enemies") or []) if str(enemy.get("id")) not in remove_ids]

    if adjustments > 0:
        stats = (((level.get("meta") or {}).get("component_generation") or {}).get("selection_stats") or {})
        stats["event_pacing_adjustments"] = int(stats.get("event_pacing_adjustments", 0)) + int(adjustments)
    return adjustments


def generate_level_constraint_based(etg: dict[str, Any], config: dict[str, Any], rng: Mulberry32) -> dict[str, Any]:
    return generate_level_incremental(
        etg,
        config,
        rng,
        validate_local_placement=None,
        mode_name="constraint_based",
    )


def _ga_topology_options(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "maxTime": config.get("gaTopologyMaxTime", config.get("topologyMaxTime")),
        "maxStates": int(config.get("gaTopologyMaxStates", config.get("topologyMaxStates", 450000))),
        "maxJumpOffsets": int(config.get("gaTopologyMaxJumpOffsets", config.get("topologyMaxJumpOffsets", 1400))),
        "maxGroundDistance": config.get("gaTopologyMaxGroundDistance", config.get("topologyMaxGroundDistance")),
        "maxJumpDistance": config.get("gaTopologyMaxJumpDistance", config.get("topologyMaxJumpDistance")),
        "allowJump": bool(config.get("gaTopologyAllowJump", config.get("topologyAllowJump", True))),
        "allowDrop": bool(config.get("gaTopologyAllowDrop", config.get("topologyAllowDrop", True))),
        "maxWallTimeSec": float(config.get("gaTopologyMaxWallTimeSec", config.get("topologyMaxWallTimeSec", 8.0))),
    }


def _ga_random_phenotype(rng: Mulberry32, config: dict[str, Any], *, safe: bool = False) -> dict[str, Any]:
    if safe:
        return {
            "geo_seed": int(math.floor(rng.random() * 4294967296.0)) & 0xFFFFFFFF,
            "sector_count": clamp_int(config.get("sectorCount", 8) + rand_range(rng, -1.0, 2.0), 6, 20),
            "max_attempts": clamp_int(config.get("maxAttempts", 28) + rand_range(rng, 4.0, 14.0), 14, 72),
            "safety_margin": clamp(float(config.get("safetyMargin", 1.0)) + rand_range(rng, 0.0, 0.45), 0.55, 2.5),
            "heading_jitter": clamp(float(config.get("headingJitterRange", 0.35)) + rand_range(rng, -0.08, 0.08), 0.08, 0.55),
            "lateral_jitter_min": clamp(float(config.get("lateralJitterMin", 1.0)) + rand_range(rng, -0.15, 0.15), 0.2, 1.8),
            "lateral_jitter_max": clamp(float(config.get("lateralJitterMax", 2.2)) + rand_range(rng, -0.2, 0.2), 0.6, 2.8),
        }
    return {
        "geo_seed": int(math.floor(rng.random() * 4294967296.0)) & 0xFFFFFFFF,
        "sector_count": clamp_int(config.get("sectorCount", 8) + rand_range(rng, -4.0, 6.0), 4, 32),
        "max_attempts": clamp_int(config.get("maxAttempts", 28) + rand_range(rng, -10.0, 16.0), 8, 80),
        "safety_margin": clamp(float(config.get("safetyMargin", 1.0)) + rand_range(rng, -0.45, 0.65), 0.35, 3.0),
        "heading_jitter": clamp(float(config.get("headingJitterRange", 0.35)) + rand_range(rng, -0.16, 0.22), 0.05, 0.95),
        "lateral_jitter_min": clamp(float(config.get("lateralJitterMin", 1.0)) + rand_range(rng, -0.5, 0.4), 0.05, 2.6),
        "lateral_jitter_max": clamp(float(config.get("lateralJitterMax", 2.2)) + rand_range(rng, -0.55, 0.7), 0.3, 4.2),
    }


def _ga_normalize_phenotype(ph: dict[str, Any]) -> dict[str, Any]:
    out = dict(ph)
    out["geo_seed"] = int(out.get("geo_seed", 1)) & 0xFFFFFFFF
    out["sector_count"] = clamp_int(out.get("sector_count", 8), 4, 32)
    out["max_attempts"] = clamp_int(out.get("max_attempts", 28), 8, 80)
    out["safety_margin"] = clamp(float(out.get("safety_margin", 1.0)), 0.35, 3.0)
    out["heading_jitter"] = clamp(float(out.get("heading_jitter", 0.35)), 0.05, 0.95)
    out["lateral_jitter_min"] = clamp(float(out.get("lateral_jitter_min", 1.0)), 0.05, 2.6)
    out["lateral_jitter_max"] = clamp(float(out.get("lateral_jitter_max", 2.2)), 0.3, 4.2)
    if out["lateral_jitter_max"] < out["lateral_jitter_min"]:
        out["lateral_jitter_min"], out["lateral_jitter_max"] = out["lateral_jitter_max"], out["lateral_jitter_min"]
    return out


def _ga_decode_constraint_level(etg: dict[str, Any], base_config: dict[str, Any], phenotype: dict[str, Any]) -> dict[str, Any]:
    ph = _ga_normalize_phenotype(phenotype)
    cfg = dict(base_config)
    cfg["generatorMode"] = "constraint_based"
    cfg["sectorCount"] = ph["sector_count"]
    cfg["maxAttempts"] = ph["max_attempts"]
    cfg["safetyMargin"] = ph["safety_margin"]
    cfg["headingJitterRange"] = ph["heading_jitter"]
    cfg["lateralJitterMin"] = ph["lateral_jitter_min"]
    cfg["lateralJitterMax"] = ph["lateral_jitter_max"]
    cfg["seed"] = f"{base_config.get('seed', 'ga')}_ga_{ph['geo_seed']}"
    geo_rng = Mulberry32(int(ph["geo_seed"]))
    return generate_level_incremental(etg, cfg, geo_rng, validate_local_placement=None, mode_name="constraint_based")


def _ga_tournament_pick(rng: Mulberry32, population: list[dict[str, Any]], k: int) -> dict[str, Any]:
    best = None
    n = len(population)
    kk = max(1, min(int(k), n))
    for _ in range(kk):
        cand = population[int(math.floor(rng.random() * n))]
        if best is None or float(cand["fitness"]) > float(best["fitness"]):
            best = cand
    return best or population[0]


def _ga_crossover(rng: Mulberry32, a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    alpha = rng.random()
    child = {
        "geo_seed": int(a["geo_seed"]) if rng.random() < 0.5 else int(b["geo_seed"]),
        "sector_count": int(round(float(a["sector_count"]) * alpha + float(b["sector_count"]) * (1.0 - alpha))),
        "max_attempts": int(round(float(a["max_attempts"]) * alpha + float(b["max_attempts"]) * (1.0 - alpha))),
        "safety_margin": float(a["safety_margin"]) * alpha + float(b["safety_margin"]) * (1.0 - alpha),
        "heading_jitter": float(a["heading_jitter"]) * alpha + float(b["heading_jitter"]) * (1.0 - alpha),
        "lateral_jitter_min": float(a["lateral_jitter_min"]) * alpha + float(b["lateral_jitter_min"]) * (1.0 - alpha),
        "lateral_jitter_max": float(a["lateral_jitter_max"]) * alpha + float(b["lateral_jitter_max"]) * (1.0 - alpha),
    }
    return _ga_normalize_phenotype(child)


def _ga_mutate(rng: Mulberry32, ph: dict[str, Any], mutation_rate: float) -> dict[str, Any]:
    out = dict(ph)
    r = clamp(float(mutation_rate), 0.0, 1.0)
    if rng.random() < r:
        out["geo_seed"] = (int(out["geo_seed"]) ^ int(math.floor(rng.random() * 4294967296.0))) & 0xFFFFFFFF
    if rng.random() < r:
        out["sector_count"] = int(out["sector_count"]) + clamp_int(rand_range(rng, -4.0, 4.0), -4, 4)
    if rng.random() < r:
        out["max_attempts"] = int(out["max_attempts"]) + clamp_int(rand_range(rng, -8.0, 12.0), -8, 12)
    if rng.random() < r:
        out["safety_margin"] = float(out["safety_margin"]) + rand_range(rng, -0.25, 0.25)
    if rng.random() < r:
        out["heading_jitter"] = float(out["heading_jitter"]) + rand_range(rng, -0.12, 0.12)
    if rng.random() < r:
        out["lateral_jitter_min"] = float(out["lateral_jitter_min"]) + rand_range(rng, -0.25, 0.25)
    if rng.random() < r:
        out["lateral_jitter_max"] = float(out["lateral_jitter_max"]) + rand_range(rng, -0.35, 0.35)
    return _ga_normalize_phenotype(out)


def _ga_fitness_from_report(report: dict[str, Any]) -> tuple[float, dict[str, float]]:
    metrics = report.get("metrics") or {}
    playability = float((metrics.get("playability") or {}).get("score", 0.0))
    etg_fidelity = float((metrics.get("etg_fidelity") or {}).get("score", 0.0))
    controllability = float((metrics.get("controllability") or {}).get("score", 0.0))
    fun_proxy = float((metrics.get("fun_proxy") or {}).get("score", 0.0))
    topology = report.get("topology") or {}
    search = topology.get("search") if isinstance(topology.get("search"), dict) else {}
    coverage = topology.get("coverage_search") if isinstance(topology.get("coverage_search"), dict) else {}
    key_lock = topology.get("key_lock_order") if isinstance(topology.get("key_lock_order"), dict) else {}
    goal_time = float(search.get("goal_time", 0.0) or 0.0)
    coverage_time = float(coverage.get("max_time_used", 0.0) or 0.0)
    truncated = bool(search.get("partial") or coverage.get("truncated"))
    lock_seen = bool(key_lock.get("lock_seen"))
    key_seen_before_lock = bool(key_lock.get("key_seen_before_lock"))
    missing_key_node = bool(key_lock.get("missing_key_node"))
    time_signal = goal_time if playability > 0.5 else coverage_time
    time_penalty = min(0.12, (time_signal / 220.0) * 0.05 + (0.04 if truncated else 0.0))
    key_route_penalty = 0.0
    if missing_key_node:
        key_route_penalty += 0.06
    if lock_seen and (not key_seen_before_lock):
        key_route_penalty += 0.04
    score = 0.60 * playability + 0.25 * etg_fidelity + 0.10 * controllability + 0.05 * fun_proxy - time_penalty - key_route_penalty
    return score, {
        "playability": playability,
        "etg_fidelity": etg_fidelity,
        "controllability": controllability,
        "fun_proxy": fun_proxy,
        "time_penalty": time_penalty,
        "key_route_penalty": key_route_penalty,
    }


def generate_level_ga_baseline(etg: dict[str, Any], config: dict[str, Any], rng: Mulberry32) -> dict[str, Any]:
    from .evaluate import evaluate_level_quality

    pop_size = clamp_int(config.get("gaPopulation", 12), 2, 48)
    generations = clamp_int(config.get("gaGenerations", 8), 1, 40)
    elite_ratio = clamp(float(config.get("gaEliteRatio", 0.25)), 0.05, 0.6)
    mutation_rate = clamp(float(config.get("gaMutationRate", 0.25)), 0.01, 0.95)
    tournament_size = clamp_int(config.get("gaTournamentSize", 3), 2, 12)
    safe_init_ratio = clamp(float(config.get("gaSafeInitRatio", 0.5)), 0.0, 1.0)
    elite_count = max(1, min(pop_size, int(round(pop_size * elite_ratio))))

    topo_opts = _ga_topology_options(config)

    def evaluate_individual(ph: dict[str, Any]) -> dict[str, Any]:
        level = _ga_decode_constraint_level(etg, config, ph)
        report = evaluate_level_quality(level, etg, {"topology": topo_opts})
        fit, comps = _ga_fitness_from_report(report)
        return {
            "phenotype": _ga_normalize_phenotype(ph),
            "fitness": fit,
            "fitness_components": comps,
            "level": level,
            "report": report,
        }

    safe_count = clamp_int(round(pop_size * safe_init_ratio), 0, pop_size)
    population = [
        _ga_random_phenotype(rng, config, safe=(i < safe_count))
        for i in range(pop_size)
    ]
    best: dict[str, Any] | None = None
    history: list[dict[str, Any]] = []

    for gen in range(generations):
        scored = [evaluate_individual(ph) for ph in population]
        scored.sort(key=lambda x: float(x["fitness"]), reverse=True)
        if best is None or float(scored[0]["fitness"]) > float(best["fitness"]):
            best = scored[0]

        mean_f = sum(float(s["fitness"]) for s in scored) / max(1, len(scored))
        history.append(
            {
                "generation": gen,
                "best_fitness": float(scored[0]["fitness"]),
                "mean_fitness": mean_f,
                "best_overall_score": float(((scored[0]["report"].get("metrics") or {}).get("overall_score", 0.0))),
            }
        )

        if gen >= generations - 1:
            break

        next_population: list[dict[str, Any]] = [dict(scored[i]["phenotype"]) for i in range(elite_count)]
        while len(next_population) < pop_size:
            p1 = _ga_tournament_pick(rng, scored, tournament_size)["phenotype"]
            p2 = _ga_tournament_pick(rng, scored, tournament_size)["phenotype"]
            child = _ga_crossover(rng, p1, p2)
            child = _ga_mutate(rng, child, mutation_rate)
            next_population.append(child)
        population = next_population

    assert best is not None
    level_best = best["level"]
    level_best.setdefault("meta", {})
    level_best["meta"]["generator_mode"] = "ga_baseline"
    level_best["meta"]["ga"] = {
        "population": pop_size,
        "generations": generations,
        "elite_count": elite_count,
        "mutation_rate": mutation_rate,
        "tournament_size": tournament_size,
        "fitness": float(best["fitness"]),
        "fitness_components": best.get("fitness_components") or {},
        "best_overall_score": float(((best.get("report") or {}).get("metrics") or {}).get("overall_score", 0.0)),
        "best_phenotype": best["phenotype"],
        "history": history,
        "decoder": "constraint_based",
        "topology_options": topo_opts,
    }
    return level_best


def generate_level(etg: dict[str, Any], config: dict[str, Any], rng: Mulberry32, validate_local_placement: Callable[[dict[str, Any]], dict[str, Any]] | None = None) -> dict[str, Any]:
    mode = str(config.get("generatorMode") or config.get("generator_mode") or "").strip()
    if not mode or mode in {"hdpcg_incremental", "incremental"}:
        level = generate_level_incremental(etg, config, rng, validate_local_placement)
        if bool(config.get("mainKeyLockRoutePass", True)):
            route_cfg = dict(config)
            route_cfg["baselineKeyLockRoutePass"] = True
            route_cfg["baselineRouteRepairBudget"] = clamp_int(config.get("mainRouteRepairBudget", 2), 0, 12)
            route_cfg["baselineRequireKeyNodeCoverage"] = bool(config.get("baselineRequireKeyNodeCoverage", True))
            route_cfg["baselineConnectivityBridgeMaxGap"] = float(config.get("baselineConnectivityBridgeMaxGap", 18.0))
            route_cfg["baselineKeyDetourMaxExtraRatio"] = float(config.get("baselineKeyDetourMaxExtraRatio", 0.45))
            route_repair = enforce_key_lock_route_coverage(level, etg, route_cfg, rng)
            stats = (((level.get("meta") or {}).get("component_generation") or {}).get("selection_stats") or {})
            stats["main_route_repairs"] = int(stats.get("main_route_repairs", 0)) + int(route_repair.get("required_key_path_repairs", 0))
        apply_main_event_pacing(level, etg, config, rng)
        _ensure_key_lock_consistency(level, etg, rng)
        return level
    if mode in {"constraint_based", "constraint"}:
        level = generate_level_constraint_based(etg, config, rng)
        enforce_key_lock_route_coverage(level, etg, config, rng)
        _ensure_key_lock_consistency(level, etg, rng)
        return level
    if mode in {"ga_baseline", "ga"}:
        level = generate_level_ga_baseline(etg, config, rng)
        enforce_key_lock_route_coverage(level, etg, config, rng)
        _ensure_key_lock_consistency(level, etg, rng)
        return level
    if mode in {"cpsat_baseline", "cpsat", "cp_sat"}:
        from .cpsat_baseline import generate_level_cpsat_baseline

        level = generate_level_cpsat_baseline(etg, config, rng)
        _ensure_key_lock_consistency(level, etg, rng)
        return level
    level = generate_level_lane(etg, config, rng)
    if bool(config.get("laneEnsureRequiredKeyPaths", True)):
        enforce_key_lock_route_coverage(level, etg, config, rng)
    _ensure_key_lock_consistency(level, etg, rng)
    return level

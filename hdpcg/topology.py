"""Topology validation: local hook + global 5D search check and observed ETG."""

from __future__ import annotations

import math
from collections import deque
from typing import Any

from .etg_core import NODE_TYPES, compute_canonical_route
from .hdpcg_bfs import (
    build_ground_offsets,
    build_jump_offsets,
    build_physics_profile,
    cell_key,
    collect_neighbors,
    compute_reachable,
    search_shortest_goal_path,
    state_key,
)
from .hdpcg_grid import build_hdpcg_model, to_cell_coord
from .paper_config import load_paper_config


def _is_lock(node: dict[str, Any]) -> bool:
    types = node.get("types") if isinstance(node.get("types"), list) and node.get("types") else ([node.get("type")] if node.get("type") else [])
    return "Lock" in types


def _is_key(node: dict[str, Any]) -> bool:
    types = node.get("types") if isinstance(node.get("types"), list) and node.get("types") else ([node.get("type")] if node.get("type") else [])
    return "Key" in types


def _clamp_int(value: Any, min_value: int, max_value: int) -> int:
    try:
        n = int(round(float(value)))
    except Exception:
        n = min_value
    return max(min_value, min(max_value, n))


def _merge_bounds(a: dict[str, Any] | None, b: dict[str, Any] | None) -> dict[str, Any] | None:
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


def _point_bounds(pos: dict[str, Any] | None, eps: float = 0.01) -> dict[str, Any] | None:
    if not pos:
        return None
    try:
        x, y, z = float(pos["x"]), float(pos["y"]), float(pos["z"])
    except Exception:
        return None
    return {
        "min": {"x": x - eps, "y": y - eps, "z": z - eps},
        "max": {"x": x + eps, "y": y + eps, "z": z + eps},
    }


def _union_bounds_from_delta(bounds_delta: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(bounds_delta, dict):
        return None
    out = None
    for b in bounds_delta.values():
        if not isinstance(b, dict) or "min" not in b or "max" not in b:
            continue
        out = _merge_bounds(out, b)
    return out


def _bounds_to_cell_box(bounds: dict[str, Any] | None, cell_size: float, padding_cells: int) -> dict[str, Any] | None:
    if not bounds:
        return None
    return {
        "min": {
            "x": int(math.floor(float(bounds["min"]["x"]) / cell_size) - padding_cells),
            "y": int(math.floor(float(bounds["min"]["y"]) / cell_size) - padding_cells),
            "z": int(math.floor(float(bounds["min"]["z"]) / cell_size) - padding_cells),
        },
        "max": {
            "x": int(math.ceil(float(bounds["max"]["x"]) / cell_size) + padding_cells),
            "y": int(math.ceil(float(bounds["max"]["y"]) / cell_size) + padding_cells),
            "z": int(math.ceil(float(bounds["max"]["z"]) / cell_size) + padding_cells),
        },
    }


def _within_box(cell: dict[str, int], box: dict[str, Any]) -> bool:
    return (
        cell["x"] >= box["min"]["x"]
        and cell["x"] <= box["max"]["x"]
        and cell["y"] >= box["min"]["y"]
        and cell["y"] <= box["max"]["y"]
        and cell["z"] >= box["min"]["z"]
        and cell["z"] <= box["max"]["z"]
    )


def _nearest_walkable_cell_in_box(
    model: Any, cell: dict[str, int] | None, t: int, phase: int, box: dict[str, Any], max_radius: int = 6
) -> dict[str, int] | None:
    if not cell or not _within_box(cell, box):
        return None
    snapped = model.findNearestWalkable(cell, t, phase, max_radius)
    if not snapped:
        return None
    if not _within_box(snapped, box):
        return None
    return snapped


def _manhattan_distance3(a: dict[str, int], b: dict[str, int]) -> int:
    return abs(a["x"] - b["x"]) + abs(a["y"] - b["y"]) + abs(a["z"] - b["z"])


def _build_sibling_tolerance_set(etg: dict[str, Any] | None, parent_id: str, exclude_child_id: str) -> set[str]:
    out: set[str] = set()
    for e in (etg.get("edges") if etg else []) or []:
        if not isinstance(e, dict):
            continue
        a, b = e.get("from"), e.get("to")
        if a == parent_id and b and b != exclude_child_id:
            out.add(str(b))
        if b == parent_id and a and a != exclude_child_id:
            out.add(str(a))
    return out


def _bfs_reachable_local(
    model: Any,
    from_cell: dict[str, int],
    to_cell: dict[str, int],
    local_box: dict[str, Any],
    max_time: int,
    start_phase: int,
    allow_jump: bool,
    allow_drop: bool,
    max_jump_offsets: int,
    walkable_tolerance_cells: int = 0,
) -> dict[str, Any]:
    start = {
        "x": from_cell["x"],
        "y": from_cell["y"],
        "z": from_cell["z"],
        "t": 0,
        "phase": _clamp_int(start_phase, 0, max(0, int(model.phaseCount) - 1)),
    }
    goal_id = cell_key(to_cell)
    vis = {state_key(start)}
    q = deque([start])

    physics = build_physics_profile(model)
    ground = build_ground_offsets(physics["maxGroundDistance"])
    jumps = (
        build_jump_offsets(
            physics["maxJumpDistance"],
            int(physics["maxJumpUp"]),
            int(physics["maxJumpDown"]),
            max_jump_offsets,
        )
        if allow_jump
        else []
    )

    expanded = 0
    while q:
        s = q.popleft()
        expanded += 1
        if cell_key(s) == goal_id:
            return {"reached": True, "expanded": expanded, "visited": len(vis)}
        for n in collect_neighbors(
            s,
            model,
            physics,
            ground,
            jumps,
            allow_jump,
            allow_drop,
            max_time,
            max(0, int(walkable_tolerance_cells)),
        ):
            if not _within_box(n, local_box):
                continue
            k = state_key(n)
            if k in vis:
                continue
            vis.add(k)
            q.append(n)
    return {"reached": False, "expanded": expanded, "visited": len(vis)}


def _is_lock_node(etg: dict[str, Any] | None, node_id: str) -> bool:
    if not etg:
        return False
    node = next((n for n in (etg.get("nodes") or []) if n.get("id") == node_id), None)
    return _is_lock(node or {})


def _validate_lock_gate_if_present(
    *,
    level: dict[str, Any],
    etg: dict[str, Any] | None,
    from_id: str,
    to_id: str,
    model: Any,
    local_box: dict[str, Any],
    max_time: int,
    allow_jump: bool,
    allow_drop: bool,
    max_jump_offsets: int,
) -> dict[str, Any]:
    candidates = {c for c in (from_id, to_id) if c}
    for node_id, anchor in (level.get("anchors") or {}).items():
        gate = (anchor or {}).get("gate")
        if not gate or not gate.get("pos"):
            continue
        gc = to_cell_coord(gate["pos"], model.cellSize)
        if _within_box(gc, local_box):
            candidates.add(node_id)

    for node_id in candidates:
        if not _is_lock_node(etg, node_id):
            continue
        anchor = (level.get("anchors") or {}).get(node_id) or {}
        ports = anchor.get("portsByNeighbor")
        if not isinstance(ports, dict) or len(ports) != 2:
            continue
        port_ids = list(ports.keys())
        pa, pb = ports.get(port_ids[0]), ports.get(port_ids[1])
        if not pa or not pb:
            continue
        a_cell = _nearest_walkable_cell_in_box(model, to_cell_coord(pa, model.cellSize), 0, 0, local_box)
        b_cell = _nearest_walkable_cell_in_box(model, to_cell_coord(pb, model.cellSize), 0, 0, local_box)
        if not a_cell or not b_cell:
            continue

        blocked = _bfs_reachable_local(
            model, a_cell, b_cell, local_box, max_time, 0, allow_jump, allow_drop, max_jump_offsets
        )
        if blocked["reached"]:
            return {"ok": False, "reason": "lock_gate_leak_no_key", "lockNodeId": node_id}

        open_with_keys = _bfs_reachable_local(
            model,
            a_cell,
            b_cell,
            local_box,
            max_time,
            max(0, int(model.phaseCount) - 1),
            allow_jump,
            allow_drop,
            max_jump_offsets,
        )
        if not open_with_keys["reached"]:
            return {"ok": False, "reason": "lock_gate_blocks_with_all_keys", "lockNodeId": node_id}

        neigh_a, neigh_b = port_ids[0], port_ids[1]
        anchor_a = (level.get("anchors") or {}).get(neigh_a)
        anchor_b = (level.get("anchors") or {}).get(neigh_b)
        if anchor_a and anchor_b:
            ac = _nearest_walkable_cell_in_box(
                model,
                to_cell_coord(anchor_a.get("exit") or anchor_a.get("entry"), model.cellSize),
                0,
                0,
                local_box,
            )
            bc = _nearest_walkable_cell_in_box(
                model,
                to_cell_coord(anchor_b.get("entry") or anchor_b.get("exit"), model.cellSize),
                0,
                0,
                local_box,
            )
            if ac and bc:
                bypass = _bfs_reachable_local(
                    model, ac, bc, local_box, max_time, 0, allow_jump, allow_drop, max_jump_offsets
                )
                if bypass["reached"]:
                    return {
                        "ok": False,
                        "reason": "lock_bypassed_between_neighbors_no_key",
                        "lockNodeId": node_id,
                        "neighbors": [neigh_a, neigh_b],
                    }
                should_open = _bfs_reachable_local(
                    model,
                    ac,
                    bc,
                    local_box,
                    max_time,
                    max(0, int(model.phaseCount) - 1),
                    allow_jump,
                    allow_drop,
                    max_jump_offsets,
                )
                if not should_open["reached"]:
                    return {
                        "ok": False,
                        "reason": "lock_still_blocks_between_neighbors_with_all_keys",
                        "lockNodeId": node_id,
                        "neighbors": [neigh_a, neigh_b],
                    }

    return {"ok": True, "warnings": []}


def _bfs_early_stop_local(
    *,
    model: Any,
    from_cell: dict[str, int],
    to_cell: dict[str, int],
    local_box: dict[str, Any],
    forbidden_by_cell: dict[str, set[str]],
    sibling_tolerance_node_ids: set[str],
    tolerance_radius_cells: int,
    max_time: int,
    max_states: int,
    max_queue: int,
    max_jump_offsets: int,
    allow_jump: bool,
    allow_drop: bool,
) -> dict[str, Any]:
    start = {"x": from_cell["x"], "y": from_cell["y"], "z": from_cell["z"], "t": 0, "phase": 0}
    goal_id = cell_key(to_cell)
    vis = {state_key(start)}
    q = deque([start])

    physics = build_physics_profile(model)
    ground = build_ground_offsets(physics["maxGroundDistance"])
    jumps = (
        build_jump_offsets(
            physics["maxJumpDistance"],
            int(physics["maxJumpUp"]),
            int(physics["maxJumpDown"]),
            max_jump_offsets,
        )
        if allow_jump
        else []
    )

    reached_target = False
    expanded = 0
    warnings: list[str] = []
    warned_nodes: set[str] = set()

    while q:
        s = q.popleft()
        expanded += 1
        if expanded > max_states or len(q) > max_queue:
            return {
                "ok": False,
                "reason": "budget_exceeded",
                "reachedTarget": reached_target,
                "expanded": expanded,
                "visitedCount": len(vis),
                "warnings": warnings,
            }

        cid = cell_key(s)
        if cid in forbidden_by_cell:
            hit = forbidden_by_cell[cid]
            not_tolerated = []
            tolerated = []
            for node_id in hit:
                ok_sibling = (
                    node_id in sibling_tolerance_node_ids
                    and _manhattan_distance3(s, from_cell) <= tolerance_radius_cells
                )
                if ok_sibling:
                    tolerated.append(node_id)
                else:
                    not_tolerated.append(node_id)
            if not_tolerated:
                return {
                    "ok": False,
                    "reason": "forbidden_reached",
                    "forbiddenNodeIds": not_tolerated,
                    "toleratedNodeIds": tolerated,
                    "reachedTarget": reached_target,
                    "expanded": expanded,
                    "visitedCount": len(vis),
                    "warnings": warnings,
                }
            for node_id in tolerated:
                if node_id in warned_nodes:
                    continue
                warned_nodes.add(node_id)
                warnings.append(f"tolerated_sibling_touch:{node_id}")

        if cid == goal_id:
            reached_target = True

        for n in collect_neighbors(
            s,
            model,
            physics,
            ground,
            jumps,
            allow_jump,
            allow_drop,
            max_time,
            0,
        ):
            if not _within_box(n, local_box):
                continue
            k = state_key(n)
            if k in vis:
                continue
            vis.add(k)
            q.append(n)

    if not reached_target:
        return {
            "ok": False,
            "reason": "target_not_reachable",
            "expanded": expanded,
            "visitedCount": len(vis),
            "warnings": warnings,
        }
    return {
        "ok": True,
        "reachedTarget": reached_target,
        "expanded": expanded,
        "visitedCount": len(vis),
        "warnings": warnings,
    }


def validate_local_topology(options: dict[str, Any]) -> dict[str, Any]:
    paper = load_paper_config()
    state_defaults = paper["state_model"]
    validation_defaults = paper["validation"]
    local_defaults = validation_defaults["local"]
    level = options.get("level")
    etg = options.get("etg")
    from_id = options.get("fromId")
    to_id = options.get("toId")
    bounds_delta = options.get("boundsDelta")

    policy = str(options.get("extraConnectivityPolicy", local_defaults["policy"])).strip()
    cell_size = float(options.get("cellSize", state_defaults["cell_size"]))
    time_step = float(options.get("timeStep", state_defaults["time_step_seconds"]))
    model_padding = int(options.get("modelPadding", state_defaults["local_model_padding_cells"]))
    local_padding_cells = _clamp_int(options.get("localPaddingCells", state_defaults["local_padding_cells"]), 0, 18)
    fast_budget = bool(options.get("allowFastBudget", False))
    min_time = 10 if fast_budget else 30
    min_states = 3_000 if fast_budget else 10_000
    min_queue = 2_500 if fast_budget else 10_000
    min_jump_offsets = 80 if fast_budget else 200
    max_time = _clamp_int(options.get("maxTime", local_defaults["max_time"]), min_time, 500)
    max_states = _clamp_int(options.get("maxStates", local_defaults["max_states"]), min_states, 450_000)
    max_queue = _clamp_int(options.get("maxQueue", local_defaults["max_queue"]), min_queue, 350_000)
    max_jump_offsets = _clamp_int(options.get("maxJumpOffsets", local_defaults["max_jump_offsets"]), min_jump_offsets, 6000)
    tolerance_radius_cells = _clamp_int(
        options.get("toleranceRadiusCells", options.get("toleranceRadius", state_defaults["sibling_tolerance_radius_cells"])),
        0,
        12,
    )
    allow_sibling_tolerance = bool(options.get("allowSiblingTolerance", local_defaults["allow_sibling_tolerance"]))
    allow_jump = bool(options.get("allowJump", validation_defaults["allow_jump"]))
    allow_drop = bool(options.get("allowDrop", validation_defaults["allow_drop"]))
    disable_forbidden_markers = bool(options.get("disableForbiddenMarkers", False))
    disable_lock_semantics = bool(options.get("disableLockSemantics", False))

    if not level or not from_id or not to_id:
        return {"ok": True, "warnings": ["validator_skipped_missing_args"]}

    from_anchor = (level.get("anchors") or {}).get(from_id)
    to_anchor = (level.get("anchors") or {}).get(to_id)
    if not from_anchor or not to_anchor:
        return {"ok": False, "reason": "missing_anchors"}

    union_bounds = _union_bounds_from_delta(bounds_delta)
    if union_bounds is None:
        return {"ok": True}
    union_bounds = _merge_bounds(union_bounds, _point_bounds(from_anchor.get("entry")))
    union_bounds = _merge_bounds(union_bounds, _point_bounds(from_anchor.get("exit")))
    union_bounds = _merge_bounds(union_bounds, _point_bounds(to_anchor.get("entry")))
    union_bounds = _merge_bounds(union_bounds, _point_bounds(to_anchor.get("exit")))

    local_box = _bounds_to_cell_box(union_bounds, cell_size, local_padding_cells)
    if not local_box:
        return {"ok": True}

    model = build_hdpcg_model(
        level,
        {
            "cellSize": cell_size,
            "timeStep": time_step,
            "padding": model_padding,
            "maxTimeHorizon": options.get("maxTimeHorizon", state_defaults["max_time_horizon"]),
            "maxPeriodTicks": options.get("maxPeriodTicks", state_defaults["max_period_ticks"]),
        },
    )
    allowed = {str(from_id), str(to_id)}
    sibling_tolerance_node_ids = (
        _build_sibling_tolerance_set(etg, str(from_id), str(to_id))
        if (policy == "strict_1hop" and allow_sibling_tolerance)
        else set()
    )

    from_cell = _nearest_walkable_cell_in_box(
        model, to_cell_coord(from_anchor.get("exit") or from_anchor.get("entry"), cell_size), 0, 0, local_box
    )
    to_cell = _nearest_walkable_cell_in_box(
        model, to_cell_coord(to_anchor.get("entry") or to_anchor.get("exit"), cell_size), 0, 0, local_box
    )
    if not from_cell or not to_cell:
        return {"ok": False, "reason": "no_walkable_marker"}

    forbidden_by_cell: dict[str, set[str]] = {}
    if not disable_forbidden_markers:
        etg_node_ids = {n.get("id") for n in (etg.get("nodes") or [])} if etg else None
        for node_id, anchor in (level.get("anchors") or {}).items():
            if node_id in allowed:
                continue
            if etg_node_ids is not None and node_id not in etg_node_ids:
                continue
            cells = []
            if anchor.get("entry"):
                c = _nearest_walkable_cell_in_box(model, to_cell_coord(anchor["entry"], cell_size), 0, 0, local_box)
                if c:
                    cells.append(c)
            if anchor.get("exit"):
                c = _nearest_walkable_cell_in_box(model, to_cell_coord(anchor["exit"], cell_size), 0, 0, local_box)
                if c:
                    cells.append(c)
            for c in cells:
                cid = cell_key(c)
                forbidden_by_cell.setdefault(cid, set()).add(str(node_id))

    result = _bfs_early_stop_local(
        model=model,
        from_cell=from_cell,
        to_cell=to_cell,
        local_box=local_box,
        forbidden_by_cell=forbidden_by_cell,
        sibling_tolerance_node_ids=sibling_tolerance_node_ids,
        tolerance_radius_cells=tolerance_radius_cells,
        max_time=max_time,
        max_states=max_states,
        max_queue=max_queue,
        max_jump_offsets=max_jump_offsets,
        allow_jump=allow_jump,
        allow_drop=allow_drop,
    )
    if not result.get("ok"):
        return result

    if not disable_lock_semantics:
        lock_check = _validate_lock_gate_if_present(
            level=level,
            etg=etg,
            from_id=str(from_id),
            to_id=str(to_id),
            model=model,
            local_box=local_box,
            max_time=max_time,
            allow_jump=allow_jump,
            allow_drop=allow_drop,
            max_jump_offsets=max_jump_offsets,
        )
        if not lock_check.get("ok"):
            return lock_check
        if lock_check.get("warnings"):
            result["warnings"] = [*(result.get("warnings") or []), *lock_check.get("warnings", [])]
    return result


def _levenshtein(a: list[str], b: list[str]) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    dp = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev = dp[0]
        dp[0] = i
        for j, cb in enumerate(b, 1):
            cur = dp[j]
            if ca == cb:
                dp[j] = prev
            else:
                dp[j] = 1 + min(prev, dp[j], dp[j - 1])
            prev = cur
    return dp[-1]


def _directed_edges(edges: list[dict[str, Any]]) -> set[tuple[str, str]]:
    out = set()
    for e in edges or []:
        a, b = e.get("from"), e.get("to")
        if not a or not b:
            continue
        out.add((str(a), str(b)))
    return out


def build_node_markers(model: Any, level: dict[str, Any], etg: dict[str, Any] | None) -> dict[str, set[str]]:
    marker_by_node: dict[str, set[str]] = {}
    etg_ids = {n.get("id") for n in (etg.get("nodes") or [])} if etg else set(level.get("anchors", {}).keys())
    for node_id, anchor in (level.get("anchors") or {}).items():
        if node_id not in etg_ids:
            continue
        cells = []
        for key in ("entry", "exit"):
            pos = anchor.get(key)
            if not pos:
                continue
            c = to_cell_coord(pos, model.cellSize)
            snapped = model.findNearestWalkable(c, 0, 0)
            if snapped:
                cells.append(cell_key(snapped))
            else:
                cells.append(cell_key(c))
        if cells:
            marker_by_node[node_id] = set(cells)
    return marker_by_node


def project_path_to_node_sequence(path: list[dict[str, int]], marker_by_node: dict[str, set[str]]) -> list[str]:
    seq: list[str] = []
    for s in path:
        cid = cell_key(s)
        hit = None
        for node_id, markers in marker_by_node.items():
            if cid in markers:
                hit = node_id
                break
        if not hit:
            continue
        if not seq or seq[-1] != hit:
            seq.append(hit)
    return seq


def _marker_index(marker_by_node: dict[str, set[str]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for node_id, cells in marker_by_node.items():
        for cid in cells:
            out.setdefault(cid, set()).add(node_id)
    return out


def collect_node_first_hits(
    reachable_by_time_phase: list[list[set[str]]],
    marker_by_node: dict[str, set[str]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    idx = _marker_index(marker_by_node)
    first_hit: dict[str, dict[str, Any]] = {}
    timeline: list[dict[str, Any]] = []
    for t, by_phase in enumerate(reachable_by_time_phase):
        for p, cells in enumerate(by_phase):
            if not cells:
                continue
            touched: set[str] = set()
            for cid in cells:
                for nid in idx.get(cid, set()):
                    touched.add(nid)
                    if nid not in first_hit:
                        first_hit[nid] = {"time": t, "phase": p, "cell": cid}
            if touched:
                timeline.append({"time": t, "phase": p, "nodes": sorted(touched)})
    return first_hit, timeline


def _expected_node_order(etg_expected: dict[str, Any] | None) -> dict[str, int]:
    out: dict[str, int] = {}
    if not etg_expected:
        return out
    for i, n in enumerate(etg_expected.get("nodes") or []):
        nid = n.get("id")
        if nid:
            out[str(nid)] = i
    return out


def build_coverage_sequence(first_hit: dict[str, dict[str, Any]], etg_expected: dict[str, Any] | None) -> list[str]:
    order = _expected_node_order(etg_expected)
    items = list(first_hit.items())
    items.sort(
        key=lambda kv: (
            int(kv[1].get("time", 10**9)),
            int(kv[1].get("phase", 10**9)),
            int(order.get(kv[0], 10**9)),
            str(kv[0]),
        )
    )
    return [nid for nid, _ in items]


def build_observed_edges_from_expected(expected_etg: dict[str, Any] | None, observed_nodes: set[str], fallback_seq: list[str]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    if expected_etg and expected_etg.get("edges"):
        eid = 0
        for e in expected_etg.get("edges") or []:
            a, b = e.get("from"), e.get("to")
            if not a or not b:
                continue
            a, b = str(a), str(b)
            if a not in observed_nodes or b not in observed_nodes:
                continue
            edges.append(
                {
                    "id": e.get("id") or f"OE{eid}",
                    "from": a,
                    "to": b,
                    "length": e.get("length", 1),
                }
            )
            eid += 1
        seen = {(str(item["from"]), str(item["to"])) for item in edges}
        for a, b in zip(fallback_seq, fallback_seq[1:]):
            if a == b or (a, b) in seen:
                continue
            edges.append({"id": f"OX{eid}", "from": a, "to": b, "length": 1})
            seen.add((a, b))
            eid += 1
        return edges

    seen: set[tuple[str, str]] = set()
    eid = 0
    for i in range(len(fallback_seq) - 1):
        a, b = fallback_seq[i], fallback_seq[i + 1]
        if a == b:
            continue
        key = (a, b)
        if key in seen:
            continue
        seen.add(key)
        edges.append({"id": f"OE{eid}", "from": a, "to": b, "length": 1})
        eid += 1
    return edges


def build_observed_etg_from_coverage(
    expected_etg: dict[str, Any] | None,
    first_hit: dict[str, dict[str, Any]],
    node_seq: list[str],
) -> dict[str, Any]:
    def primary_type(src: dict[str, Any]) -> str:
        t = src.get("type")
        if isinstance(t, str) and t and t != "None":
            return t
        ts = src.get("types")
        if isinstance(ts, list) and ts:
            h = ts[0]
            if isinstance(h, str) and h:
                return h
        if isinstance(t, str) and t:
            return t
        return "None"

    expected_node_by_id = {n.get("id"): n for n in (expected_etg.get("nodes") or [])} if expected_etg else {}
    observed_nodes = set(node_seq)

    nodes = []
    for nid in node_seq:
        src = expected_node_by_id.get(nid, {})
        node = {
            "id": nid,
            "type": primary_type(src),
            "types": src.get("types", [src.get("type", "None")]),
            "intensity": src.get("intensity", 0.5),
        }
        if src.get("key_id"):
            node["key_id"] = src.get("key_id")
        if src.get("requires_key_id"):
            node["requires_key_id"] = src.get("requires_key_id")
        if src.get("lock_id"):
            node["lock_id"] = src.get("lock_id")
        hit = first_hit.get(nid)
        if hit:
            node["first_hit"] = {"time": hit.get("time"), "phase": hit.get("phase"), "cell": hit.get("cell")}
        nodes.append(node)

    edges = build_observed_edges_from_expected(expected_etg, observed_nodes, node_seq)

    return {
        "version": 2,
        "nodes": nodes,
        "edges": edges,
        "meta": {"source": "global_5d_coverage_projection"},
    }


def build_observed_etg(expected_etg: dict[str, Any] | None, node_seq: list[str]) -> dict[str, Any]:
    def primary_type(src: dict[str, Any]) -> str:
        t = src.get("type")
        if isinstance(t, str) and t and t != "None":
            return t
        ts = src.get("types")
        if isinstance(ts, list) and ts:
            h = ts[0]
            if isinstance(h, str) and h:
                return h
        if isinstance(t, str) and t:
            return t
        return "None"

    expected_node_by_id = {n.get("id"): n for n in (expected_etg.get("nodes") or [])} if expected_etg else {}

    nodes = []
    seen = set()
    for i, nid in enumerate(node_seq):
        if nid in seen:
            continue
        seen.add(nid)
        src = expected_node_by_id.get(nid, {})
        node = {
            "id": nid,
            "type": primary_type(src),
            "types": src.get("types", [src.get("type", "None")]),
            "intensity": src.get("intensity", 0.5),
        }
        if src.get("key_id"):
            node["key_id"] = src.get("key_id")
        if src.get("requires_key_id"):
            node["requires_key_id"] = src.get("requires_key_id")
        if src.get("lock_id"):
            node["lock_id"] = src.get("lock_id")
        nodes.append(node)

    edges = []
    eid = 0
    seen_edges = set()
    for i in range(len(node_seq) - 1):
        a, b = node_seq[i], node_seq[i + 1]
        if a == b:
            continue
        key = (a, b)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        edges.append({"id": f"OE{eid}", "from": a, "to": b, "length": 1})
        eid += 1

    return {
        "version": 2,
        "nodes": nodes,
        "edges": edges,
        "meta": {"source": "global_5d_projection"},
    }


def compare_etg(expected: dict[str, Any] | None, observed: dict[str, Any], expected_seq: list[str], observed_seq: list[str]) -> dict[str, Any]:
    if not expected:
        return {"available": False}

    exp_nodes = {n.get("id") for n in (expected.get("nodes") or []) if n.get("id")}
    obs_nodes = {n.get("id") for n in (observed.get("nodes") or []) if n.get("id")}

    exp_edges = _directed_edges(expected.get("edges") or [])
    obs_edges = _directed_edges(observed.get("edges") or [])

    node_tp = len(exp_nodes & obs_nodes)
    edge_tp = len(exp_edges & obs_edges)

    node_precision = node_tp / len(obs_nodes) if obs_nodes else 0.0
    node_recall = node_tp / len(exp_nodes) if exp_nodes else 0.0
    edge_precision = edge_tp / len(obs_edges) if obs_edges else 0.0
    edge_recall = edge_tp / len(exp_edges) if exp_edges else 0.0

    node_f1 = 0.0 if (node_precision + node_recall) == 0 else 2 * node_precision * node_recall / (node_precision + node_recall)
    edge_f1 = 0.0 if (edge_precision + edge_recall) == 0 else 2 * edge_precision * edge_recall / (edge_precision + edge_recall)

    lev = _levenshtein(expected_seq, observed_seq)
    norm = lev / max(1, len(expected_seq), len(observed_seq))
    seq_similarity = 1.0 - norm

    return {
        "available": True,
        "node": {
            "precision": node_precision,
            "recall": node_recall,
            "f1": node_f1,
            "tp": node_tp,
            "expected": len(exp_nodes),
            "observed": len(obs_nodes),
        },
        "edge": {
            "precision": edge_precision,
            "recall": edge_recall,
            "f1": edge_f1,
            "tp": edge_tp,
            "expected": len(exp_edges),
            "observed": len(obs_edges),
        },
        "sequence": {
            "levenshtein": lev,
            "normalized_distance": norm,
            "similarity": seq_similarity,
            "expected": expected_seq,
            "observed": observed_seq,
        },
        "extra_nodes": sorted(list(obs_nodes - exp_nodes)),
        "missing_nodes": sorted(list(exp_nodes - obs_nodes)),
        "extra_edges": sorted([list(e) for e in obs_edges - exp_edges]),
        "missing_edges": sorted([list(e) for e in exp_edges - obs_edges]),
    }


def key_lock_order_check(
    etg: dict[str, Any],
    seq: list[str],
    first_hit: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    pos = {nid: i for i, nid in enumerate(seq)}
    issues = []
    lock_seen = False
    key_seen_before_lock = False
    missing_key_node = False
    checked_pairs = 0
    valid_pairs = 0
    for n in etg.get("nodes") or []:
        if not _is_lock(n):
            continue
        req = n.get("requires_key_id")
        if not req:
            continue
        checked_pairs += 1
        key_node = next((k for k in etg.get("nodes") or [] if _is_key(k) and k.get("key_id") == req), None)
        if not key_node:
            missing_key_node = True
            issues.append(
                {
                    "lock_node": n.get("id"),
                    "key_node": None,
                    "key_id": req,
                    "reason": "missing_key_node_in_etg",
                }
            )
            continue
        lk, kk = pos.get(n.get("id")), pos.get(key_node.get("id"))
        if lk is not None:
            lock_seen = True
        if lk is None or kk is None:
            missing_key_node = missing_key_node or (kk is None)
            issues.append(
                {
                    "lock_node": n.get("id"),
                    "key_node": key_node.get("id"),
                    "key_id": req,
                    "reason": "missing_node_in_observed_sequence",
                }
            )
            continue
        key_time = int((first_hit or {}).get(str(key_node.get("id")), {}).get("time", -1))
        lock_time = int((first_hit or {}).get(str(n.get("id")), {}).get("time", -1))
        if kk > lk or (key_time >= 0 and lock_time >= 0 and key_time >= lock_time):
            issues.append(
                {
                    "lock_node": n.get("id"),
                    "key_node": key_node.get("id"),
                    "key_id": req,
                    "reason": "key_not_before_lock",
                }
            )
            continue
        valid_pairs += 1
    key_seen_before_lock = valid_pairs > 0 and valid_pairs == checked_pairs
    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "lock_seen": bool(lock_seen),
        "key_seen_before_lock": bool(key_seen_before_lock),
        "missing_key_node": bool(missing_key_node),
        "checked_pairs": int(checked_pairs),
        "valid_pairs": int(valid_pairs),
    }


def progression_structure_check(
    etg: dict[str, Any] | None,
    path_sequence: list[str],
    first_hit: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not etg:
        return {"ok": True, "issues": [], "missing_nodes": [], "extra_path_edges": []}

    nodes = [n for n in (etg.get("nodes") or []) if n.get("id")]
    node_ids = {str(n["id"]) for n in nodes}
    expected_edges = _directed_edges(etg.get("edges") or [])
    start_nodes = [str(n["id"]) for n in nodes if "Start" in (n.get("types") or [n.get("type")])]
    goal_nodes = [str(n["id"]) for n in nodes if "Goal" in (n.get("types") or [n.get("type")])]
    issues: list[dict[str, Any]] = []

    path_edges = [(str(a), str(b)) for a, b in zip(path_sequence, path_sequence[1:]) if a != b]
    extra_path_edges = [edge for edge in path_edges if edge not in expected_edges]
    for a, b in extra_path_edges:
        issues.append({"reason": "unexpected_path_transition", "from": a, "to": b})

    if start_nodes and (not path_sequence or str(path_sequence[0]) not in start_nodes):
        issues.append({"reason": "path_missing_start"})
    if goal_nodes and (not path_sequence or str(path_sequence[-1]) not in goal_nodes):
        issues.append({"reason": "path_missing_goal"})

    missing_nodes = sorted(node_ids - {str(node_id) for node_id in first_hit})
    for node_id in missing_nodes:
        issues.append({"reason": "unreached_etg_node", "node": node_id})

    incoming: dict[str, set[str]] = {}
    for source, target in expected_edges:
        incoming.setdefault(target, set()).add(source)
    dominators = {node_id: set(node_ids) for node_id in node_ids}
    for node_id in start_nodes:
        dominators[node_id] = {node_id}
    changed = True
    while changed:
        changed = False
        for node_id in node_ids - set(start_nodes):
            predecessors = incoming.get(node_id, set())
            if not predecessors:
                updated = {node_id}
            else:
                shared = set(node_ids)
                for predecessor in predecessors:
                    shared &= dominators.get(predecessor, {predecessor})
                updated = {node_id} | shared
            if updated != dominators[node_id]:
                dominators[node_id] = updated
                changed = True
    for node_id, hit in first_hit.items():
        node_id = str(node_id)
        if node_id in start_nodes:
            continue
        predecessors = incoming.get(node_id, set())
        if not predecessors:
            issues.append({"reason": "reached_without_predecessor", "node": node_id})
            continue
        hit_time = int(hit.get("time", 10**9))
        earlier = []
        for predecessor in predecessors:
            predecessor_hit = first_hit.get(predecessor)
            if not predecessor_hit:
                continue
            predecessor_time = int(predecessor_hit.get("time", 10**9))
            if predecessor_time < hit_time:
                earlier.append(predecessor)
        if not earlier:
            issues.append(
                {
                    "reason": "premature_node_reachability",
                    "node": node_id,
                    "expected_predecessors": sorted(predecessors),
                }
            )
        late_dominators = []
        for dominator in dominators.get(node_id, set()) - {node_id}:
            dominator_hit = first_hit.get(dominator)
            if not dominator_hit:
                late_dominators.append(dominator)
                continue
            dominator_time = int(dominator_hit.get("time", 10**9))
            if dominator_time >= hit_time:
                late_dominators.append(dominator)
        if late_dominators:
            issues.append(
                {
                    "reason": "required_region_bypassed",
                    "node": node_id,
                    "required_nodes": sorted(late_dominators),
                }
            )

    return {
        "ok": not issues,
        "issues": issues,
        "missing_nodes": missing_nodes,
        "extra_path_edges": [list(edge) for edge in extra_path_edges],
        "path_edges": [list(edge) for edge in path_edges],
    }


def _node_region_cells(level: dict[str, Any], node_id: str, model: Any) -> set[str]:
    cells = set()
    for item in level.get("platforms") or []:
        if str(item.get("node_id")) != node_id:
            continue
        pos = item.get("pos") or {}
        size = item.get("size") or {}
        try:
            half_x = float(size.get("x", 0.0)) * 0.5
            half_z = float(size.get("z", 0.0)) * 0.5
            top = float(pos.get("y", 0.0)) + float(size.get("y", 0.0)) * 0.5
            min_x = int(math.floor((float(pos.get("x", 0.0)) - half_x) / model.cellSize))
            max_x = int(math.ceil((float(pos.get("x", 0.0)) + half_x) / model.cellSize))
            min_z = int(math.floor((float(pos.get("z", 0.0)) - half_z) / model.cellSize))
            max_z = int(math.ceil((float(pos.get("z", 0.0)) + half_z) / model.cellSize))
            y = int(round(top / model.cellSize))
        except (TypeError, ValueError):
            continue
        for x in range(min_x, max_x + 1):
            for z in range(min_z, max_z + 1):
                cells.add(cell_key({"x": x, "y": y, "z": z}))
    return cells


def _goal_reachable_avoiding(
    model: Any,
    forbidden_cells: set[str],
    goal_cells: set[str],
    options: dict[str, Any],
) -> dict[str, Any]:
    start_cell = model.findNearestWalkable(model.startCell, 0, 0) or model.startCell
    start = {"x": start_cell["x"], "y": start_cell["y"], "z": start_cell["z"], "t": 0, "phase": 0}
    physics = build_physics_profile(model)
    ground = build_ground_offsets(physics["maxGroundDistance"])
    max_jump_offsets = max(80, min(6000, int(options.get("maxJumpOffsets", 1400))))
    jumps = build_jump_offsets(
        physics["maxJumpDistance"],
        int(physics["maxJumpUp"]),
        int(physics["maxJumpDown"]),
        max_jump_offsets,
    ) if options.get("allowJump", True) else []
    max_time = int(options.get("maxTime") or max(120, int(model.timeHorizon) * 3))
    max_states = min(250000, int(options.get("maxStates", 250000)))
    max_queue = min(180000, int(options.get("maxQueue", 180000)))
    q = deque([start])
    seen = {state_key(start)}
    expanded = 0
    while q:
        state = q.popleft()
        expanded += 1
        cid = cell_key(state)
        if cid in goal_cells:
            return {"reached": True, "expanded": expanded, "truncated": False}
        if expanded > max_states or len(q) > max_queue:
            return {"reached": False, "expanded": expanded, "truncated": True}
        for neighbor in collect_neighbors(
            state,
            model,
            physics,
            ground,
            jumps,
            bool(options.get("allowJump", True)),
            bool(options.get("allowDrop", True)),
            max_time,
            1,
        ):
            if cell_key(neighbor) in forbidden_cells:
                continue
            key = state_key(neighbor)
            if key in seen:
                continue
            seen.add(key)
            q.append(neighbor)
    return {"reached": False, "expanded": expanded, "truncated": False}


def latent_shortcut_check(
    level: dict[str, Any],
    etg: dict[str, Any] | None,
    model: Any,
    marker_by_node: dict[str, set[str]],
    options: dict[str, Any],
) -> dict[str, Any]:
    if not etg:
        return {"ok": True, "issues": []}
    canonical = compute_canonical_route(etg, {"defaultSpeed": (etg.get("meta") or {}).get("defaultSpeed")})
    route = [str(node_id) for node_id in canonical.get("nodes") or []]
    if len(route) < 3:
        return {"ok": True, "issues": []}
    goal_cells = marker_by_node.get(route[-1], set())
    all_nodes = {str(item.get("id")) for item in etg.get("nodes") or [] if item.get("id")}
    incoming: dict[str, set[str]] = {}
    for source, target in _directed_edges(etg.get("edges") or []):
        incoming.setdefault(target, set()).add(source)
    start = route[0]
    dominators = {node_id: set(all_nodes) for node_id in all_nodes}
    dominators[start] = {start}
    changed = True
    while changed:
        changed = False
        for node_id in all_nodes - {start}:
            predecessors = incoming.get(node_id, set())
            shared = set(all_nodes)
            for predecessor in predecessors:
                shared &= dominators.get(predecessor, {predecessor})
            updated = {node_id} | (shared if predecessors else set())
            if updated != dominators[node_id]:
                dominators[node_id] = updated
                changed = True
    required_nodes = dominators.get(route[-1], set()) - {route[0], route[-1]}
    issues = []
    checks = []
    for node_id in sorted(required_nodes):
        forbidden = set(marker_by_node.get(node_id, set())) | _node_region_cells(level, node_id, model)
        if not forbidden or not goal_cells:
            continue
        result = _goal_reachable_avoiding(model, forbidden, goal_cells, options)
        checks.append({"required_node": node_id, **result})
        if result.get("truncated"):
            issues.append({"reason": "shortcut_check_truncated", "required_node": node_id})
        elif result.get("reached"):
            issues.append({"reason": "latent_shortcut", "required_node": node_id, "target_node": route[-1]})
    return {"ok": not issues, "issues": issues, "checks": checks}


def _classify_unreachable_reason(
    *,
    path_reason: str,
    expected_seq: list[str],
    observed_seq: list[str],
    key_lock_ok: bool,
    coverage_truncated: bool,
) -> str:
    reason = str(path_reason or "unreachable")
    if reason in {"wall_time_exceeded", "budget_exceeded"}:
        return "budget_limit_near_goal"
    if reason != "goal_unreachable":
        return reason
    if not key_lock_ok:
        return "lock_order_block"
    if expected_seq:
        observed_set = {str(n) for n in observed_seq}
        missing = [nid for nid in expected_seq if str(nid) not in observed_set]
        if missing:
            return "disconnected_spine"
    if coverage_truncated:
        return "budget_limit_near_goal"
    return "goal_unreachable"


def validate_global_topology(level: dict[str, Any], etg_expected: dict[str, Any] | None = None, options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options or {}
    model = build_hdpcg_model(
        level,
        {
            "cellSize": options.get("cellSize", 1),
            "timeStep": options.get("timeStep", 1),
            "padding": options.get("padding", 4),
            "maxTimeHorizon": options.get("maxTimeHorizon", 180),
            "maxPeriodTicks": options.get("maxPeriodTicks", 180),
        },
    )

    search_options = {
        "allowJump": options.get("allowJump", True),
        "allowDrop": options.get("allowDrop", True),
        "maxTime": options.get("maxTime"),
        "maxStates": options.get("maxStates", 450000),
        "maxQueue": options.get("maxQueue", 350000),
        "maxJumpOffsets": options.get("maxJumpOffsets", 1400),
        "maxGroundDistance": options.get("maxGroundDistance"),
        "maxJumpDistance": options.get("maxJumpDistance"),
        "compressTime": options.get("compressTime", True),
        "maxWallTimeSec": options.get("maxWallTimeSec"),
    }

    path_res = search_shortest_goal_path(
        model,
        search_options,
    )

    marker_by_node = build_node_markers(model, level, etg_expected or level.get("etg"))
    path_seq = project_path_to_node_sequence(path_res.get("path") or [], marker_by_node)
    observed_path = build_observed_etg(etg_expected or level.get("etg"), path_seq)

    coverage_res = compute_reachable(
        model,
        {
            "allowJump": search_options.get("allowJump", True),
            "allowDrop": search_options.get("allowDrop", True),
            "maxTime": search_options.get("maxTime"),
            "maxStates": search_options.get("maxStates", 450000),
            "maxQueue": search_options.get("maxQueue", 350000),
            "maxJumpOffsets": search_options.get("maxJumpOffsets", 1400),
            "maxGroundDistance": search_options.get("maxGroundDistance"),
            "maxJumpDistance": search_options.get("maxJumpDistance"),
            "compressTime": search_options.get("compressTime", True),
            "maxWallTimeSec": search_options.get("maxWallTimeSec"),
        },
    )
    node_first_hit, hit_timeline = collect_node_first_hits(coverage_res.get("reachableByTimePhase") or [], marker_by_node)
    seq = build_coverage_sequence(node_first_hit, etg_expected or level.get("etg"))
    observed = build_observed_etg_from_coverage(etg_expected or level.get("etg"), node_first_hit, seq)

    expected_canonical = compute_canonical_route(etg_expected, {"defaultSpeed": (etg_expected.get("meta") or {}).get("defaultSpeed")}) if etg_expected else {"ok": False}
    expected_seq = list(expected_canonical.get("nodes") or []) if expected_canonical.get("ok") else []
    cmp = compare_etg(etg_expected, observed, expected_seq, seq)
    kl = key_lock_order_check(etg_expected, seq, node_first_hit) if etg_expected else {"ok": True, "issues": []}
    structure = progression_structure_check(etg_expected, path_seq, node_first_hit)
    if coverage_res.get("truncated"):
        structure = {
            **structure,
            "ok": False,
            "issues": [*(structure.get("issues") or []), {"reason": "coverage_search_truncated"}],
        }
    shortcuts = (
        latent_shortcut_check(level, etg_expected, model, marker_by_node, search_options)
        if bool(options.get("checkLatentShortcuts", False))
        else {"ok": True, "issues": [], "checks": [], "skipped": True}
    )
    if not shortcuts.get("ok", True):
        structure = {
            **structure,
            "ok": False,
            "issues": [*(structure.get("issues") or []), *(shortcuts.get("issues") or [])],
        }
    failure_reason = _classify_unreachable_reason(
        path_reason=str(path_res.get("reason", "unreachable")),
        expected_seq=expected_seq,
        observed_seq=seq,
        key_lock_ok=bool(kl.get("ok", True)),
        coverage_truncated=bool(coverage_res.get("truncated")),
    )

    coverage_summary = {
        "max_time": coverage_res.get("maxTime"),
        "max_time_used": coverage_res.get("maxTimeUsed"),
        "last_reachable_cell_time": coverage_res.get("lastReachableCellTime"),
        "expanded": coverage_res.get("expanded"),
        "visited": coverage_res.get("visitedCount"),
        "truncated": bool(coverage_res.get("truncated")),
        "hit_node_count": len(node_first_hit),
        "hit_nodes": sorted(node_first_hit.keys()),
        "unhit_nodes": sorted(
            [nid for nid in marker_by_node.keys() if nid not in node_first_hit]
        ),
        "node_first_hit": node_first_hit,
        "timeline_events": hit_timeline,
    }

    if not path_res.get("ok"):
        return {
            "ok": False,
            "goal_reachable": False,
            "reason": failure_reason,
            "search": path_res,
            "coverage_search": coverage_summary,
            "marker_nodes": {k: sorted(list(v)) for k, v in marker_by_node.items()},
            "observed_node_sequence": seq,
            "observed_etg": observed,
            "observed_node_sequence_path": path_seq,
            "observed_etg_path": observed_path,
            "comparison": cmp,
            "key_lock_order": kl,
            "structural_pass": structure,
            "shortcut_check": shortcuts,
            "partial_observation": bool(path_res.get("path")),
        }

    fidelity = 0.0
    if cmp.get("available"):
        fidelity = 0.45 * cmp["node"]["f1"] + 0.35 * cmp["edge"]["f1"] + 0.20 * cmp["sequence"]["similarity"]

    topology_ok = bool(structure.get("ok", True)) and bool(kl.get("ok", True))
    return {
        "ok": topology_ok,
        "goal_reachable": True,
        "reason": "reachable" if topology_ok else "topology_violation",
        "search": {
            "expanded": path_res.get("expanded"),
            "visited": path_res.get("visited"),
            "goal_time": path_res.get("time"),
            "goal_phase": path_res.get("phase"),
            "path_length_states": len(path_res.get("path") or []),
        },
        "coverage_search": coverage_summary,
        "marker_nodes": {k: sorted(list(v)) for k, v in marker_by_node.items()},
        "observed_node_sequence": seq,
        "observed_etg": observed,
        "observed_node_sequence_path": path_seq,
        "observed_etg_path": observed_path,
        "comparison": cmp,
        "key_lock_order": kl,
        "structural_pass": structure,
        "shortcut_check": shortcuts,
        "fidelity_score": fidelity,
    }

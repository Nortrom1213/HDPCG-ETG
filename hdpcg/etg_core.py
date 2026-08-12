"""ETG schema, normalization, validation, and canonical route search."""

from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from typing import Any

ETG_VERSION = 2
DEFAULT_SPEED = 7.5
DEFAULT_EDGE_LENGTH = 30.0

NODE_TYPES = {
    "START": "Start",
    "GOAL": "Goal",
    "NONE": "None",
    "PLATFORM": "Platform",
    "JUMP": "Jump",
    "DROP": "Drop",
    "ENEMY": "Enemy",
    "KEY": "Key",
    "LOCK": "Lock",
}
NODE_TYPES_LIST = list(NODE_TYPES.values())
GROUND_TYPES = {
    NODE_TYPES["START"],
    NODE_TYPES["GOAL"],
    NODE_TYPES["NONE"],
    NODE_TYPES["PLATFORM"],
    NODE_TYPES["JUMP"],
    NODE_TYPES["DROP"],
}
OVERLAY_TYPES = {
    NODE_TYPES["ENEMY"],
    NODE_TYPES["KEY"],
    NODE_TYPES["LOCK"],
}

DEFAULT_INTENSITY = 0.5
DEFAULT_INTENSITY_STRUCTURAL = 0.1


@dataclass
class EtgValidation:
    ok: bool
    issues: list[str]
    warnings: list[str]


def clamp_number(value: Any, min_value: float, max_value: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return min_value
    if n != n:
        return min_value
    return max(min_value, min(max_value, n))


def _unique_list(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def choose_primary_type(types: list[str]) -> str:
    if NODE_TYPES["START"] in types:
        return NODE_TYPES["START"]
    if NODE_TYPES["GOAL"] in types:
        return NODE_TYPES["GOAL"]
    if NODE_TYPES["JUMP"] in types:
        return NODE_TYPES["JUMP"]
    if NODE_TYPES["DROP"] in types:
        return NODE_TYPES["DROP"]
    if NODE_TYPES["PLATFORM"] in types:
        return NODE_TYPES["PLATFORM"]
    if NODE_TYPES["NONE"] in types:
        return NODE_TYPES["NONE"]
    return NODE_TYPES["NONE"]


def is_etg(etg: dict[str, Any] | None) -> bool:
    if not isinstance(etg, dict):
        return False
    return etg.get("version") == ETG_VERSION or (etg.get("meta") or {}).get("version") == ETG_VERSION


def normalize_node(node: dict[str, Any] | None, fallback_index: int = 0) -> dict[str, Any]:
    safe = node if isinstance(node, dict) else {}
    raw_types = safe.get("types") if isinstance(safe.get("types"), list) else ([safe.get("type")] if safe.get("type") else [])
    normalized_types = _unique_list(
        [str(t).strip() for t in raw_types if isinstance(t, str) and str(t).strip() in NODE_TYPES_LIST]
    )
    types = normalized_types if normalized_types else [NODE_TYPES["NONE"]]

    if NODE_TYPES["START"] in types:
        types = [NODE_TYPES["START"]]
    if NODE_TYPES["GOAL"] in types:
        types = [NODE_TYPES["GOAL"]]

    has_ground = any(t in GROUND_TYPES for t in types)
    has_overlay = any(t in OVERLAY_TYPES for t in types)
    if not has_ground and has_overlay:
        types = [NODE_TYPES["NONE"], *types]

    primary = choose_primary_type(types)
    is_structural = primary in {NODE_TYPES["START"], NODE_TYPES["GOAL"], NODE_TYPES["NONE"]}
    intensity_default = DEFAULT_INTENSITY_STRUCTURAL if is_structural else DEFAULT_INTENSITY
    intensity = clamp_number(safe.get("intensity", intensity_default), 0.0, 1.0)

    node_id = str(safe.get("id", "")).strip() if safe.get("id") is not None else ""
    out: dict[str, Any] = {
        "id": node_id if node_id else f"N{fallback_index}",
        "type": primary,
        "types": types,
        "intensity": intensity,
    }

    if NODE_TYPES["KEY"] in types:
        key_id = str(safe.get("key_id", "")).strip()
        out["key_id"] = key_id if key_id else "K1"
    if NODE_TYPES["LOCK"] in types:
        req = str(safe.get("requires_key_id", "")).strip()
        out["requires_key_id"] = req if req else "K1"
        lock_id = str(safe.get("lock_id", "")).strip()
        if lock_id:
            out["lock_id"] = lock_id

    return out


def normalize_edge(edge: dict[str, Any] | None, fallback_index: int = 0) -> dict[str, Any]:
    safe = edge if isinstance(edge, dict) else {}
    length = clamp_number(safe.get("length", DEFAULT_EDGE_LENGTH), 1.0, 100000.0)
    edge_id = str(safe.get("id", "")).strip() if safe.get("id") is not None else ""
    return {
        "id": edge_id if edge_id else f"E{fallback_index}",
        "from": safe.get("from"),
        "to": safe.get("to"),
        "length": length,
    }


def normalize_etg(etg: dict[str, Any] | None, options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options or {}
    if not isinstance(etg, dict):
        return create_default_etg()

    default_speed = clamp_number(
        (etg.get("meta") or {}).get("defaultSpeed", options.get("defaultSpeed", DEFAULT_SPEED)),
        0.1,
        1000.0,
    )

    nodes = [normalize_node(node, idx) for idx, node in enumerate(etg.get("nodes") or [])]
    edges = [normalize_edge(edge, idx) for idx, edge in enumerate(etg.get("edges") or [])]

    meta = dict(etg.get("meta") or {})
    meta["defaultSpeed"] = default_speed

    return {
        "version": ETG_VERSION,
        "nodes": nodes,
        "edges": edges,
        "meta": meta,
    }


def _node_has_type(node: dict[str, Any] | None, type_name: str) -> bool:
    if not isinstance(node, dict):
        return False
    types = node.get("types") if isinstance(node.get("types"), list) and node.get("types") else ([node.get("type")] if node.get("type") else [])
    return type_name in types


def _is_connected_without(
    node_ids: set[str],
    neighbor_set_by_id: dict[str, set[str]],
    blocked_node_id: str,
    start_id: str,
    goal_id: str,
) -> bool:
    if not start_id or not goal_id:
        return False
    if start_id == goal_id:
        return True
    if start_id not in node_ids or goal_id not in node_ids:
        return False

    blocked = str(blocked_node_id)
    visited = {start_id}
    queue = [start_id]
    head = 0

    while head < len(queue):
        current = queue[head]
        head += 1
        neighbors = neighbor_set_by_id.get(current) or set()
        for nxt in neighbors:
            if not nxt or nxt == blocked:
                continue
            if current == blocked:
                continue
            if nxt in visited:
                continue
            if nxt not in node_ids:
                continue
            if nxt == goal_id:
                return True
            visited.add(nxt)
            queue.append(nxt)

    return False


def validate_etg(etg: dict[str, Any] | None) -> EtgValidation:
    issues: list[str] = []
    warnings: list[str] = []

    if not isinstance(etg, dict):
        issues.append("ETG missing")
        return EtgValidation(False, issues, warnings)

    nodes = etg.get("nodes") if isinstance(etg.get("nodes"), list) else []
    edges = etg.get("edges") if isinstance(etg.get("edges"), list) else []

    by_id: dict[str, dict[str, Any]] = {}
    for node in nodes:
        node_id = node.get("id") if isinstance(node, dict) else None
        if not isinstance(node_id, str) or not node_id:
            issues.append("node missing id")
            continue
        if node_id in by_id:
            issues.append(f"duplicate node id {node_id}")
        by_id[node_id] = node

        types = node.get("types") if isinstance(node.get("types"), list) and node.get("types") else ([node.get("type")] if node.get("type") else [])
        if not types:
            issues.append(f"node {node_id} missing types")
        for t in types:
            if t not in NODE_TYPES_LIST:
                warnings.append(f"node {node_id} has unknown type {t}")

        if not isinstance(node.get("intensity"), (int, float)):
            warnings.append(f"node {node_id} intensity invalid")

        ground_set = {t for t in types if t in {NODE_TYPES['PLATFORM'], NODE_TYPES['JUMP'], NODE_TYPES['DROP']}}
        if len(ground_set) > 1:
            warnings.append(f"node {node_id} has multiple ground types ({', '.join(sorted(ground_set))})")

        if NODE_TYPES["START"] in types and len(types) != 1:
            warnings.append(f"Start node {node_id} should not mix types")
        if NODE_TYPES["GOAL"] in types and len(types) != 1:
            warnings.append(f"Goal node {node_id} should not mix types")

    starts = [n for n in nodes if _node_has_type(n, NODE_TYPES["START"])]
    goals = [n for n in nodes if _node_has_type(n, NODE_TYPES["GOAL"])]
    if len(starts) != 1:
        issues.append(f"expected exactly 1 Start, found {len(starts)}")
    if len(goals) != 1:
        issues.append(f"expected exactly 1 Goal, found {len(goals)}")

    neighbor_set_by_id: dict[str, set[str]] = {}
    edge_ids: set[str] = set()
    ordered_pairs: set[tuple[str, str]] = set()

    def add_neighbor(a: str | None, b: str | None) -> None:
        if not a or not b or a == b:
            return
        if a not in neighbor_set_by_id:
            neighbor_set_by_id[a] = set()
        neighbor_set_by_id[a].add(b)

    for edge in edges:
        if not isinstance(edge, dict):
            issues.append("edge missing from/to")
            continue
        edge_id = edge.get("id") or "(no-id)"
        a = edge.get("from")
        b = edge.get("to")
        if not a or not b:
            issues.append("edge missing from/to")
            continue
        if a not in by_id or b not in by_id:
            issues.append(f"edge {edge_id} connects missing node")
        if edge_id != "(no-id)":
            if str(edge_id) in edge_ids:
                issues.append(f"duplicate edge id {edge_id}")
            edge_ids.add(str(edge_id))
        if a == b:
            issues.append(f"edge {edge_id} is a self-loop")
        pair = (str(a), str(b))
        if pair in ordered_pairs:
            issues.append(f"parallel edge for ordered pair {a}->{b}")
        ordered_pairs.add(pair)
        length = edge.get("length")
        if not isinstance(length, (int, float)) or not (length > 0):
            issues.append(f"edge {edge_id} length must be > 0")

        add_neighbor(a, b)
        add_neighbor(b, a)

    key_ids = {
        str(n.get("key_id")).strip()
        for n in nodes
        if _node_has_type(n, NODE_TYPES["KEY"]) and isinstance(n.get("key_id"), str) and str(n.get("key_id")).strip()
    }

    node_ids = {n.get("id") for n in nodes if isinstance(n.get("id"), str)}

    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        if _node_has_type(node, NODE_TYPES["KEY"]) and not node.get("key_id"):
            issues.append(f"Key node {node_id} missing key_id")

        if _node_has_type(node, NODE_TYPES["LOCK"]):
            if not node.get("requires_key_id"):
                issues.append(f"Lock node {node_id} missing requires_key_id")
            neighbors = neighbor_set_by_id.get(node_id, set())
            if len(neighbors) != 2:
                issues.append(f"Lock node {node_id} must have degree 2 (found {len(neighbors)})")
            if node.get("requires_key_id") and node.get("requires_key_id") not in key_ids:
                issues.append(f"Lock node {node_id} requires missing key_id {node.get('requires_key_id')}")
            if len(neighbors) == 2:
                a, b = list(neighbors)
                if _is_connected_without(node_ids, neighbor_set_by_id, str(node_id), str(a), str(b)):
                    warnings.append(f"Lock node {node_id} neighbors remain connected without the lock (may not gate)")

    return EtgValidation(len(issues) == 0, issues, warnings)


def _make_state_key(node_id: str, mask: int) -> str:
    return f"{node_id}@@{mask}"


def _parse_state_key(key: str) -> tuple[str, int]:
    idx = key.rfind("@@")
    if idx < 0:
        return key, 0
    return key[:idx], int(key[idx + 2 :] or 0)


def compute_canonical_route(etg: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options or {}
    default_speed = clamp_number(
        (etg.get("meta") or {}).get("defaultSpeed", options.get("defaultSpeed", DEFAULT_SPEED)), 0.1, 1000.0
    )
    nodes = etg.get("nodes") if isinstance(etg.get("nodes"), list) else []
    edges = etg.get("edges") if isinstance(etg.get("edges"), list) else []
    by_id = {n.get("id"): n for n in nodes if isinstance(n, dict) and n.get("id")}

    start = next((n for n in nodes if _node_has_type(n, NODE_TYPES["START"])), None)
    goal = next((n for n in nodes if _node_has_type(n, NODE_TYPES["GOAL"])), None)
    if not start or not goal:
        return {
            "ok": False,
            "reason": "missing Start/Goal",
            "nodes": [],
            "edges": [],
            "totalLength": 0,
            "totalEtaSeconds": 0,
            "defaultSpeed": default_speed,
        }

    key_ids = []
    for n in nodes:
        if _node_has_type(n, NODE_TYPES["KEY"]) and n.get("key_id") and n.get("key_id") not in key_ids:
            key_ids.append(n.get("key_id"))
    key_index = {key_id: idx for idx, key_id in enumerate(key_ids)}

    key_mask_of_node: dict[str, int] = {}
    lock_req_index_of_node: dict[str, int] = {}

    for n in nodes:
        node_id = n.get("id")
        if not node_id:
            continue
        if _node_has_type(n, NODE_TYPES["KEY"]) and n.get("key_id") in key_index:
            key_mask_of_node[node_id] = 1 << key_index[n.get("key_id")]
        if _node_has_type(n, NODE_TYPES["LOCK"]) and n.get("requires_key_id") in key_index:
            lock_req_index_of_node[node_id] = key_index[n.get("requires_key_id")]

    edges_by_from: dict[str, list[tuple[dict[str, Any], str]]] = {}
    for e in edges:
        if not isinstance(e, dict):
            continue
        a = e.get("from")
        b = e.get("to")
        if not a or not b:
            continue
        edges_by_from.setdefault(a, []).append((e, b))

    start_id = start.get("id")
    goal_id = goal.get("id")
    start_mask = key_mask_of_node.get(start_id, 0)

    start_state = _make_state_key(start_id, start_mask)
    dist: dict[str, float] = {start_state: 0.0}
    prev: dict[str, dict[str, Any]] = {}
    pq: list[tuple[float, str]] = []
    heappush(pq, (0.0, start_state))

    goal_state: str | None = None

    while pq:
        cost, key = heappop(pq)
        if cost != dist.get(key):
            continue
        node_id, mask = _parse_state_key(key)
        if node_id == goal_id:
            goal_state = key
            break

        for edge_obj, to_id in edges_by_from.get(node_id, []):
            to_node = by_id.get(to_id)
            if not to_node:
                continue

            next_mask = mask
            if _node_has_type(to_node, NODE_TYPES["LOCK"]):
                req_idx = lock_req_index_of_node.get(to_id)
                if req_idx is not None:
                    has_key = (mask & (1 << req_idx)) != 0
                    if not has_key:
                        continue
                elif to_node.get("requires_key_id"):
                    continue

            next_mask |= key_mask_of_node.get(to_id, 0)
            next_key = _make_state_key(to_id, next_mask)

            length = edge_obj.get("length") if isinstance(edge_obj.get("length"), (int, float)) else DEFAULT_EDGE_LENGTH
            next_cost = cost + max(1e-6, float(length))

            best = dist.get(next_key)
            if best is None or next_cost < best:
                dist[next_key] = next_cost
                prev[next_key] = {"prevKey": key, "edgeId": edge_obj.get("id")}
                heappush(pq, (next_cost, next_key))

    if goal_state is None:
        return {
            "ok": False,
            "reason": "no feasible path (check Key/Lock connectivity or missing keys)",
            "nodes": [],
            "edges": [],
            "totalLength": 0,
            "totalEtaSeconds": 0,
            "defaultSpeed": default_speed,
        }

    state_trail: list[str] = []
    cursor: str | None = goal_state
    while cursor:
        state_trail.append(cursor)
        step = prev.get(cursor)
        cursor = step.get("prevKey") if step else None
    state_trail.reverse()

    edge_map = {e.get("id"): e for e in edges if isinstance(e, dict) and e.get("id")}
    route_nodes: list[str] = []
    route_edges: list[str] = []
    total_length = 0.0

    for state_key in state_trail:
        node_id, _ = _parse_state_key(state_key)
        route_nodes.append(node_id)
        step = prev.get(state_key)
        edge_id = step.get("edgeId") if step else None
        if edge_id:
            route_edges.append(edge_id)
            edge_obj = edge_map.get(edge_id)
            if edge_obj and isinstance(edge_obj.get("length"), (int, float)):
                total_length += float(edge_obj.get("length"))

    return {
        "ok": True,
        "reason": None,
        "nodes": route_nodes,
        "edges": route_edges,
        "totalLength": total_length,
        "totalEtaSeconds": total_length / default_speed,
        "defaultSpeed": default_speed,
    }


def create_default_etg() -> dict[str, Any]:
    return normalize_etg(
        {
            "version": ETG_VERSION,
            "nodes": [
                {"id": "N0", "type": NODE_TYPES["START"], "intensity": DEFAULT_INTENSITY_STRUCTURAL},
                {"id": "N1", "type": NODE_TYPES["NONE"], "intensity": DEFAULT_INTENSITY_STRUCTURAL},
                {"id": "N2", "type": NODE_TYPES["GOAL"], "intensity": DEFAULT_INTENSITY_STRUCTURAL},
            ],
            "edges": [
                {"id": "E0", "from": "N0", "to": "N1", "length": 20},
                {"id": "E1", "from": "N1", "to": "N2", "length": 20},
            ],
            "meta": {"defaultSpeed": DEFAULT_SPEED},
        }
    )

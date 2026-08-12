"""ETG synthesis and canonical-route utilities."""

from __future__ import annotations

from typing import Any

from .etg_core import DEFAULT_SPEED, NODE_TYPES, compute_canonical_route, normalize_etg
from .random_utils import Mulberry32, pick


def _clamp01(value: Any) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        n = 0.0
    return max(0.0, min(1.0, n))


def _choose_segment_type(difficulty: float, rng: Mulberry32) -> str:
    if difficulty < 0.35:
        return pick(rng, [NODE_TYPES["NONE"], NODE_TYPES["PLATFORM"], NODE_TYPES["PLATFORM"]])
    if difficulty < 0.65:
        return pick(
            rng,
            [
                NODE_TYPES["PLATFORM"],
                NODE_TYPES["JUMP"],
                NODE_TYPES["ENEMY"],
                NODE_TYPES["DROP"],
                NODE_TYPES["PLATFORM"],
            ],
        )
    return pick(rng, [NODE_TYPES["JUMP"], NODE_TYPES["ENEMY"], NODE_TYPES["DROP"], NODE_TYPES["JUMP"]])


def _sample_edge_length(difficulty: float, rng: Mulberry32, kind: str) -> int:
    base = 26 + difficulty * 18
    scale = 1.0
    if kind == NODE_TYPES["NONE"]:
        scale = 0.7
    if kind == NODE_TYPES["JUMP"]:
        scale = 0.9
    if kind == NODE_TYPES["DROP"]:
        scale = 0.85
    if kind == NODE_TYPES["ENEMY"]:
        scale = 0.95
    if kind == "gate":
        scale = 0.75
    if kind == "branch":
        scale = 0.8
    if kind == "loop":
        scale = 0.9
    if kind == "end":
        scale = 0.7
    jitter = 0.75 + rng.random() * 0.5
    return round(max(12, base * scale * jitter))


def create_etg(config: dict[str, Any], rng: Mulberry32) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_id = 0
    edge_id = 0

    difficulty = float(config.get("difficulty", 0.5))
    segment_count = max(4, int(config.get("length", 9)))
    key_lock_enabled = bool(config.get("keyLock", config.get("key_lock", False)))
    branch_chance = _clamp01(config.get("branchChance", config.get("branch_chance", 0.65)))

    lock_at = max(2, int(segment_count * 0.7)) if key_lock_enabled else -1
    branch_from_at = max(1, int(segment_count * 0.35)) if key_lock_enabled else -1

    def add_node(type_name: str, props: dict[str, Any] | None = None) -> dict[str, Any]:
        nonlocal node_id
        props = props or {}
        nid = f"N{node_id}"
        node_id += 1
        intensity = _clamp01(props.get("intensity", difficulty))
        node: dict[str, Any] = {"id": nid, "type": type_name, "intensity": intensity}
        if type_name == NODE_TYPES["KEY"]:
            node["key_id"] = props.get("key_id", "K1")
        if type_name == NODE_TYPES["LOCK"]:
            node["requires_key_id"] = props.get("requires_key_id", "K1")
            node["lock_id"] = props.get("lock_id", "L1")
        nodes.append(node)
        return node

    def add_edge(from_id: str, to_id: str, length: int) -> str:
        nonlocal edge_id
        eid = f"E{edge_id}"
        edge_id += 1
        edges.append({"id": eid, "from": from_id, "to": to_id, "length": length})
        return eid

    start = add_node(NODE_TYPES["START"], {"intensity": 0.1})
    last = start

    spine = [start]
    for i in range(segment_count):
        if key_lock_enabled and i == lock_at:
            lock_node = add_node(
                NODE_TYPES["LOCK"],
                {
                    "intensity": min(1.0, difficulty + 0.15),
                    "requires_key_id": "K1",
                    "lock_id": "L1",
                },
            )
            add_edge(last["id"], lock_node["id"], _sample_edge_length(difficulty, rng, "gate"))
            spine.append(lock_node)
            last = lock_node
            continue

        segment_type = _choose_segment_type(difficulty, rng)
        node = add_node(segment_type, {"intensity": _clamp01(difficulty + (rng.random() - 0.5) * 0.25)})
        add_edge(last["id"], node["id"], _sample_edge_length(difficulty, rng, segment_type))
        spine.append(node)
        last = node

    goal = add_node(NODE_TYPES["GOAL"], {"intensity": 0.1})
    add_edge(last["id"], goal["id"], _sample_edge_length(difficulty, rng, "end"))
    spine.append(goal)

    if key_lock_enabled and lock_at >= 0:
        branch_from = spine[min(len(spine) - 2, max(0, branch_from_at))]
        lock_node = next((n for n in spine if n.get("type") == NODE_TYPES["LOCK"]), None)
        if lock_node and lock_node in spine:
            rejoin_target = spine[max(0, spine.index(lock_node) - 1)]
        else:
            rejoin_target = spine[max(0, len(spine) - 2)]

        key_node = add_node(
            NODE_TYPES["KEY"],
            {"intensity": max(0.2, difficulty - 0.05), "key_id": "K1"},
        )
        add_edge(branch_from["id"], key_node["id"], _sample_edge_length(difficulty, rng, "branch"))
        add_edge(key_node["id"], rejoin_target["id"], _sample_edge_length(difficulty, rng, "branch"))

    loop_chance = 0.08 + 0.55 * branch_chance
    if rng.random() < loop_chance and len(spine) > 4:
        a = spine[max(1, int(rng.random() * (len(spine) - 3)))]
        b = spine[max(1, int(rng.random() * (len(spine) - 2)))]
        if a and b and a["id"] != b["id"]:
            add_edge(b["id"], a["id"], _sample_edge_length(difficulty, rng, "loop"))

    extra_branch_budget = max(0, min(4, int(round(branch_chance * max(0, segment_count - 2) * 0.35))))
    for _ in range(extra_branch_budget):
        if len(spine) < 5:
            break
        src_idx = max(1, min(len(spine) - 4, int(rng.random() * (len(spine) - 3))))
        dst_idx = max(src_idx + 2, min(len(spine) - 2, src_idx + 2 + int(rng.random() * 3)))
        src = spine[src_idx]
        dst = spine[dst_idx]
        if not src or not dst or src["id"] == dst["id"]:
            continue
        branch_type = _choose_segment_type(difficulty, rng)
        branch_node = add_node(branch_type, {"intensity": _clamp01(difficulty + (rng.random() - 0.5) * 0.3)})
        add_edge(src["id"], branch_node["id"], _sample_edge_length(difficulty, rng, "branch"))
        add_edge(branch_node["id"], dst["id"], _sample_edge_length(difficulty, rng, "branch"))

    return normalize_etg(
        {
            "nodes": nodes,
            "edges": edges,
            "meta": {
                "seed": config.get("seed"),
                "defaultSpeed": DEFAULT_SPEED,
            },
        }
    )


def summarize_etg(etg: dict[str, Any]) -> dict[str, Any]:
    canonical = compute_canonical_route(etg, {"defaultSpeed": (etg.get("meta") or {}).get("defaultSpeed")})
    return {
        "node_count": len(etg.get("nodes") or []),
        "edge_count": len(etg.get("edges") or []),
        "canonical_ok": bool(canonical.get("ok")),
        "canonical_total_length": round(float(canonical.get("totalLength", 0.0)), 2) if canonical.get("ok") else None,
        "canonical_eta_seconds": round(float(canonical.get("totalEtaSeconds", 0.0)), 2)
        if canonical.get("ok")
        else None,
        "canonical_nodes": list(canonical.get("nodes") or []) if canonical.get("ok") else [],
    }

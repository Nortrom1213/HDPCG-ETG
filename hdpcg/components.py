"""Component family catalog for DI-HDPCG."""

from __future__ import annotations

from typing import Any

from .etg_core import NODE_TYPES


CONNECTOR_FAMILIES = [
    "linear_bridge",
    "stair_bridge",
    "arc_bridge",
    "zigzag_bridge",
    "split_merge_bridge",
    "moving_shuttle_bridge",
    "hazard_chicane_bridge",
    "vertical_lift_bridge",
]


NODE_CHUNK_FAMILIES = {
    NODE_TYPES["START"]: ["start_plaza", "start_ramp"],
    NODE_TYPES["GOAL"]: ["goal_platform", "goal_tower"],
    NODE_TYPES["NONE"]: ["open_room", "serpentine_room", "dual_lane_room", "arena_room"],
    NODE_TYPES["PLATFORM"]: ["open_room", "serpentine_room", "dual_lane_room", "arena_room"],
    NODE_TYPES["JUMP"]: ["gap_chain", "offset_islands", "ascending_jumps"],
    NODE_TYPES["DROP"]: ["drop_well", "stepped_drop", "spiral_drop"],
    NODE_TYPES["ENEMY"]: ["patrol_line", "cross_patrol", "choke_guard"],
    NODE_TYPES["KEY"]: ["safe_key_pocket", "risk_key_room", "timed_key_bridge"],
    NODE_TYPES["LOCK"]: ["center_gate", "offset_gate", "double_gate_hall"],
    "Checkpoint": ["checkpoint_pocket", "checkpoint_bridge"],
}


def choose_node_primary_type(node: dict[str, Any]) -> str:
    types = (
        node.get("types")
        if isinstance(node.get("types"), list) and node.get("types")
        else ([node.get("type")] if node.get("type") else [NODE_TYPES["NONE"]])
    )
    if NODE_TYPES["START"] in types:
        return NODE_TYPES["START"]
    if NODE_TYPES["GOAL"] in types:
        return NODE_TYPES["GOAL"]
    if NODE_TYPES["LOCK"] in types:
        return NODE_TYPES["LOCK"]
    if NODE_TYPES["KEY"] in types:
        return NODE_TYPES["KEY"]
    if NODE_TYPES["ENEMY"] in types:
        return NODE_TYPES["ENEMY"]
    if NODE_TYPES["JUMP"] in types:
        return NODE_TYPES["JUMP"]
    if NODE_TYPES["DROP"] in types:
        return NODE_TYPES["DROP"]
    if NODE_TYPES["PLATFORM"] in types:
        return NODE_TYPES["PLATFORM"]
    return NODE_TYPES["NONE"]


def list_node_families(node: dict[str, Any]) -> list[str]:
    primary = choose_node_primary_type(node)
    types = (
        node.get("types")
        if isinstance(node.get("types"), list) and node.get("types")
        else ([node.get("type")] if node.get("type") else [NODE_TYPES["NONE"]])
    )
    out = set(NODE_CHUNK_FAMILIES.get(primary, ["open_room"]))
    if NODE_TYPES["ENEMY"] in types:
        out.update(NODE_CHUNK_FAMILIES[NODE_TYPES["ENEMY"]])
    if NODE_TYPES["KEY"] in types:
        out.update(NODE_CHUNK_FAMILIES[NODE_TYPES["KEY"]])
    return sorted(out)


def list_connector_families(edge_length: float) -> list[str]:
    length = float(edge_length or 0.0)
    if length < 16:
        return ["linear_bridge", "stair_bridge", "arc_bridge", "zigzag_bridge"]
    if length > 42:
        return [
            "linear_bridge",
            "stair_bridge",
            "arc_bridge",
            "zigzag_bridge",
            "split_merge_bridge",
            "moving_shuttle_bridge",
            "vertical_lift_bridge",
        ]
    return list(CONNECTOR_FAMILIES)


def family_base_complexity(family: str) -> float:
    if family in {"linear_bridge", "start_plaza", "goal_platform", "open_room"}:
        return 0.2
    if family in {"stair_bridge", "arc_bridge", "serpentine_room", "drop_well"}:
        return 0.35
    if family in {"zigzag_bridge", "dual_lane_room", "goal_tower", "ascending_jumps"}:
        return 0.5
    if family in {
        "split_merge_bridge",
        "moving_shuttle_bridge",
        "hazard_chicane_bridge",
        "vertical_lift_bridge",
        "arena_room",
        "offset_islands",
        "spiral_drop",
        "cross_patrol",
        "choke_guard",
        "risk_key_room",
        "timed_key_bridge",
        "double_gate_hall",
    }:
        return 0.75
    return 0.45

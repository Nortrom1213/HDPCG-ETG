"""Hard constraints for DI-HDPCG candidates."""

from __future__ import annotations

from typing import Any

from .etg_core import NODE_TYPES


def _has_type(node: dict[str, Any], t: str) -> bool:
    types = (
        node.get("types")
        if isinstance(node.get("types"), list) and node.get("types")
        else ([node.get("type")] if node.get("type") else [])
    )
    return t in types


def _surrogate_profile(config: dict[str, Any], canonical: bool) -> tuple[float, float, float, float, set[str]]:
    cfg = config or {}
    if not canonical:
        return (0.0, 0.0, 1.0, 2.0, set())
    strictness = str(
        cfg.get("surrogateCanonicalStrictness", cfg.get("baselineCanonicalSurrogateStrictness", "medium"))
    ).strip().lower()
    if strictness in {"medium+", "medium_plus"}:
        strictness = "medium_plus"
    if strictness not in {"low", "medium", "medium_plus", "high"}:
        strictness = "medium"

    if strictness == "low":
        max_lat, max_vert, max_complexity, max_stair = 2.8, 1.9, 0.96, 1.25
    elif strictness == "medium_plus":
        max_lat, max_vert, max_complexity, max_stair = 2.5, 1.7, 0.88, 1.16
    elif strictness == "high":
        max_lat, max_vert, max_complexity, max_stair = 2.0, 1.3, 0.72, 0.95
    else:
        max_lat, max_vert, max_complexity, max_stair = 2.3, 1.55, 0.82, 1.10

    max_lat = float(cfg.get("surrogateCanonicalMaxLateral", max_lat))
    max_vert = float(cfg.get("surrogateCanonicalMaxVertical", max_vert))
    max_complexity = float(cfg.get("surrogateCanonicalMaxComplexity", max_complexity))
    max_stair = float(cfg.get("surrogateCanonicalMaxStairStep", max_stair))
    disallow = {
        str(v)
        for v in (
            cfg.get("surrogateCanonicalDisallowConnectors")
            or ["moving_shuttle_bridge", "hazard_chicane_bridge", "split_merge_bridge"]
        )
        if v
    }
    return max_lat, max_vert, max_complexity, max_stair, disallow


def check_component_hard_constraints(
    candidate: dict[str, Any],
    *,
    edge: dict[str, Any],
    to_node: dict[str, Any],
    canonical: bool = False,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issues: list[str] = []
    cfg = config or {}
    edge_length = float(edge.get("length", 0))
    connector_family = candidate.get("connectorFamily")
    node_family = candidate.get("nodeFamily")
    connector = candidate.get("connector") or {}
    complexity = float(candidate.get("complexity", 0.0) or 0.0)
    lateral_amp = float(connector.get("lateralAmplitude", 0.0) or 0.0)
    vertical_amp = float(connector.get("verticalAmplitude", 0.0) or 0.0)
    stair_step = float(connector.get("stairStep", 0.0) or 0.0)

    if edge_length <= 0:
        issues.append("edge_length_invalid")

    if connector_family == "vertical_lift_bridge" and edge_length < 12:
        issues.append("vertical_lift_requires_long_edge")
    if connector_family == "split_merge_bridge" and edge_length < 18:
        issues.append("split_merge_requires_min_length")
    if connector_family == "moving_shuttle_bridge" and edge_length < 14:
        issues.append("moving_shuttle_requires_min_length")

    if _has_type(to_node, NODE_TYPES["LOCK"]):
        if node_family not in {"center_gate", "offset_gate", "double_gate_hall"}:
            issues.append("lock_node_family_mismatch")
    if _has_type(to_node, NODE_TYPES["KEY"]):
        if node_family not in {"safe_key_pocket", "risk_key_room", "timed_key_bridge"}:
            issues.append("key_node_family_mismatch")
    if _has_type(to_node, NODE_TYPES["START"]):
        if node_family not in {"start_plaza", "start_ramp"}:
            issues.append("start_node_family_mismatch")
    if _has_type(to_node, NODE_TYPES["GOAL"]):
        if node_family not in {"goal_platform", "goal_tower"}:
            issues.append("goal_node_family_mismatch")

    if bool(cfg.get("surrogateReachabilityRules", True)):
        if canonical:
            max_lat, max_vert, max_complexity, max_stair, disallow = _surrogate_profile(cfg, True)
            if lateral_amp > max_lat:
                issues.append("surrogate_lateral_amp_exceeded")
            if vertical_amp > max_vert:
                issues.append("surrogate_vertical_amp_exceeded")
            if complexity > max_complexity:
                issues.append("surrogate_complexity_exceeded")
            if stair_step > max_stair:
                issues.append("surrogate_stair_step_exceeded")
            if connector_family in disallow:
                issues.append("surrogate_connector_family_blocked")
            if _has_type(to_node, NODE_TYPES["KEY"]) and node_family == "timed_key_bridge":
                issues.append("surrogate_key_family_blocked")
            if _has_type(to_node, NODE_TYPES["LOCK"]) and node_family == "double_gate_hall":
                issues.append("surrogate_lock_family_blocked")

    return {"ok": len(issues) == 0, "issues": issues}

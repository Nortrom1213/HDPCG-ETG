import { NODE_TYPES } from "./etg-core.js";

function hasType(node, type) {
  const types = Array.isArray(node?.types) && node.types.length ? node.types : node?.type ? [node.type] : [];
  return types.includes(type);
}

export function checkComponentHardConstraints(candidate, context) {
  const issues = [];
  const edgeLength = Number(context?.edge?.length) || 0;
  const toNode = context?.toNode;

  if (edgeLength <= 0) {
    issues.push("edge_length_invalid");
  }

  if (candidate.connectorFamily === "vertical_lift_bridge" && edgeLength < 12) {
    issues.push("vertical_lift_requires_long_edge");
  }
  if (candidate.connectorFamily === "split_merge_bridge" && edgeLength < 18) {
    issues.push("split_merge_requires_min_length");
  }
  if (candidate.connectorFamily === "moving_shuttle_bridge" && edgeLength < 14) {
    issues.push("moving_shuttle_requires_min_length");
  }

  if (hasType(toNode, NODE_TYPES.LOCK)) {
    const allowed = new Set(["center_gate", "offset_gate", "double_gate_hall"]);
    if (!allowed.has(candidate.nodeFamily)) issues.push("lock_node_family_mismatch");
  }
  if (hasType(toNode, NODE_TYPES.KEY)) {
    const allowed = new Set(["safe_key_pocket", "risk_key_room", "timed_key_bridge"]);
    if (!allowed.has(candidate.nodeFamily)) issues.push("key_node_family_mismatch");
  }
  if (hasType(toNode, NODE_TYPES.START)) {
    const allowed = new Set(["start_plaza", "start_ramp"]);
    if (!allowed.has(candidate.nodeFamily)) issues.push("start_node_family_mismatch");
  }
  if (hasType(toNode, NODE_TYPES.GOAL)) {
    const allowed = new Set(["goal_platform", "goal_tower"]);
    if (!allowed.has(candidate.nodeFamily)) issues.push("goal_node_family_mismatch");
  }

  return { ok: issues.length === 0, issues };
}

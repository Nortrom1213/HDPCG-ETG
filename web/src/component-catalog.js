import { NODE_TYPES } from "./etg-core.js";

export const CONNECTOR_FAMILIES = [
  "linear_bridge",
  "stair_bridge",
  "arc_bridge",
  "zigzag_bridge",
  "split_merge_bridge",
  "moving_shuttle_bridge",
  "hazard_chicane_bridge",
  "vertical_lift_bridge",
];

export const NODE_CHUNK_FAMILIES = {
  [NODE_TYPES.START]: ["start_plaza", "start_ramp"],
  [NODE_TYPES.GOAL]: ["goal_platform", "goal_tower"],
  [NODE_TYPES.NONE]: ["open_room", "serpentine_room", "dual_lane_room", "arena_room"],
  [NODE_TYPES.PLATFORM]: ["open_room", "serpentine_room", "dual_lane_room", "arena_room"],
  [NODE_TYPES.JUMP]: ["gap_chain", "offset_islands", "ascending_jumps"],
  [NODE_TYPES.DROP]: ["drop_well", "stepped_drop", "spiral_drop"],
  [NODE_TYPES.ENEMY]: ["patrol_line", "cross_patrol", "choke_guard"],
  [NODE_TYPES.KEY]: ["safe_key_pocket", "risk_key_room", "timed_key_bridge"],
  [NODE_TYPES.LOCK]: ["center_gate", "offset_gate", "double_gate_hall"],
  Checkpoint: ["checkpoint_pocket", "checkpoint_bridge"],
};

const FALLBACK_NODE_FAMILIES = ["open_room"];

export function chooseNodePrimaryType(node) {
  const types = Array.isArray(node?.types) && node.types.length ? node.types : node?.type ? [node.type] : [NODE_TYPES.NONE];
  if (types.includes(NODE_TYPES.START)) return NODE_TYPES.START;
  if (types.includes(NODE_TYPES.GOAL)) return NODE_TYPES.GOAL;
  if (types.includes(NODE_TYPES.LOCK)) return NODE_TYPES.LOCK;
  if (types.includes(NODE_TYPES.KEY)) return NODE_TYPES.KEY;
  if (types.includes(NODE_TYPES.ENEMY)) return NODE_TYPES.ENEMY;
  if (types.includes(NODE_TYPES.JUMP)) return NODE_TYPES.JUMP;
  if (types.includes(NODE_TYPES.DROP)) return NODE_TYPES.DROP;
  if (types.includes(NODE_TYPES.PLATFORM)) return NODE_TYPES.PLATFORM;
  return NODE_TYPES.NONE;
}

export function listNodeFamilies(node) {
  const primary = chooseNodePrimaryType(node);
  const types = Array.isArray(node?.types) && node.types.length ? node.types : node?.type ? [node.type] : [NODE_TYPES.NONE];
  const families = new Set(NODE_CHUNK_FAMILIES[primary] || FALLBACK_NODE_FAMILIES);

  if (types.includes(NODE_TYPES.ENEMY)) {
    for (const name of NODE_CHUNK_FAMILIES[NODE_TYPES.ENEMY]) families.add(name);
  }
  if (types.includes(NODE_TYPES.KEY)) {
    for (const name of NODE_CHUNK_FAMILIES[NODE_TYPES.KEY]) families.add(name);
  }

  return Array.from(families);
}

export function listConnectorFamilies(edgeLength) {
  const length = Number(edgeLength) || 0;
  if (length < 16) {
    return ["linear_bridge", "stair_bridge", "arc_bridge", "zigzag_bridge"];
  }
  if (length > 42) {
    return [
      "linear_bridge",
      "stair_bridge",
      "arc_bridge",
      "zigzag_bridge",
      "split_merge_bridge",
      "moving_shuttle_bridge",
      "vertical_lift_bridge",
    ];
  }
  return CONNECTOR_FAMILIES.slice();
}

export function familyBaseComplexity(family) {
  switch (family) {
    case "linear_bridge":
    case "start_plaza":
    case "goal_platform":
    case "open_room":
      return 0.2;
    case "stair_bridge":
    case "arc_bridge":
    case "serpentine_room":
    case "drop_well":
      return 0.35;
    case "zigzag_bridge":
    case "dual_lane_room":
    case "goal_tower":
    case "ascending_jumps":
      return 0.5;
    case "split_merge_bridge":
    case "moving_shuttle_bridge":
    case "hazard_chicane_bridge":
    case "vertical_lift_bridge":
    case "arena_room":
    case "offset_islands":
    case "spiral_drop":
    case "cross_patrol":
    case "choke_guard":
    case "risk_key_room":
    case "timed_key_bridge":
    case "double_gate_hall":
      return 0.75;
    default:
      return 0.45;
  }
}

export function createProceduralObstacleCourse() {
  const platforms = [
    platform("start", "start", 0, 0, 0, 10, 1, 10),
    platform("approach", "approach", 9, 0.5, 0, 7, 1, 6),
    platform("split", "split", 18, 1, 0, 10, 1, 10),
    platform("safe_a", "safe", 28, 1, -8, 8, 1, 6),
    platform("safe_b", "safe", 38, 1, -8, 8, 1, 6),
    platform("risk_a", "risk", 28, 2, 8, 6, 1, 6),
    platform("risk_b", "risk", 38, 2, 8, 6, 1, 6),
    platform("merge", "merge", 48, 1, 0, 11, 1, 11),
    platform("gate", "gate", 60, 1, 0, 9, 1, 8),
    platform("finish", "goal", 72, 0.5, 0, 12, 1, 12),
  ];
  return {
    meta: { seed: "procedural-course", generator_mode: "procedural_obstacle_course", visual_theme: "manual" },
    start: { x: 0, y: 1, z: 0 },
    goal: { x: 72, y: 1.5, z: 0 },
    platforms,
    enemies: [],
    keys: [],
    locks: [],
    checkpoints: [],
    sweepers: [{ id: "safe_sweeper", node_id: "safe", pos: { x: 33, y: 2, z: -8 }, length: 8, period: 5 }],
    bumpers: [
      { id: "risk_bumper_0", node_id: "risk", pos: { x: 28, y: 3.3, z: 8 }, radius: 1.2 },
      { id: "risk_bumper_1", node_id: "risk", pos: { x: 38, y: 3.3, z: 8 }, radius: 1.2 },
    ],
    timed_gates: [{ id: "final_gate", node_id: "gate", pos: { x: 60, y: 2, z: 0 }, period: 6, openDuration: 3 }],
    mapping: { node: {}, edge: {} },
    anchors: {},
  };
}

function platform(id, nodeId, x, y, z, sx, sy, sz) {
  return { id, node_id: nodeId, pos: { x, y, z }, size: { x: sx, y: sy, z: sz } };
}

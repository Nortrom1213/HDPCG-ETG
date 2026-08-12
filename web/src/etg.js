import { pick } from "./random.js";
import { computeCanonicalRoute } from "./etg-utils.js";
import { NODE_TYPES, normalizeEtg, DEFAULT_SPEED } from "./etg-core.js";

export { NODE_TYPES };

export function createETG(config, rng) {
  const nodes = [];
  const edges = [];
  let nodeId = 0;
  let edgeId = 0;

  const difficulty = typeof config.difficulty === "number" ? config.difficulty : 0.5;
  const segmentCount = Math.max(4, config.length | 0);
  const lockAt = config.keyLock ? Math.max(2, Math.floor(segmentCount * 0.7)) : -1;
  const branchFromAt = config.keyLock ? Math.max(1, Math.floor(segmentCount * 0.35)) : -1;

  const addNode = (type, props = {}) => {
    const id = `N${nodeId++}`;
    const intensity = clamp01(props.intensity ?? difficulty);
    const node = { id, type, intensity };
    if (type === NODE_TYPES.KEY) node.key_id = props.key_id || "K1";
    if (type === NODE_TYPES.LOCK) {
      node.requires_key_id = props.requires_key_id || "K1";
      node.lock_id = props.lock_id || "L1";
    }
    nodes.push(node);
    return node;
  };

  const addEdge = (from, to, length) => {
    const id = `E${edgeId++}`;
    edges.push({ id, from, to, length });
    return id;
  };

  const start = addNode(NODE_TYPES.START, { intensity: 0.1 });
  let last = start;

  const spine = [start];
  for (let i = 0; i < segmentCount; i += 1) {
    if (config.keyLock && i === lockAt) {
      const lockNode = addNode(NODE_TYPES.LOCK, { intensity: Math.min(1, difficulty + 0.15), requires_key_id: "K1", lock_id: "L1" });
      addEdge(last.id, lockNode.id, sampleEdgeLength(difficulty, rng, "gate"));
      spine.push(lockNode);
      last = lockNode;
      continue;
    }

    const type = chooseSegmentType(difficulty, rng);
    const node = addNode(type, { intensity: clamp01(difficulty + (rng() - 0.5) * 0.25) });
    addEdge(last.id, node.id, sampleEdgeLength(difficulty, rng, type));
    spine.push(node);
    last = node;
  }

  const goal = addNode(NODE_TYPES.GOAL, { intensity: 0.1 });
  addEdge(last.id, goal.id, sampleEdgeLength(difficulty, rng, "end"));
  spine.push(goal);

  if (config.keyLock && lockAt >= 0) {
    const branchFrom = spine[Math.min(spine.length - 2, Math.max(0, branchFromAt))];
    const lockNode = spine.find((n) => n.type === NODE_TYPES.LOCK) || null;
    const rejoinTarget = lockNode ? spine[Math.max(0, spine.indexOf(lockNode) - 1)] : spine[Math.max(0, spine.length - 2)];
    const keyNode = addNode(NODE_TYPES.KEY, { intensity: Math.max(0.2, difficulty - 0.05), key_id: "K1" });
    addEdge(branchFrom.id, keyNode.id, sampleEdgeLength(difficulty, rng, "branch"));
    addEdge(keyNode.id, rejoinTarget.id, sampleEdgeLength(difficulty, rng, "branch"));
  }

  if (rng() < 0.25 && spine.length > 4) {
    const a = spine[Math.max(1, Math.floor(rng() * (spine.length - 3)))];
    const b = spine[Math.max(1, Math.floor(rng() * (spine.length - 2)))];
    if (a && b && a.id !== b.id) addEdge(b.id, a.id, sampleEdgeLength(difficulty, rng, "loop"));
  }

  return normalizeEtg({
    nodes,
    edges,
    meta: {
      seed: config.seed,
      defaultSpeed: DEFAULT_SPEED,
    },
  });
}

export function summarizeETG(etg) {
  const canonical = computeCanonicalRoute(etg, { defaultSpeed: etg?.meta?.defaultSpeed });
  return {
    node_count: Array.isArray(etg.nodes) ? etg.nodes.length : 0,
    edge_count: Array.isArray(etg.edges) ? etg.edges.length : 0,
    canonical_ok: Boolean(canonical.ok),
    canonical_total_length: canonical.ok ? Number(canonical.totalLength.toFixed(2)) : null,
    canonical_eta_seconds: canonical.ok ? Number(canonical.totalEtaSeconds.toFixed(2)) : null,
    canonical_nodes: canonical.ok ? canonical.nodes.slice() : [],
  };
}

function chooseSegmentType(difficulty, rng) {
  if (difficulty < 0.35) {
    return pick(rng, [NODE_TYPES.NONE, NODE_TYPES.PLATFORM, NODE_TYPES.PLATFORM]);
  }
  if (difficulty < 0.65) {
    return pick(rng, [NODE_TYPES.PLATFORM, NODE_TYPES.JUMP, NODE_TYPES.ENEMY, NODE_TYPES.DROP, NODE_TYPES.PLATFORM]);
  }
  return pick(rng, [NODE_TYPES.JUMP, NODE_TYPES.ENEMY, NODE_TYPES.DROP, NODE_TYPES.JUMP]);
}

function sampleEdgeLength(difficulty, rng, kind) {
  const base = 26 + difficulty * 18;
  let scale = 1.0;
  if (kind === NODE_TYPES.NONE) scale = 0.7;
  if (kind === NODE_TYPES.JUMP) scale = 0.9;
  if (kind === NODE_TYPES.DROP) scale = 0.85;
  if (kind === NODE_TYPES.ENEMY) scale = 0.95;
  if (kind === "gate") scale = 0.75;
  if (kind === "branch") scale = 0.8;
  if (kind === "loop") scale = 0.9;
  if (kind === "end") scale = 0.7;
  const jitter = 0.75 + rng() * 0.5;
  return Math.round(Math.max(12, base * scale * jitter));
}

function clamp01(x) {
  return Math.min(1, Math.max(0, Number(x) || 0));
}

export const ETG_VERSION = 2;

export const NODE_TYPES = {
  START: "Start",
  GOAL: "Goal",
  NONE: "None",
  PLATFORM: "Platform",
  JUMP: "Jump",
  DROP: "Drop",
  ENEMY: "Enemy",
  KEY: "Key",
  LOCK: "Lock",
};

export const NODE_TYPES_LIST = Object.values(NODE_TYPES);
export const GROUND_TYPES = new Set([
  NODE_TYPES.START,
  NODE_TYPES.GOAL,
  NODE_TYPES.NONE,
  NODE_TYPES.PLATFORM,
  NODE_TYPES.JUMP,
  NODE_TYPES.DROP,
]);
export const OVERLAY_TYPES = new Set([
  NODE_TYPES.ENEMY,
  NODE_TYPES.KEY,
  NODE_TYPES.LOCK,
]);

const DEFAULT_INTENSITY = 0.5;
const DEFAULT_INTENSITY_STRUCTURAL = 0.1;
const DEFAULT_EDGE_LENGTH = 30;
export const DEFAULT_SPEED = 7.5;

export function isEtg(etg) {
  return Boolean(etg && typeof etg === "object" && (etg.version === ETG_VERSION || etg.meta?.version === ETG_VERSION));
}

export function normalizeEtg(etg, options = {}) {
  if (!etg || typeof etg !== "object") {
    return createDefaultEtg();
  }

  const defaultSpeed = clampNumber(etg?.meta?.defaultSpeed ?? options.defaultSpeed ?? DEFAULT_SPEED, 0.1, 1000);
  const nodes = Array.isArray(etg.nodes) ? etg.nodes.map((node, idx) => normalizeNode(node, idx)) : [];
  const edges = Array.isArray(etg.edges) ? etg.edges.map((edge, idx) => normalizeEdge(edge, idx)) : [];

  return {
    version: ETG_VERSION,
    nodes,
    edges,
    meta: {
      ...(etg.meta || {}),
      defaultSpeed,
    },
  };
}

export function normalizeNode(node, fallbackIndex = 0) {
  const safe = node && typeof node === "object" ? node : {};
  const rawTypes = Array.isArray(safe.types) ? safe.types : safe.type ? [safe.type] : [];
  const normalizedTypes = uniqueList(
    rawTypes
      .map((t) => (typeof t === "string" ? t.trim() : ""))
      .filter((t) => NODE_TYPES_LIST.includes(t))
  );

  let types = normalizedTypes.length ? normalizedTypes : [NODE_TYPES.NONE];

  // Structural nodes cannot be mixed.
  if (types.includes(NODE_TYPES.START)) types = [NODE_TYPES.START];
  if (types.includes(NODE_TYPES.GOAL)) types = [NODE_TYPES.GOAL];

  // Overlay-only nodes get an implicit walkable ground.
  const hasGround = types.some((t) => GROUND_TYPES.has(t));
  const hasOverlay = types.some((t) => OVERLAY_TYPES.has(t));
  if (!hasGround && hasOverlay) types = [NODE_TYPES.NONE, ...types];

  // Choose the primary type used for UI color.
  const primary = choosePrimaryType(types);
  const isStructural = primary === NODE_TYPES.START || primary === NODE_TYPES.GOAL || primary === NODE_TYPES.NONE;
  const intensityDefault = isStructural ? DEFAULT_INTENSITY_STRUCTURAL : DEFAULT_INTENSITY;
  const intensity = clampNumber(safe.intensity ?? intensityDefault, 0, 1);

  const out = {
    id: typeof safe.id === "string" && safe.id.trim() ? safe.id : `N${fallbackIndex}`,
    type: primary,
    types,
    intensity,
  };

  if (types.includes(NODE_TYPES.KEY)) {
    out.key_id = typeof safe.key_id === "string" && safe.key_id.trim() ? safe.key_id.trim() : "K1";
  }
  if (types.includes(NODE_TYPES.LOCK)) {
    out.requires_key_id =
      typeof safe.requires_key_id === "string" && safe.requires_key_id.trim() ? safe.requires_key_id.trim() : "K1";
    if (typeof safe.lock_id === "string" && safe.lock_id.trim()) out.lock_id = safe.lock_id.trim();
  }

  return out;
}

export function normalizeEdge(edge, fallbackIndex = 0) {
  const safe = edge && typeof edge === "object" ? edge : {};
  const length = clampNumber(safe.length ?? DEFAULT_EDGE_LENGTH, 1, 100000);
  return {
    id: typeof safe.id === "string" && safe.id.trim() ? safe.id : `E${fallbackIndex}`,
    from: safe.from,
    to: safe.to,
    length,
  };
}

export function validateEtg(etg) {
  const issues = [];
  const warnings = [];

  if (!etg || typeof etg !== "object") {
    issues.push("ETG missing");
    return { ok: false, issues, warnings };
  }

  const nodes = Array.isArray(etg.nodes) ? etg.nodes : [];
  const edges = Array.isArray(etg.edges) ? etg.edges : [];

  const byId = new Map();
  for (const node of nodes) {
    if (!node?.id || typeof node.id !== "string") {
      issues.push("node missing id");
      continue;
    }
    if (byId.has(node.id)) issues.push(`duplicate node id ${node.id}`);
    byId.set(node.id, node);
    const types = Array.isArray(node.types) && node.types.length ? node.types : node.type ? [node.type] : [];
    if (!types.length) issues.push(`node ${node.id} missing types`);
    for (const t of types) {
      if (!NODE_TYPES_LIST.includes(t)) warnings.push(`node ${node.id} has unknown type ${t}`);
    }
    if (typeof node.intensity !== "number" || Number.isNaN(node.intensity)) warnings.push(`node ${node.id} intensity invalid`);

    const groundSet = new Set(types.filter((t) => [NODE_TYPES.PLATFORM, NODE_TYPES.JUMP, NODE_TYPES.DROP].includes(t)));
    if (groundSet.size > 1) warnings.push(`node ${node.id} has multiple ground types (${Array.from(groundSet).join(", ")})`);

    if (types.includes(NODE_TYPES.START) && types.length !== 1) warnings.push(`Start node ${node.id} should not mix types`);
    if (types.includes(NODE_TYPES.GOAL) && types.length !== 1) warnings.push(`Goal node ${node.id} should not mix types`);
  }

  const hasType = (n, t) => {
    const types = Array.isArray(n?.types) && n.types.length ? n.types : n?.type ? [n.type] : [];
    return types.includes(t);
  };
  const starts = nodes.filter((n) => hasType(n, NODE_TYPES.START));
  const goals = nodes.filter((n) => hasType(n, NODE_TYPES.GOAL));
  if (starts.length !== 1) issues.push(`expected exactly 1 Start, found ${starts.length}`);
  if (goals.length !== 1) issues.push(`expected exactly 1 Goal, found ${goals.length}`);

  for (const edge of edges) {
    if (!edge?.from || !edge?.to) {
      issues.push("edge missing from/to");
      continue;
    }
    if (!byId.has(edge.from) || !byId.has(edge.to)) {
      issues.push(`edge ${edge.id || "(no-id)"} connects missing node`);
    }
    if (!(typeof edge.length === "number") || !Number.isFinite(edge.length) || edge.length <= 0) {
      issues.push(`edge ${edge.id || "(no-id)"} length must be > 0`);
    }
  }

  // Undirected adjacency (edges are spatial connections).
  const neighborSetById = new Map();
  const addNeighbor = (a, b) => {
    if (!a || !b) return;
    if (a === b) return;
    if (!neighborSetById.has(a)) neighborSetById.set(a, new Set());
    neighborSetById.get(a).add(b);
  };
  for (const edge of edges) {
    if (!edge?.from || !edge?.to) continue;
    addNeighbor(edge.from, edge.to);
    addNeighbor(edge.to, edge.from);
  }

  // Key ids present in ETG.
  const keyIds = new Set(
    nodes
      .filter((n) => hasType(n, NODE_TYPES.KEY) && typeof n.key_id === "string" && n.key_id.trim())
      .map((n) => n.key_id.trim())
  );

  for (const node of nodes) {
    if (hasType(node, NODE_TYPES.KEY)) {
      if (!node.key_id) issues.push(`Key node ${node.id} missing key_id`);
    }
    if (hasType(node, NODE_TYPES.LOCK)) {
      if (!node.requires_key_id) issues.push(`Lock node ${node.id} missing requires_key_id`);
      // Hard constraint: Lock must connect exactly two (distinct) neighbors.
      const neighbors = neighborSetById.get(node.id) || new Set();
      if (neighbors.size !== 2) {
        issues.push(`Lock node ${node.id} must have degree 2 (found ${neighbors.size})`);
      }
      // Lock should reference an existing key id to be meaningful.
      if (node.requires_key_id && !keyIds.has(node.requires_key_id)) {
        issues.push(`Lock node ${node.id} requires missing key_id ${node.requires_key_id}`);
      }
      // Check whether the lock is required for connectivity.
      if (neighbors.size === 2) {
        const [a, b] = Array.from(neighbors);
        const connected = isConnectedWithout(nodes, neighborSetById, node.id, a, b);
        if (connected) warnings.push(`Lock node ${node.id} neighbors remain connected without the lock (may not gate)`);
      }
    }
  }

  return { ok: issues.length === 0, issues, warnings };
}

function isConnectedWithout(nodes, neighborSetById, blockedNodeId, startId, goalId) {
  if (!startId || !goalId) return false;
  if (startId === goalId) return true;
  const nodeIds = new Set((nodes || []).map((n) => n?.id).filter(Boolean));
  if (!nodeIds.has(startId) || !nodeIds.has(goalId)) return false;
  const blocked = String(blockedNodeId);
  const visited = new Set([startId]);
  const queue = [startId];
  let head = 0;
  while (head < queue.length) {
    const current = queue[head++];
    const neighbors = neighborSetById.get(current);
    if (!neighbors) continue;
    for (const next of neighbors) {
      if (!next || next === blocked) continue;
      if (current === blocked) continue;
      if (visited.has(next)) continue;
      if (!nodeIds.has(next)) continue;
      if (next === goalId) return true;
      visited.add(next);
      queue.push(next);
    }
  }
  return false;
}

export function computeCanonicalRoute(etg, options = {}) {
  const defaultSpeed = clampNumber(etg?.meta?.defaultSpeed ?? options.defaultSpeed ?? DEFAULT_SPEED, 0.1, 1000);
  const nodes = Array.isArray(etg?.nodes) ? etg.nodes : [];
  const edges = Array.isArray(etg?.edges) ? etg.edges : [];
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const hasType = (n, t) => {
    const types = Array.isArray(n?.types) && n.types.length ? n.types : n?.type ? [n.type] : [];
    return types.includes(t);
  };
  const start = nodes.find((n) => hasType(n, NODE_TYPES.START)) || null;
  const goal = nodes.find((n) => hasType(n, NODE_TYPES.GOAL)) || null;
  if (!start || !goal) {
    return {
      ok: false,
      reason: "missing Start/Goal",
      nodes: [],
      edges: [],
      totalLength: 0,
      totalEtaSeconds: 0,
      defaultSpeed,
    };
  }

  // Key ids -> bit index.
  const keyIds = Array.from(
    new Set(nodes.filter((n) => hasType(n, NODE_TYPES.KEY) && n.key_id).map((n) => n.key_id))
  );
  const keyIndex = new Map(keyIds.map((id, idx) => [id, idx]));
  const keyMaskOfNode = new Map();
  const lockReqIndexOfNode = new Map();
  for (const n of nodes) {
    if (hasType(n, NODE_TYPES.KEY) && n.key_id && keyIndex.has(n.key_id)) {
      keyMaskOfNode.set(n.id, 1 << keyIndex.get(n.key_id));
    }
    if (hasType(n, NODE_TYPES.LOCK) && n.requires_key_id && keyIndex.has(n.requires_key_id)) {
      lockReqIndexOfNode.set(n.id, keyIndex.get(n.requires_key_id));
    }
  }

  // Treat edges as spatial connections: traversable in both directions.
  const edgesByFrom = new Map();
  for (const e of edges) {
    if (!e?.from || !e?.to) continue;
    if (!edgesByFrom.has(e.from)) edgesByFrom.set(e.from, []);
    if (!edgesByFrom.has(e.to)) edgesByFrom.set(e.to, []);
    edgesByFrom.get(e.from).push({ edge: e, to: e.to });
    edgesByFrom.get(e.to).push({ edge: e, to: e.from });
  }

  // Dijkstra on (nodeId, tokenMask).
  const startMask = keyMaskOfNode.get(start.id) || 0;
  const startState = makeStateKey(start.id, startMask);
  const dist = new Map([[startState, 0]]);
  const prev = new Map();
  const pq = new MinHeap();
  pq.push({ key: startState, cost: 0 });

  let goalState = null;
  while (!pq.isEmpty()) {
    const current = pq.pop();
    if (!current) break;
    const { key, cost } = current;
    if (cost !== dist.get(key)) continue;
    const { nodeId, mask } = parseStateKey(key);
    if (nodeId === goal.id) {
      goalState = key;
      break;
    }
    const outgoing = edgesByFrom.get(nodeId) || [];
    for (const step of outgoing) {
      const e = step.edge;
      const toNode = byId.get(step.to);
      if (!toNode) continue;
      const length = typeof e.length === "number" && Number.isFinite(e.length) ? e.length : DEFAULT_EDGE_LENGTH;
      let nextMask = mask;

      if (hasType(toNode, NODE_TYPES.LOCK)) {
        const reqIdx = lockReqIndexOfNode.get(toNode.id);
        if (reqIdx !== undefined) {
          const has = (mask & (1 << reqIdx)) !== 0;
          if (!has) continue;
        } else {
          if (toNode.requires_key_id) continue;
        }
      }

      nextMask |= keyMaskOfNode.get(toNode.id) || 0;

      const nextKey = makeStateKey(toNode.id, nextMask);
      const nextCost = cost + Math.max(1e-6, length);
      const best = dist.get(nextKey);
      if (best === undefined || nextCost < best) {
        dist.set(nextKey, nextCost);
        prev.set(nextKey, { prevKey: key, edgeId: e.id || null });
        pq.push({ key: nextKey, cost: nextCost });
      }
    }
  }

  if (!goalState) {
    return {
      ok: false,
      reason: "no feasible path (check Key/Lock connectivity or missing keys)",
      nodes: [],
      edges: [],
      totalLength: 0,
      totalEtaSeconds: 0,
      defaultSpeed,
    };
  }

  const stateTrail = [];
  let cursor = goalState;
  while (cursor) {
    stateTrail.push(cursor);
    const step = prev.get(cursor);
    cursor = step?.prevKey || null;
  }
  stateTrail.reverse();

  const routeNodes = [];
  const routeEdges = [];
  let totalLength = 0;
  for (let i = 0; i < stateTrail.length; i += 1) {
    const { nodeId } = parseStateKey(stateTrail[i]);
    routeNodes.push(nodeId);
    const step = prev.get(stateTrail[i]);
    if (step?.edgeId) {
      routeEdges.push(step.edgeId);
      const edgeObj = edges.find((x) => x.id === step.edgeId);
      if (edgeObj?.length) totalLength += edgeObj.length;
    }
  }

  return {
    ok: true,
    reason: null,
    nodes: routeNodes,
    edges: routeEdges,
    totalLength,
    totalEtaSeconds: totalLength / defaultSpeed,
    defaultSpeed,
  };
}

function choosePrimaryType(types) {
  if (types.includes(NODE_TYPES.START)) return NODE_TYPES.START;
  if (types.includes(NODE_TYPES.GOAL)) return NODE_TYPES.GOAL;
  if (types.includes(NODE_TYPES.JUMP)) return NODE_TYPES.JUMP;
  if (types.includes(NODE_TYPES.DROP)) return NODE_TYPES.DROP;
  if (types.includes(NODE_TYPES.PLATFORM)) return NODE_TYPES.PLATFORM;
  if (types.includes(NODE_TYPES.NONE)) return NODE_TYPES.NONE;
  return NODE_TYPES.NONE;
}

function uniqueList(items) {
  return Array.from(new Set((items || []).filter(Boolean)));
}

export function createDefaultEtg() {
  return normalizeEtg({
    version: ETG_VERSION,
    nodes: [
      { id: "N0", type: NODE_TYPES.START, intensity: DEFAULT_INTENSITY_STRUCTURAL },
      { id: "N1", type: NODE_TYPES.NONE, intensity: DEFAULT_INTENSITY_STRUCTURAL },
      { id: "N2", type: NODE_TYPES.GOAL, intensity: DEFAULT_INTENSITY_STRUCTURAL },
    ],
    edges: [
      { id: "E0", from: "N0", to: "N1", length: 20 },
      { id: "E1", from: "N1", to: "N2", length: 20 },
    ],
    meta: { defaultSpeed: DEFAULT_SPEED },
  });
}

function clampNumber(value, min, max) {
  const n = Number(value);
  if (!Number.isFinite(n)) return min;
  return Math.min(max, Math.max(min, n));
}

function makeStateKey(nodeId, mask) {
  return `${nodeId}@@${mask}`;
}

function parseStateKey(key) {
  const idx = key.lastIndexOf("@@");
  if (idx < 0) return { nodeId: key, mask: 0 };
  return { nodeId: key.slice(0, idx), mask: Number(key.slice(idx + 2)) || 0 };
}

class MinHeap {
  constructor() {
    this._data = [];
  }

  isEmpty() {
    return this._data.length === 0;
  }

  push(item) {
    this._data.push(item);
    this._bubbleUp(this._data.length - 1);
  }

  pop() {
    if (this._data.length === 0) return null;
    const root = this._data[0];
    const last = this._data.pop();
    if (this._data.length > 0) {
      this._data[0] = last;
      this._bubbleDown(0);
    }
    return root;
  }

  _bubbleUp(index) {
    while (index > 0) {
      const parent = Math.floor((index - 1) / 2);
      if (this._data[parent].cost <= this._data[index].cost) break;
      const tmp = this._data[parent];
      this._data[parent] = this._data[index];
      this._data[index] = tmp;
      index = parent;
    }
  }

  _bubbleDown(index) {
    const len = this._data.length;
    while (true) {
      const left = index * 2 + 1;
      const right = index * 2 + 2;
      let smallest = index;
      if (left < len && this._data[left].cost < this._data[smallest].cost) smallest = left;
      if (right < len && this._data[right].cost < this._data[smallest].cost) smallest = right;
      if (smallest === index) break;
      const tmp = this._data[smallest];
      this._data[smallest] = this._data[index];
      this._data[index] = tmp;
      index = smallest;
    }
  }
}

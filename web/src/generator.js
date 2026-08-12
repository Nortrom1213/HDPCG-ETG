import { randRange } from "./random.js";
import { NODE_TYPES } from "./etg-core.js";
import { computeCanonicalRoute } from "./etg-utils.js";
import { generateLevelIncremental } from "./generator-hdpcg.js";
import { validateLocalTopology } from "./hdpcg-local-validate.js";

const PLATFORM_SIZE = { x: 3, y: 1, z: 3 };
const TURN_CHANCE = 0.35;
const DEFAULT_EDGE_LENGTH = 30;
const LOCK_GATE_SPAN = 18;
const LOCK_CORRIDOR_WIDTH = 4.2;
const LOCK_GATE_HEIGHT = 7.0;

export function generateLevel(etg, config, rng) {
  const mode = String(config.generatorMode || config.generator_mode || "").trim();
  if (!mode || mode === "hdpcg_incremental" || mode === "incremental") {
    const enableValidate = config.topologyValidate !== false && config.localValidate !== false;
    const extraConnectivityPolicy =
      config.extra_connectivity_policy || config.extraConnectivityPolicy || "strict_1hop";
    const hooks = enableValidate
      ? {
          validatePlacement: ({ level, boundsDelta, fromId, toId }) =>
            validateLocalTopology({
              level,
              etg,
              fromId,
              toId,
              boundsDelta,
              extraConnectivityPolicy,
              cellSize: config.validationCellSize ?? 1,
              timeStep: config.validationTimeStep ?? 1,
              modelPadding: config.validationModelPadding ?? 2,
              localPaddingCells: config.validationLocalPaddingCells ?? 3,
              maxTime: config.validationMaxTime ?? 160,
              maxStates: config.validationMaxStates ?? 120000,
              maxQueue: config.validationMaxQueue ?? 90000,
              maxJumpOffsets: config.validationMaxJumpOffsets ?? 900,
              allowJump: config.validationAllowJump ?? true,
              allowDrop: config.validationAllowDrop ?? true,
              toleranceRadiusCells:
                config.validationToleranceRadiusCells ??
                config.toleranceRadiusCells ??
                config.toleranceRadius ??
                2,
              allowSiblingTolerance: config.validationAllowSiblingTolerance ?? true,
            }),
        }
      : {};
    return generateLevelIncremental(etg, config, rng, hooks);
  }
  if (mode === "constraint_based" || mode === "constraint") {
    return generateLevelIncremental(
      etg,
      {
        ...config,
        generatorMode: "constraint_based",
      },
      rng,
      {}
    );
  }
  return generateLevelLane(etg, config, rng);
}

function generateLevelLane(etg, config = {}, rng) {
  const level = {
    meta: {
      seed: config.seed,
      config: { ...config },
      etg_version: 2,
    },
    etg,
    platforms: [],
    enemies: [],
    keys: [],
    locks: [],
    checkpoints: [],
    start: null,
    goal: null,
    mapping: {
      node: {},
      edge: {},
    },
    anchors: {},
  };

  let platformId = 0;
  let enemyId = 0;
  let keyId = 0;
  let lockId = 0;
  let checkpointId = 0;

  const difficulty = typeof config.difficulty === "number" ? config.difficulty : 0.5;
  const maxGap = 4.5 + difficulty * 1.5;
  const maxVertical = 2.6 + difficulty * 0.6;

  const platformById = new Map();

  const addPlatform = (pos, size, opts = {}) => {
    const id = `P${platformId++}`;
    const platform = {
      id,
      pos: { ...pos },
      size: { ...size },
      kind: opts.kind || "static",
      motion: opts.motion || null,
      tags: opts.tags || [],
      node_id: opts.node_id || null,
    };
    level.platforms.push(platform);
    platformById.set(id, platform);
    return platform;
  };

  const addEnemy = (pos, patrol, opts = {}) => {
    const id = `E${enemyId++}`;
    const enemy = {
      id,
      pos: { ...pos },
      radius: opts.radius ?? 0.6,
      patrol,
      speed: opts.speed ?? 1.2,
      node_id: opts.node_id || null,
    };
    level.enemies.push(enemy);
    return enemy;
  };

  const addKey = (pos, key_id, opts = {}) => {
    const id = `K${keyId++}`;
    const key = {
      id,
      key_id,
      pos: { ...pos },
      radius: 0.4,
      node_id: opts.node_id || null,
    };
    level.keys.push(key);
    return key;
  };

  const addLock = (pos, lock_id, key_id, opts = {}) => {
    const id = `L${lockId++}`;
    const lock = {
      id,
      lock_id,
      key_id,
      pos: { ...pos },
      size: opts.size || { x: 2, y: 3, z: 0.6 },
      node_id: opts.node_id || null,
      locked: true,
    };
    level.locks.push(lock);
    return lock;
  };

  const addCheckpoint = (pos, opts = {}) => {
    const id = `C${checkpointId++}`;
    const checkpoint = {
      id,
      pos: { ...pos },
      radius: 0.6,
      node_id: opts.node_id || null,
    };
    level.checkpoints.push(checkpoint);
    return checkpoint;
  };

  const ensureNodeMap = (nodeId) => {
    if (!level.mapping.node[nodeId]) {
      level.mapping.node[nodeId] = {
        platforms: [],
        enemies: [],
        keys: [],
        locks: [],
        checkpoints: [],
      };
    }
    return level.mapping.node[nodeId];
  };

  const recordPlatform = (nodeId, platform) => {
    const map = ensureNodeMap(nodeId);
    map.platforms.push(platform.id);
  };
  const recordEnemy = (nodeId, enemy) => {
    const map = ensureNodeMap(nodeId);
    map.enemies.push(enemy.id);
  };
  const recordKey = (nodeId, key) => {
    const map = ensureNodeMap(nodeId);
    map.keys.push(key.id);
  };
  const recordLock = (nodeId, lock) => {
    const map = ensureNodeMap(nodeId);
    map.locks.push(lock.id);
  };
  const recordCheckpoint = (nodeId, checkpoint) => {
    const map = ensureNodeMap(nodeId);
    map.checkpoints.push(checkpoint.id);
  };

  const nodeById = new Map((etg.nodes || []).map((n) => [n.id, n]));
  const edgesById = new Map((etg.edges || []).map((e) => [e.id, e]));

  const canonical = computeCanonicalRoute(etg, { defaultSpeed: etg?.meta?.defaultSpeed });
  level.meta.canonical = canonical.ok
    ? {
        ok: true,
        totalLength: canonical.totalLength,
        totalEtaSeconds: canonical.totalEtaSeconds,
        nodes: canonical.nodes.slice(),
        edges: canonical.edges.slice(),
        defaultSpeed: canonical.defaultSpeed,
      }
    : { ok: false, reason: canonical.reason || "no route" };

  if (!canonical.ok) {
    // Return a minimal level when no canonical route exists.
    const startNode = (etg.nodes || []).find((n) => n.type === NODE_TYPES.START) || { id: "Start", type: NODE_TYPES.START, intensity: 0.1 };
    const platform = addPlatform({ x: 0, y: 0, z: 0 }, PLATFORM_SIZE, { node_id: startNode.id, tags: [startNode.type] });
    recordPlatform(startNode.id, platform);
    level.start = { ...platform.pos };
    level.goal = { x: platform.pos.x + 12, y: platform.pos.y, z: platform.pos.z };
    level.anchors[startNode.id] = { entry: { ...platform.pos }, exit: { ...platform.pos }, heading: { x: 1, z: 0 } };
    return level;
  }

  // Spatial semantics:
  // - Nodes are "experience chunks" (Platform/Jump/Drop/Enemy/Key/Lock/None).
  // - Edges are walkable spatial connectors with explicit length.
  // - Branches are placed onto separate spatial lanes (different z) to form distinct routes.
  // - Fixed-direction placement keeps geometry readable and consistent with edge lengths.

  const helpers = {
    maxGap,
    maxVertical,
    addPlatform,
    addEnemy,
    addKey,
    addLock,
    addCheckpoint,
    recordPlatform,
    recordEnemy,
    recordKey,
    recordLock,
    recordCheckpoint,
    platformById,
  };

  const canonicalNodes = canonical.nodes.map((id) => nodeById.get(id)).filter(Boolean);
  const canonicalEdges = canonical.edges.map((id) => edgesById.get(id)).filter(Boolean);
  const canonicalEdgeIdSet = new Set((canonical.edges || []).filter(Boolean));

  const laneSpacing = 22;
  const laneByNode = new Map();
  const allocateLane = makeLaneAllocator();

  // Fixed forward direction (+x). Lanes are global z offsets.
  const forwardHeading = { x: 1, z: 0 };

  const builtNodes = new Set();

  // Pre-assign lanes for canonical route: keep the main flow on lane 0, but push loop-only
  // subpaths between repeated node occurrences to unique side lanes. A Key detour such as
  // A -> Key -> A remains a spatial branch even when it lies on the canonical route.
  assignCanonicalLanes(canonicalNodes, laneByNode, allocateLane);

  // Build canonical route on lane 0.
  let cursor = { x: 0, y: 0, z: 0 };
  for (let i = 0; i < canonicalNodes.length; i += 1) {
    const node = canonicalNodes[i];
    const lane = laneByNode.get(node.id) ?? 0;
    const laneZ = lane * laneSpacing;
    const arrival = { ...cursor, z: laneZ };

    if (!builtNodes.has(node.id)) {
      const chunk = buildNodeChunk(node, arrival, forwardHeading, rng, helpers);
      level.anchors[node.id] = { entry: chunk.entry, exit: chunk.exit, heading: { ...forwardHeading } };
      builtNodes.add(node.id);
      if (node.type === NODE_TYPES.START) level.start = { ...chunk.entry };
      if (node.type === NODE_TYPES.GOAL) level.goal = { ...chunk.exit };
      cursor = { ...chunk.exit };
    } else {
      // We are revisiting a node on the canonical route (loop/back-edge).
      // Snap to its entry for arrival, then continue from its exit.
      const anchor = level.anchors[node.id];
      cursor = { ...(anchor?.exit || cursor), z: laneZ };
    }

    const edge = canonicalEdges[i] || null;
    const nextNode = canonicalNodes[i + 1] || null;
    if (!edge || !nextNode) continue;

    const connectorStart = { ...cursor };
    const nextLane = laneByNode.get(nextNode.id) ?? 0;
    const nextZ = nextLane * laneSpacing;
    const edgeLength = edge.length ?? DEFAULT_EDGE_LENGTH;

    // Reuse an edge already materialized by an out-and-back canonical traversal.
    const alreadyBuilt = Boolean(level.mapping.edge[edge.id]);
    if (!alreadyBuilt) {
      const targetEntry = builtNodes.has(nextNode.id) && level.anchors[nextNode.id]
        ? { ...level.anchors[nextNode.id].entry }
        : computeConnectorEndpoint(cursor, lane, nextLane, nextZ, edgeLength, laneSpacing);
      targetEntry.z = nextZ;
      const connector = buildEdgeConnector(edge, connectorStart, targetEntry, rng, helpers);
      level.mapping.edge[edge.id] = {
        from: edge.from,
        to: edge.to,
        entry: connector.entry,
        exit: connector.exit,
        constraints: { length: edgeLength },
      };
      cursor = { ...targetEntry };
    } else {
      // Snap to the next node's lane; geometry is already traversable.
      if (builtNodes.has(nextNode.id) && level.anchors[nextNode.id]) {
        cursor = { ...level.anchors[nextNode.id].exit, z: nextZ };
      } else {
        cursor = { x: cursor.x, y: cursor.y, z: nextZ };
      }
    }
  }

  // Build remaining edges as branch/loop connectors. New nodes get their own lane.
  const pending = (etg.edges || []).filter((e) => e && !canonicalEdgeIdSet.has(e.id));
  let progress = true;
  while (pending.length > 0 && progress) {
    progress = false;
    for (let i = pending.length - 1; i >= 0; i -= 1) {
      const edge = pending[i];
      const fromNode = nodeById.get(edge.from);
      const toNode = nodeById.get(edge.to);
      if (!fromNode || !toNode) {
        pending.splice(i, 1);
        continue;
      }
      if (!builtNodes.has(fromNode.id) || !level.anchors[fromNode.id]) continue;

      const fromExit = level.anchors[fromNode.id].exit;
      const fromLane = laneByNode.get(fromNode.id) ?? 0;
      const existingLane = laneByNode.get(toNode.id);
      const toLane = existingLane !== undefined ? existingLane : allocateLane();
      laneByNode.set(toNode.id, toLane);
      const targetZ = toLane * laneSpacing;

      const alreadyBuilt = Boolean(level.mapping.edge[edge.id]);
      const toEntry = builtNodes.has(toNode.id) && level.anchors[toNode.id]
        ? { ...level.anchors[toNode.id].entry }
        : computeConnectorEndpoint(fromExit, fromLane, toLane, targetZ, edge.length ?? DEFAULT_EDGE_LENGTH, laneSpacing);
      if (!alreadyBuilt) {
        const connector = buildEdgeConnector(edge, fromExit, toEntry, rng, helpers);
        level.mapping.edge[edge.id] = {
          from: edge.from,
          to: edge.to,
          entry: connector.entry,
          exit: connector.exit,
          constraints: { length: edge.length ?? DEFAULT_EDGE_LENGTH },
        };
      }

      if (!builtNodes.has(toNode.id)) {
        const chunk = buildNodeChunk(toNode, toEntry, forwardHeading, rng, helpers);
        level.anchors[toNode.id] = { entry: chunk.entry, exit: chunk.exit, heading: { ...forwardHeading } };
        builtNodes.add(toNode.id);
      }

      pending.splice(i, 1);
      progress = true;
    }
  }

  return level;
}

function computeConnectorEndpoint(fromPos, fromLane, toLane, targetZ, length, laneSpacing) {
  const L = Math.max(1, Number(length) || DEFAULT_EDGE_LENGTH);
  if (fromLane === toLane) {
    return { x: fromPos.x + L, y: fromPos.y, z: targetZ };
  }

  const dzWanted = targetZ - fromPos.z;
  const maxDz = L * 0.92;
  const dz = Math.abs(dzWanted) > maxDz ? Math.sign(dzWanted) * maxDz : dzWanted;
  const dx = Math.sqrt(Math.max(0, L * L - dz * dz));
  const leadX = Math.max(6, dx);
  return { x: fromPos.x + leadX, y: fromPos.y, z: fromPos.z + dz };
}

function makeLaneAllocator() {
  // Produces 1, -1, 2, -2, 3, -3...
  let k = 1;
  let sign = 1;
  return () => {
    const out = sign * k;
    if (sign === 1) {
      sign = -1;
    } else {
      sign = 1;
      k += 1;
    }
    return out;
  };
}

function assignCanonicalLanes(canonicalNodes, laneByNode, allocateLane) {
  const firstIndex = new Map();
  for (let i = 0; i < canonicalNodes.length; i += 1) {
    const node = canonicalNodes[i];
    if (!node?.id) continue;
    if (!firstIndex.has(node.id)) {
      firstIndex.set(node.id, i);
      laneByNode.set(node.id, 0);
      continue;
    }
    const start = firstIndex.get(node.id);
    // Nodes strictly inside the loop become a side lane branch.
    const lane = allocateLane();
    for (let j = start + 1; j < i; j += 1) {
      const inner = canonicalNodes[j];
      if (!inner?.id) continue;
      // Move only the detour nodes.
      if ((laneByNode.get(inner.id) ?? 0) === 0) {
        laneByNode.set(inner.id, lane);
      }
    }
  }
}

function buildEdgeConnector(edge, fromPos, toPos, rng, helpers) {
  const edgeKey = `edge:${edge.id}`;
  const distance = Math.hypot(toPos.x - fromPos.x, toPos.z - fromPos.z);
  const step = 6.0;
  const steps = clampInt(Math.round(distance / step), 1, 40);
  const size = { x: 7.5, y: 0.8, z: 6.5 };
  let entry = null;
  let exit = null;
  for (let i = 1; i <= steps; i += 1) {
    const t = i / (steps + 1);
    const pos = {
      x: fromPos.x + (toPos.x - fromPos.x) * t,
      y: fromPos.y + (toPos.y - fromPos.y) * t,
      z: fromPos.z + (toPos.z - fromPos.z) * t,
    };
    const platform = helpers.addPlatform(pos, size, { node_id: edgeKey, tags: ["connector"] });
    helpers.recordPlatform(edgeKey, platform);
    if (!entry) entry = { ...pos };
    exit = { ...pos };
  }
  if (!entry) entry = { ...fromPos };
  if (!exit) exit = { ...toPos };
  return { entry, exit };
}

function buildNodeChunk(node, entryPos, heading, rng, helpers) {
  const types = Array.isArray(node?.types) && node.types.length ? node.types : node?.type ? [node.type] : [NODE_TYPES.NONE];
  const has = (t) => types.includes(t);
  const groundType =
    has(NODE_TYPES.START) ? NODE_TYPES.START :
    has(NODE_TYPES.GOAL) ? NODE_TYPES.GOAL :
    has(NODE_TYPES.JUMP) ? NODE_TYPES.JUMP :
    has(NODE_TYPES.DROP) ? NODE_TYPES.DROP :
    has(NODE_TYPES.PLATFORM) ? NODE_TYPES.PLATFORM :
    has(NODE_TYPES.NONE) ? NODE_TYPES.NONE :
    NODE_TYPES.NONE;
  const intensity = clamp(node?.intensity ?? 0.5, 0, 1);

  // Lock nodes are modeled as a dedicated gate corridor so they reliably separate two sides.
  if (has(NODE_TYPES.LOCK)) {
    return buildLockGateChunkV2(node, entryPos, heading, rng, helpers);
  }

  // Default chunk parameters (localized experience; edge connectors provide the long travel distance).
  let count = 2 + Math.round(intensity * 4);
  let gap = 2.2 + intensity * 1.8;
  let verticalStep = 0;
  let verticalVariance = 0.0;
  let size = { ...PLATFORM_SIZE };
  let tags = [groundType];

  const isStructural = groundType === NODE_TYPES.START || groundType === NODE_TYPES.GOAL;
  if (isStructural || groundType === NODE_TYPES.NONE) {
    // Walkable chunk.
    count = 1;
    gap = 0;
    verticalStep = 0;
    verticalVariance = 0;
    size = { x: 9, y: 1, z: 7 };
    tags = [groundType, "walkable"];
  } else if (groundType === NODE_TYPES.PLATFORM) {
    // Horizontal jump challenge.
    verticalVariance = 0.05 + 0.15 * intensity;
  } else if (groundType === NODE_TYPES.JUMP) {
    // Upward jump challenge.
    verticalStep = Math.min(helpers.maxVertical, 0.7 + intensity * 2.0);
    verticalVariance = 0.05;
  } else if (groundType === NODE_TYPES.DROP) {
    // Downward jump/descending challenge.
    verticalStep = -Math.min(helpers.maxVertical, 0.7 + intensity * 2.0);
    verticalVariance = 0.05;
  }

  // Overlay types receive walkable ground by default and render as entities.
  if (has(NODE_TYPES.ENEMY) && groundType === NODE_TYPES.NONE) {
    count = clampInt(2 + Math.round(intensity * 2), 2, 5);
    gap = 0.4;
    size = { x: 7, y: 1, z: 6 };
    tags = [groundType, "walkable"];
  }
  if ((has(NODE_TYPES.KEY) || has(NODE_TYPES.LOCK)) && groundType === NODE_TYPES.NONE) {
    count = 1;
    gap = 0;
    size = { x: 8, y: 1, z: 6 };
    tags = [groundType, "walkable"];
  }

  count = clampInt(count, 1, 10);

  const forward = normalizeHeading(heading);
  let x = entryPos.x;
  let y = entryPos.y;
  let z = entryPos.z;

  const step = size.x + Math.max(0, gap);
  let entry = null;
  let exit = null;
  let exitPlatformId = null;

  for (let i = 0; i < count; i += 1) {
    const pos = { x, y, z };
    const platform = helpers.addPlatform(pos, size, { node_id: node.id, tags });
    helpers.recordPlatform(node.id, platform);
    if (!entry) entry = { ...pos };
    exit = { ...pos };
    exitPlatformId = platform.id;

    x += forward.x * step;
    z += forward.z * step;
    if (verticalStep !== 0) {
      y += verticalStep;
    } else if (verticalVariance > 0) {
      y += randRange(rng, -verticalVariance, verticalVariance);
    }
  }

  if (has(NODE_TYPES.ENEMY)) {
    const enemyCount = clampInt(1 + Math.floor(intensity * 3.2), 1, 5);
    const patrolLength = 3.5 + intensity * 6.0;
    const speed = 1.0 + intensity * 2.5 + rng() * 0.4;
    const height = 0.8 + intensity * 0.6;
    applyEnemies(node, { count: enemyCount, patrol_length: patrolLength, speed, height }, entry, exit, helpers, rng);
  }

  if (has(NODE_TYPES.KEY)) {
    const keyId = node.key_id || "K1";
    const key = helpers.addKey({ x: entry.x, y: entry.y + 1.0, z: entry.z }, keyId, { node_id: node.id });
    helpers.recordKey(node.id, key);
  }

  return { entry, exit };
}

function buildLockGateChunkV2(node, entryPos, heading, rng, helpers) {
  const forward = snapHeadingToAxis(heading);
  const span = clampInt(node?.gate_span ?? LOCK_GATE_SPAN, 10, 60);
  const width = clamp(node?.gate_width ?? LOCK_CORRIDOR_WIDTH, 2.4, 12);
  const height = clamp(node?.gate_height ?? LOCK_GATE_HEIGHT, 3.5, 18);

  const exit = {
    x: entryPos.x + forward.x * span,
    y: entryPos.y,
    z: entryPos.z + forward.z * span,
  };
  const mid = {
    x: (entryPos.x + exit.x) * 0.5,
    y: entryPos.y,
    z: (entryPos.z + exit.z) * 0.5,
  };

  const corridorSize = forward.x !== 0
    ? { x: span + 8, y: 1, z: width }
    : { x: width, y: 1, z: span + 8 };

  const platform = helpers.addPlatform(mid, corridorSize, { node_id: node.id, tags: [NODE_TYPES.NONE, "walkable", "lock_gate"] });
  helpers.recordPlatform(node.id, platform);

  const requires = node.requires_key_id || "K1";
  const lockId = node.lock_id || "L1";
  const lockThickness = 0.85;
  const lockSize = forward.x !== 0
    ? { x: lockThickness, y: height, z: width + 1.6 }
    : { x: width + 1.6, y: height, z: lockThickness };

  const topY = mid.y + corridorSize.y * 0.5;
  const lockPos = {
    x: mid.x,
    y: topY + lockSize.y * 0.5,
    z: mid.z,
  };
  const lock = helpers.addLock(lockPos, lockId, requires, { node_id: node.id, size: lockSize });
  helpers.recordLock(node.id, lock);

  return { entry: { ...entryPos }, exit, heading: forward };
}

function snapHeadingToAxis(heading) {
  const len = Math.hypot(heading.x, heading.z) || 1;
  const hx = heading.x / len;
  const hz = heading.z / len;
  if (Math.abs(hx) >= Math.abs(hz)) return { x: hx >= 0 ? 1 : -1, z: 0 };
  return { x: 0, z: hz >= 0 ? 1 : -1 };
}

function applyEnemies(node, spec, entry, exit, helpers, rng) {
  if (!spec) return;
  const count = Math.max(1, spec.count ?? 1);
  const patrolLength = spec.patrol_length ?? 4.5;
  const height = spec.height ?? 0.8;
  const axis = normalizeHeading({ x: exit.x - entry.x, z: exit.z - entry.z });
  const mid = { x: (entry.x + exit.x) * 0.5, y: entry.y + height, z: (entry.z + exit.z) * 0.5 };

  for (let i = 0; i < count; i += 1) {
    const offset = (i - (count - 1) / 2) * 1.2;
    const centerX = mid.x + axis.x * offset;
    const centerZ = mid.z + axis.z * offset;
    const patrol = {
      from: { x: centerX - axis.x * patrolLength * 0.5, y: entry.y + height, z: centerZ - axis.z * patrolLength * 0.5 },
      to: { x: centerX + axis.x * patrolLength * 0.5, y: entry.y + height, z: centerZ + axis.z * patrolLength * 0.5 },
    };
    const enemy = helpers.addEnemy({ x: centerX, y: entry.y + height, z: centerZ }, patrol, {
      node_id: node.id,
      speed: spec.speed ?? 1.1 + rng() * 0.8,
    });
    helpers.recordEnemy(node.id, enemy);
  }
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function clampInt(value, min, max) {
  const n = Math.round(value);
  return clamp(n, min, max);
}

function normalizeHeading(heading) {
  const len = Math.hypot(heading.x, heading.z) || 1;
  return { x: heading.x / len, z: heading.z / len };
}

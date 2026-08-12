import { randRange } from "./random.js";
import { NODE_TYPES } from "./etg-core.js";
import { computeCanonicalRoute } from "./etg-utils.js";
import { buildCandidatePool } from "./component-sampler.js";
import { checkComponentHardConstraints } from "./component-rules.js";
import { scoreCandidate, selectCandidateOrder } from "./component-scorer.js";

const PLATFORM_SIZE = { x: 3, y: 1, z: 3 };
const DEFAULT_EDGE_LENGTH = 30;
const LOCK_GATE_SPAN = 18;
const LOCK_CORRIDOR_WIDTH = 4.2;
const LOCK_GATE_HEIGHT = 7.0;
const ENEMY_CLEARANCE_Y = 1.2;

/**
 * HDPCG incremental generator:
 * - Expand one edge at a time (Frontier)
 * - Sample a direction per outgoing edge to spatially separate branches
 * - Place a walkable connector (edge.length) then place the target node chunk
 * - Check tentative placements through an optional validation hook before commit
 */
export function generateLevelIncremental(etg, config = {}, rng, hooks = {}) {
  const level = {
    meta: {
      seed: config.seed,
      config: { ...config },
      etg_version: 2,
      generator_mode:
        String(config.generatorMode || config.generator_mode || "").trim() === "constraint_based"
          ? "constraint_based"
          : "hdpcg_incremental",
      component_generation: {
        version: "di-hdpcg-v1",
        strategy: String(config.componentStrategy || "diverse").trim() || "diverse",
        family_usage: {},
        selection_stats: {
          candidate_total: 0,
          candidate_accepted: 0,
          rejected_constraints: 0,
          rejected_overlap: 0,
          rejected_validation: 0,
          fallback_uses: 0,
          requeued_canonical: 0,
          key_lock_repairs: 0,
        },
      },
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

  const nodeById = new Map((etg.nodes || []).map((n) => [n.id, n]));
  const edges = (etg.edges || []).filter(Boolean);
  const edgeById = new Map(edges.map((e) => [e.id, e]));
  const neighborsByNode = buildNeighborsByNode(edges);

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

  const startNode =
    (etg.nodes || []).find((n) => nodeHasType(n, NODE_TYPES.START)) ||
    (etg.nodes || [])[0] ||
    { id: "Start", types: [NODE_TYPES.START], intensity: 0.1 };

  const placedNodes = new Map(); // nodeId -> { entry, exit, outgoingEdgeCount }
  const builtEdgeIds = new Set();
  const builtUndirected = new Map(); // "A|B" -> edgeId that created geometry

  const nodeBounds = new Map(); // node_id -> AABB

  // Place Start chunk at origin.
  {
    const chunk = buildNodeChunk(startNode, { x: 0, y: 0, z: 0 }, { x: 1, z: 0 }, rng, helpers);
    level.anchors[startNode.id] = { entry: chunk.entry, exit: chunk.exit, heading: { x: 1, z: 0 } };
    placedNodes.set(startNode.id, {
      entry: chunk.entry,
      exit: chunk.exit,
      outgoingEdgeCount: 0,
      sectorShift: Math.floor(rng() * 1000000) % 9973, // Seed-controlled per-node sector offset.
      sectorBaseAngle: rng() * Math.PI * 2,
      usedSectors: new Set(),
      portsByNeighbor: null,
      lockForward: null,
    });
    level.start = { ...chunk.entry };
    if (nodeHasType(startNode, NODE_TYPES.GOAL)) level.goal = { ...chunk.exit };
    // Update bounds for start.
    const startPlatforms = level.platforms.filter((p) => p.node_id === startNode.id);
    const boundsBy = collectBoundsByNode(startPlatforms);
    if (boundsBy[startNode.id]) nodeBounds.set(startNode.id, boundsBy[startNode.id]);
  }

  // Frontier holds oriented work items (from placed -> other end).
  const frontier = [];
  const frontierKeys = new Set();
  const canonicalEdgeSet = new Set((canonical.ok ? canonical.edges : []).filter(Boolean));

  const pushFrontierForNode = (nodeId) => {
    for (const edge of edges) {
      if (!edge?.id) continue;
      if (builtEdgeIds.has(edge.id)) continue;
      const fromPlaced = placedNodes.has(edge.from);
      const toPlaced = placedNodes.has(edge.to);
      if (fromPlaced && !toPlaced) addFrontier(edge.id, edge.from, edge.to);
      else if (toPlaced && !fromPlaced) addFrontier(edge.id, edge.to, edge.from);
      else if (fromPlaced && toPlaced) addFrontier(edge.id, edge.from, edge.to);
    }
  };

  const addFrontier = (edgeId, fromId, toId, failCount = 0) => {
    const key = `${edgeId}|${fromId}`;
    if (frontierKeys.has(key)) return;
    frontierKeys.add(key);
    frontier.push({ edgeId, fromId, toId, canonical: canonicalEdgeSet.has(edgeId), failCount });
  };

  pushFrontierForNode(startNode.id);

  const maxAttempts = clampInt(config.maxAttempts ?? 28, 5, 80);
  const sectorCount = clampInt(config.sectorCount ?? 8, 4, 32);
  const safetyMargin = typeof config.safetyMargin === "number" ? config.safetyMargin : 1.0;
  const componentStrategy = String(config.componentStrategy || "diverse").trim() || "diverse";
  const useDiverseStrategy = componentStrategy !== "legacy";
  const candidatePoolSize = clampInt(config.candidatePoolSize ?? 12, 1, 48);
  const selectionTopP = clamp(config.selectionTopP ?? 0.70, 0.05, 1);
  const selectionTemperature = clamp(config.selectionTemperature ?? 0.80, 0.05, 4);
  const maxLocalRejects = clampInt(config.maxLocalRejects ?? 24, 1, 120);
  const fallbackEnabled = config.fallbackEnabled !== false;
  const familyBalanceWindow = clampInt(config.familyBalanceWindow ?? 40, 4, 200);
  const maxCanonicalRetries = clampInt(config.maxCanonicalRetries ?? 2, 0, 8);
  const familyUsage = level.meta.component_generation.family_usage;
  const selectionStats = level.meta.component_generation.selection_stats;
  const recentFamilyWindow = [];

  // Main expansion loop.
  let guard = 0;
  const maxSteps = Math.max(30, edges.length * 6);
  while (frontier.length > 0 && guard < maxSteps) {
    guard += 1;

    // Prefer canonical edges to build the backbone first, then randomize.
    let idx = frontier.findIndex((f) => f.canonical);
    if (idx < 0) idx = Math.floor(rng() * frontier.length);
    const work = frontier.splice(idx, 1)[0];
    frontierKeys.delete(`${work.edgeId}|${work.fromId}`);

    const edge = edgeById.get(work.edgeId);
    if (!edge || builtEdgeIds.has(edge.id)) continue;

    // Reuse geometry already created for the undirected pair.
    const undirectedKey = undirectedPairKey(edge.from, edge.to);
    if (builtUndirected.has(undirectedKey)) {
      const existingId = builtUndirected.get(undirectedKey);
      level.mapping.edge[edge.id] = level.mapping.edge[existingId] || {
        from: edge.from,
        to: edge.to,
        entry: { ...(placedNodes.get(work.fromId)?.exit || level.start) },
        exit: { ...(placedNodes.get(work.toId)?.entry || placedNodes.get(work.fromId)?.exit || level.start) },
        constraints: { length: edge.length ?? DEFAULT_EDGE_LENGTH },
      };
      builtEdgeIds.add(edge.id);
      continue;
    }

    const fromAnchor = placedNodes.get(work.fromId);
    if (!fromAnchor) continue;
    const fromExit = resolveExitPort(placedNodes, work.fromId, work.toId) || fromAnchor.exit;
    const toNode = nodeById.get(work.toId);
    if (!toNode) continue;

    const toAlreadyPlaced = placedNodes.has(work.toId) && level.anchors[work.toId];
    const targetEntry = toAlreadyPlaced ? { ...(resolveEntryPort(placedNodes, work.toId, work.fromId) || level.anchors[work.toId].entry) } : null;
    const edgeLength = Math.max(1, Number(edge.length) || DEFAULT_EDGE_LENGTH);

    let candidateOrder = [];
    if (useDiverseStrategy) {
      const rawCandidates = buildCandidatePool({
        edge,
        toNode,
        rng,
        poolSize: candidatePoolSize,
      });
      selectionStats.candidate_total += rawCandidates.length;
      const usageForScore = { ...familyUsage };
      for (const family of recentFamilyWindow) {
        usageForScore[family] = (usageForScore[family] || 0) + 1;
      }
      const scored = [];
      for (const candidate of rawCandidates) {
        const check = checkComponentHardConstraints(candidate, { edge, toNode });
        if (!check.ok) {
          selectionStats.rejected_constraints += 1;
          continue;
        }
        scored.push(
          scoreCandidate(candidate, {
            edgeLength,
            familyUsage: usageForScore,
            weights: {
              alignmentWeight: config.alignmentWeight ?? 0.35,
              playabilityWeight: config.playabilityWeight ?? 0.30,
              noveltyWeight: config.noveltyWeight ?? 0.20,
              shapeWeight: config.shapeWeight ?? 0.15,
              riskWeight: config.riskWeight ?? 0.20,
            },
          })
        );
      }
      candidateOrder = selectCandidateOrder(
        scored,
        {
          selectionTopP,
          selectionTemperature,
        },
        rng
      );
    }

    const attemptPlan = useDiverseStrategy
      ? (() => {
          const plan = candidateOrder.slice(0, maxLocalRejects);
          if (fallbackEnabled) plan.push(null);
          if (plan.length === 0 && fallbackEnabled) plan.push(null);
          return plan;
        })()
      : Array.from({ length: maxAttempts }, () => null);

    let committed = false;
    for (let attempt = 0; attempt < Math.min(maxAttempts, attemptPlan.length); attempt += 1) {
      const diverseCandidate = useDiverseStrategy ? attemptPlan[attempt] : null;
      const snapshot = captureSnapshot(level);

      const chosenSector = toAlreadyPlaced ? null : pickSectorIndex(fromAnchor, sectorCount, attempt);
      let heading = toAlreadyPlaced
        ? normalizeHeading({
            x: targetEntry.x - fromExit.x,
            z: targetEntry.z - fromExit.z,
          })
        : sampleHeadingFromSector(fromAnchor, chosenSector, sectorCount, rng);
      if (!toAlreadyPlaced && nodeHasType(toNode, NODE_TYPES.LOCK)) {
        // Snap Lock nodes to an axis so the gate spans the corridor.
        heading = snapHeadingToAxis(heading);
      }

      // For a new node placement, pick an endpoint consistent with edge.length along heading.
      const desiredEntry = toAlreadyPlaced
        ? targetEntry
        : {
            x: fromExit.x + heading.x * edgeLength,
            y: fromExit.y,
            z: fromExit.z + heading.z * edgeLength,
          };

      // Small spatial jitter to avoid systematic overlaps.
      if (!toAlreadyPlaced) {
        const jitter = diverseCandidate
          ? clamp(Number(diverseCandidate.connector?.lateralAmplitude) || 1.0, 0.2, 4.2)
          : 1.0 + rng() * 1.2;
        const right = perpendicular(heading);
        desiredEntry.x += right.x * randRange(rng, -jitter, jitter);
        desiredEntry.z += right.z * randRange(rng, -jitter, jitter);
      }

      // 1) Place connector (walkable, no jump required).
      const connector = buildEdgeConnector(edge, fromExit, desiredEntry, rng, helpers, diverseCandidate?.connector || null);
      level.mapping.edge[edge.id] = {
        from: edge.from,
        to: edge.to,
        entry: connector.entry,
        exit: connector.exit,
        constraints: {
          length: edgeLength,
          connector_family: diverseCandidate?.connectorFamily || "legacy_linear",
          node_family: diverseCandidate?.nodeFamily || "legacy_default",
        },
      };

      // 2) Place node chunk if needed.
      let chunk = null;
      if (!toAlreadyPlaced) {
        if (nodeHasType(toNode, NODE_TYPES.LOCK)) {
          const neighbors = Array.from(neighborsByNode.get(toNode.id) || []);
          const otherNeighbor = neighbors.find((id) => id && id !== work.fromId) || null;
          const lockChunk = buildLockGateChunk(toNode, desiredEntry, heading, rng, helpers, diverseCandidate?.node || null);
          chunk = lockChunk;
          const portsByNeighbor = {};
          portsByNeighbor[work.fromId] = { ...lockChunk.entry };
          if (otherNeighbor) portsByNeighbor[otherNeighbor] = { ...lockChunk.exit };
          level.anchors[toNode.id] = {
            entry: { ...lockChunk.entry },
            exit: { ...lockChunk.exit },
            heading: { ...lockChunk.heading },
            portsByNeighbor,
            gate: { ...lockChunk.gate },
          };
        } else {
          chunk = buildNodeChunk(toNode, desiredEntry, heading, rng, helpers, diverseCandidate?.node || null);
          level.anchors[toNode.id] = { entry: chunk.entry, exit: chunk.exit, heading: { ...heading } };
        }
      }

      // 3) Check spatial separation with an AABB safety margin.
      const connectorNodeId = `edge:${edge.id}`;
      const connectorTouchNodes = new Set([work.fromId, work.toId].filter(Boolean));
      const overlapEval = evaluateSafetyMargin(
        level,
        snapshot,
        nodeBounds,
        connectorNodeId,
        connectorTouchNodes,
        safetyMargin
      );
      if (!overlapEval.ok) {
        if (useDiverseStrategy) selectionStats.rejected_overlap += 1;
        rollbackToSnapshot(level, snapshot);
        continue;
      }

      // 4) Run the optional local topology validation hook.
      if (typeof hooks.validatePlacement === "function") {
        const result = hooks.validatePlacement({
          level,
          etg,
          edge,
          fromId: work.fromId,
          toId: work.toId,
          snapshot,
          boundsDelta: overlapEval.deltaBounds,
          placedNodes,
        });
        if (!result?.ok) {
          if (useDiverseStrategy) selectionStats.rejected_validation += 1;
          rollbackToSnapshot(level, snapshot);
          continue;
        }
      }

      // Commit bounds + placed node.
      for (const [nodeId, bounds] of Object.entries(overlapEval.proposedBounds)) {
        nodeBounds.set(nodeId, bounds);
      }
      builtEdgeIds.add(edge.id);
      builtUndirected.set(undirectedKey, edge.id);
      fromAnchor.outgoingEdgeCount += 1;
      if (chosenSector !== null && chosenSector !== undefined) {
        fromAnchor.usedSectors?.add(chosenSector);
      }
      if (useDiverseStrategy) {
        if (diverseCandidate?.connectorFamily) {
          familyUsage[diverseCandidate.connectorFamily] = (familyUsage[diverseCandidate.connectorFamily] || 0) + 1;
          recentFamilyWindow.push(diverseCandidate.connectorFamily);
        }
        if (diverseCandidate?.nodeFamily) {
          familyUsage[diverseCandidate.nodeFamily] = (familyUsage[diverseCandidate.nodeFamily] || 0) + 1;
          recentFamilyWindow.push(diverseCandidate.nodeFamily);
        }
        while (recentFamilyWindow.length > familyBalanceWindow) recentFamilyWindow.shift();
        if (diverseCandidate) selectionStats.candidate_accepted += 1;
        else selectionStats.fallback_uses += 1;
      }

      if (!toAlreadyPlaced) {
        const isLock = nodeHasType(toNode, NODE_TYPES.LOCK);
        placedNodes.set(toNode.id, {
          entry: chunk.entry,
          exit: chunk.exit,
          outgoingEdgeCount: 0,
          sectorShift: Math.floor(rng() * 1000000) % 9967,
          sectorBaseAngle: rng() * Math.PI * 2,
          usedSectors: new Set(),
          portsByNeighbor: isLock ? { ...(level.anchors[toNode.id]?.portsByNeighbor || {}) } : null,
          lockForward: isLock ? { ...(level.anchors[toNode.id]?.heading || { x: 1, z: 0 }) } : null,
        });
        if (nodeHasType(toNode, NODE_TYPES.GOAL)) level.goal = { ...chunk.exit };
        pushFrontierForNode(toNode.id);
      }

      committed = true;
      break;
    }

    if (!committed) {
      if ((work.failCount || 0) < maxCanonicalRetries && work.canonical) {
        const key = `${work.edgeId}|${work.fromId}`;
        if (!frontierKeys.has(key)) {
          frontierKeys.add(key);
          frontier.push({
            ...work,
            canonical: false,
            failCount: (work.failCount || 0) + 1,
          });
          if (useDiverseStrategy) selectionStats.requeued_canonical += 1;
        }
      }
      continue;
    }
  }

  ensureKeyLockConsistency(level, helpers, rng);

  // Ensure a goal marker is present.
  if (!level.goal) {
    const last = placedNodes.get(startNode.id);
    level.goal = last ? { x: last.exit.x + 12, y: last.exit.y, z: last.exit.z } : { x: 12, y: 0, z: 0 };
  }

  if (useDiverseStrategy) {
    const processedEdges = Math.max(1, builtEdgeIds.size);
    selectionStats.processed_edges = builtEdgeIds.size;
    selectionStats.accept_rate = selectionStats.candidate_total > 0
      ? Number((selectionStats.candidate_accepted / selectionStats.candidate_total).toFixed(4))
      : 0;
    selectionStats.avg_candidates_per_edge = Number((selectionStats.candidate_total / processedEdges).toFixed(3));
  }

  return level;
}

function nodeHasType(node, type) {
  const types = Array.isArray(node?.types) ? node.types : node?.type ? [node.type] : [];
  return types.includes(type);
}

function undirectedPairKey(a, b) {
  const x = String(a);
  const y = String(b);
  return x < y ? `${x}|${y}` : `${y}|${x}`;
}

function normalizeHeading(heading) {
  const len = Math.hypot(heading.x, heading.z) || 1;
  return { x: heading.x / len, z: heading.z / len };
}

function perpendicular(heading) {
  return { x: -heading.z, z: heading.x };
}

function pickSectorIndex(nodeState, sectorCount, attempt) {
  const count = Math.max(1, sectorCount);
  const shift = Math.abs(Math.round(nodeState?.sectorShift ?? 0)) % count;
  const preferred = (shift + Math.abs(Math.round(nodeState?.outgoingEdgeCount ?? 0))) % count;
  const start = (preferred + Math.abs(Math.round(attempt))) % count;
  const used = nodeState?.usedSectors;
  if (used && used.size < count) {
    for (let k = 0; k < count; k += 1) {
      const idx = (start + k) % count;
      if (!used.has(idx)) return idx;
    }
  }
  return start;
}

function sampleHeadingFromSector(nodeState, sectorIndex, sectorCount, rng) {
  const idx = Math.abs(Math.round(sectorIndex)) % Math.max(1, sectorCount);
  const baseAngle = ((idx / Math.max(1, sectorCount)) * Math.PI * 2) + (nodeState?.sectorBaseAngle ?? 0);
  const jitter = randRange(rng, -0.35, 0.35) * (Math.PI * 2 / Math.max(1, sectorCount));
  const angle = baseAngle + jitter;
  return normalizeHeading({ x: Math.cos(angle), z: Math.sin(angle) });
}

function snapHeadingToAxis(heading) {
  const h = normalizeHeading(heading);
  if (Math.abs(h.x) >= Math.abs(h.z)) {
    return { x: h.x >= 0 ? 1 : -1, z: 0 };
  }
  return { x: 0, z: h.z >= 0 ? 1 : -1 };
}

function buildNeighborsByNode(edges) {
  const map = new Map();
  const add = (a, b) => {
    if (!a || !b || a === b) return;
    if (!map.has(a)) map.set(a, new Set());
    map.get(a).add(b);
  };
  for (const e of edges || []) {
    if (!e?.from || !e?.to) continue;
    add(e.from, e.to);
    add(e.to, e.from);
  }
  return map;
}

function resolveEntryPort(placedNodes, nodeId, fromNeighborId) {
  const state = placedNodes.get(nodeId);
  const ports = state?.portsByNeighbor;
  if (ports && fromNeighborId && ports[fromNeighborId]) return ports[fromNeighborId];
  return null;
}

function resolveExitPort(placedNodes, nodeId, toNeighborId) {
  const state = placedNodes.get(nodeId);
  const ports = state?.portsByNeighbor;
  if (ports && toNeighborId && ports[toNeighborId]) return ports[toNeighborId];
  return null;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function clampInt(value, min, max) {
  const n = Math.round(Number(value) || min);
  return clamp(n, min, max);
}

function captureSnapshot(level) {
  return {
    platformsLen: level.platforms.length,
    enemiesLen: level.enemies.length,
    keysLen: level.keys.length,
    locksLen: level.locks.length,
    checkpointsLen: level.checkpoints.length,
    edgeIds: new Set(Object.keys(level.mapping.edge)),
    anchorIds: new Set(Object.keys(level.anchors)),
  };
}

function rollbackToSnapshot(level, snapshot) {
  rollbackEntities(level, "platforms", snapshot.platformsLen, "platforms");
  rollbackEntities(level, "enemies", snapshot.enemiesLen, "enemies");
  rollbackEntities(level, "keys", snapshot.keysLen, "keys");
  rollbackEntities(level, "locks", snapshot.locksLen, "locks");
  rollbackEntities(level, "checkpoints", snapshot.checkpointsLen, "checkpoints");

  for (const edgeId of Object.keys(level.mapping.edge)) {
    if (!snapshot.edgeIds.has(edgeId)) delete level.mapping.edge[edgeId];
  }
  for (const anchorId of Object.keys(level.anchors)) {
    if (!snapshot.anchorIds.has(anchorId)) delete level.anchors[anchorId];
  }
}

function rollbackEntities(level, listKey, keepLength, mapKey) {
  const removed = level[listKey].splice(keepLength);
  for (const entity of removed) {
    if (!entity?.node_id) continue;
    const mapping = level.mapping.node[entity.node_id];
    if (!mapping || !Array.isArray(mapping[mapKey])) continue;
    mapping[mapKey] = mapping[mapKey].filter((id) => id !== entity.id);
    if (
      mapping.platforms.length === 0 &&
      mapping.enemies.length === 0 &&
      mapping.keys.length === 0 &&
      mapping.locks.length === 0 &&
      mapping.checkpoints.length === 0
    ) {
      delete level.mapping.node[entity.node_id];
    }
  }
}

function collectBoundsByNode(platforms) {
  const boundsByNode = {};
  for (const platform of platforms) {
    if (!platform?.node_id) continue;
    const nodeId = platform.node_id;
    const bounds = boundsByNode[nodeId] || emptyBounds();
    const halfX = platform.size.x * 0.5;
    const halfY = platform.size.y * 0.5;
    const halfZ = platform.size.z * 0.5;
    bounds.min.x = Math.min(bounds.min.x, platform.pos.x - halfX);
    bounds.max.x = Math.max(bounds.max.x, platform.pos.x + halfX);
    bounds.min.y = Math.min(bounds.min.y, platform.pos.y - halfY);
    bounds.max.y = Math.max(bounds.max.y, platform.pos.y + halfY);
    bounds.min.z = Math.min(bounds.min.z, platform.pos.z - halfZ);
    bounds.max.z = Math.max(bounds.max.z, platform.pos.z + halfZ);
    boundsByNode[nodeId] = bounds;
  }
  return boundsByNode;
}

function emptyBounds() {
  return {
    min: { x: Infinity, y: Infinity, z: Infinity },
    max: { x: -Infinity, y: -Infinity, z: -Infinity },
  };
}

function mergeBounds(a, b) {
  if (!a) return b;
  if (!b) return a;
  return {
    min: {
      x: Math.min(a.min.x, b.min.x),
      y: Math.min(a.min.y, b.min.y),
      z: Math.min(a.min.z, b.min.z),
    },
    max: {
      x: Math.max(a.max.x, b.max.x),
      y: Math.max(a.max.y, b.max.y),
      z: Math.max(a.max.z, b.max.z),
    },
  };
}

function aabbDistance(a, b) {
  const dx = Math.max(0, Math.max(b.min.x - a.max.x, a.min.x - b.max.x));
  const dy = Math.max(0, Math.max(b.min.y - a.max.y, a.min.y - b.max.y));
  const dz = Math.max(0, Math.max(b.min.z - a.max.z, a.min.z - b.max.z));
  return Math.hypot(dx, dy, dz);
}

function evaluateSafetyMargin(level, snapshot, nodeBounds, connectorNodeId, connectorTouchNodes, safetyMargin) {
  const newPlatforms = level.platforms.slice(snapshot.platformsLen);
  const newBoundsByNode = collectBoundsByNode(newPlatforms);
  const proposedBounds = {};
  for (const [nodeId, bounds] of Object.entries(newBoundsByNode)) {
    const existing = nodeBounds.get(nodeId);
    proposedBounds[nodeId] = existing ? mergeBounds(existing, bounds) : bounds;
  }

  // Compare proposed bounds against existing bounds (and other proposed).
  const proposedEntries = Object.entries(proposedBounds);
  for (const [nodeId, bounds] of proposedEntries) {
    for (const [otherId, otherBounds] of nodeBounds.entries()) {
      if (otherId === nodeId) continue;
      if (
        (nodeId === connectorNodeId && connectorTouchNodes.has(otherId)) ||
        (otherId === connectorNodeId && connectorTouchNodes.has(nodeId))
      ) {
        continue;
      }
      const compare = proposedBounds[otherId] || otherBounds;
      if (aabbDistance(bounds, compare) < safetyMargin) return { ok: false };
    }
  }
  for (let i = 0; i < proposedEntries.length; i += 1) {
    const [nodeId, bounds] = proposedEntries[i];
    for (let j = i + 1; j < proposedEntries.length; j += 1) {
      const [otherId, otherBounds] = proposedEntries[j];
      if (nodeId === otherId) continue;
      if (
        (nodeId === connectorNodeId && connectorTouchNodes.has(otherId)) ||
        (otherId === connectorNodeId && connectorTouchNodes.has(nodeId))
      ) {
        continue;
      }
      if (aabbDistance(bounds, otherBounds) < safetyMargin) return { ok: false };
    }
  }

  return { ok: true, proposedBounds, deltaBounds: newBoundsByNode };
}

function buildEdgeConnector(edge, fromPos, toPos, rng, helpers, style = null) {
  const edgeKey = `edge:${edge.id}`;
  const distance = Math.hypot(toPos.x - fromPos.x, toPos.z - fromPos.z);
  const step = 6.0;
  const steps = clampInt(Math.round(distance / step), 1, 48);
  const family = style?.family || "linear_bridge";
  const baseSize = {
    x: 6.8 + clampNumber(style?.lateralAmplitude ?? 1.0, 0.2, 3.2) * 0.9,
    y: 0.8,
    z: 5.8 + clampNumber(style?.lateralAmplitude ?? 1.0, 0.2, 3.2) * 0.6,
  };
  let entry = null;
  let exit = null;
  const axis = normalizeHeading({ x: toPos.x - fromPos.x, z: toPos.z - fromPos.z });
  const right = perpendicular(axis);
  const zigPeriod = clampNumber(style?.zigzagPeriod ?? 4.5, 1.5, 9);
  const latAmp = clampNumber(style?.lateralAmplitude ?? 1.0, 0, 3.5);
  const vertAmp = clampNumber(style?.verticalAmplitude ?? 0.8, 0, 3.0);
  const stairStep = clampNumber(style?.stairStep ?? 0.6, 0.2, 1.5);
  const movingRate = clampNumber(style?.movingRate ?? 0.35, 0, 1);
  const hazardDensity = clampNumber(style?.hazardDensity ?? 0.25, 0, 1);
  for (let i = 1; i <= steps; i += 1) {
    const t = i / (steps + 1);
    const local = t * distance;
    const wave = Math.sin((local / zigPeriod) * Math.PI * 2);
    let lateral = 0;
    let vertical = 0;
    if (family === "zigzag_bridge") lateral = wave * latAmp;
    if (family === "arc_bridge") vertical = Math.sin(t * Math.PI) * vertAmp;
    if (family === "stair_bridge") vertical = Math.floor(t * (steps + 1) * 0.5) * stairStep * 0.45;
    if (family === "vertical_lift_bridge") vertical = (t < 0.5 ? t : 1 - t) * vertAmp * 2;
    if (family === "hazard_chicane_bridge") lateral = wave * latAmp * 0.65;
    if (family === "split_merge_bridge") lateral = Math.sin(t * Math.PI) * latAmp * 0.8;
    const pos = {
      x: fromPos.x + (toPos.x - fromPos.x) * t + right.x * lateral,
      y: fromPos.y + (toPos.y - fromPos.y) * t + vertical,
      z: fromPos.z + (toPos.z - fromPos.z) * t + right.z * lateral,
    };
    const platformOpts = { node_id: edgeKey, tags: ["connector", family] };
    if (
      family === "moving_shuttle_bridge" &&
      steps > 2 &&
      i > 1 &&
      i < steps &&
      rng() < movingRate
    ) {
      platformOpts.kind = "moving";
      platformOpts.motion = {
        axis: Math.abs(axis.x) >= Math.abs(axis.z) ? "x" : "z",
        amplitude: clampNumber(1.2 + latAmp * 0.4, 0.8, 2.6),
        period: clampNumber(2.6 + rng() * 2.2, 1.4, 5.5),
        phase: rng() * Math.PI * 2,
      };
    }
    const platform = helpers.addPlatform(pos, baseSize, platformOpts);
    helpers.recordPlatform(edgeKey, platform);
    if (
      family === "hazard_chicane_bridge" &&
      i > 1 &&
      i < steps &&
      rng() < hazardDensity * 0.4
    ) {
      const patrol = {
        from: { x: pos.x - axis.x * 1.8, y: pos.y + ENEMY_CLEARANCE_Y, z: pos.z - axis.z * 1.8 },
        to: { x: pos.x + axis.x * 1.8, y: pos.y + ENEMY_CLEARANCE_Y, z: pos.z + axis.z * 1.8 },
      };
      const enemy = helpers.addEnemy({ x: pos.x, y: pos.y + ENEMY_CLEARANCE_Y, z: pos.z }, patrol, {
        node_id: edgeKey,
        speed: 1.0 + rng() * 1.2,
      });
      helpers.recordEnemy(edgeKey, enemy);
    }
    if (!entry) entry = { ...pos };
    exit = { ...pos };
  }
  if (!entry) entry = { ...fromPos };
  if (!exit) exit = { ...toPos };
  return { entry, exit };
}

function buildNodeChunk(node, entryPos, heading, rng, helpers, style = null) {
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
  const family = style?.family || null;

  let count = 2 + Math.round(intensity * 4);
  let gap = 2.2 + intensity * 1.8;
  let verticalStep = 0;
  let verticalVariance = 0.0;
  let size = { ...PLATFORM_SIZE };
  let tags = [groundType];

  const isStructural = groundType === NODE_TYPES.START || groundType === NODE_TYPES.GOAL;
  if (isStructural || groundType === NODE_TYPES.NONE) {
    count = 1;
    gap = 0;
    verticalStep = 0;
    verticalVariance = 0;
    size = { x: 9, y: 1, z: 7 };
    tags = [groundType, "walkable"];
  } else if (groundType === NODE_TYPES.PLATFORM) {
    verticalVariance = 0.05 + 0.15 * intensity;
  } else if (groundType === NODE_TYPES.JUMP) {
    verticalStep = Math.min(helpers.maxVertical, 0.7 + intensity * 2.0);
    verticalVariance = 0.05;
  } else if (groundType === NODE_TYPES.DROP) {
    verticalStep = -Math.min(helpers.maxVertical, 0.7 + intensity * 2.0);
    verticalVariance = 0.05;
  }

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

  if (family === "start_plaza" || family === "goal_platform") {
    count = 1;
    gap = 0;
    size = { x: 11, y: 1, z: 9 };
  } else if (family === "start_ramp") {
    count = 3;
    gap = 0.6;
    size = { x: 6.5, y: 1, z: 6.8 };
    verticalStep = 0.5;
  } else if (family === "goal_tower") {
    count = 3;
    gap = 0.9;
    size = { x: 6.5, y: 1, z: 6.5 };
    verticalStep = 0.8;
  } else if (family === "serpentine_room") {
    count = clampInt(count + 1, 2, 10);
    gap = clamp(gap * 0.6, 0.4, 3.0);
    verticalVariance = Math.max(verticalVariance, 0.08);
  } else if (family === "dual_lane_room") {
    count = clampInt(count + 1, 2, 10);
    gap = clamp(gap * 0.7, 0.4, 3.2);
    size = { x: size.x * 0.9, y: size.y, z: size.z * 0.9 };
  } else if (family === "arena_room") {
    count = clampInt(count, 1, 10);
    gap = clamp(gap * 0.4, 0.2, 2.2);
    size = { x: 8.8, y: 1, z: 8.8 };
  } else if (family === "gap_chain") {
    count = clampInt(count + 1, 3, 10);
    gap = clamp(gap * 1.35, 1.8, 4.6);
    size = { x: 3.4, y: 1, z: 3.2 };
    verticalVariance = Math.max(verticalVariance, 0.1);
  } else if (family === "offset_islands") {
    count = clampInt(count + 1, 3, 10);
    gap = clamp(gap * 1.2, 1.6, 4.2);
    size = { x: 3.8, y: 1, z: 3.6 };
    verticalVariance = Math.max(verticalVariance, 0.12);
  } else if (family === "ascending_jumps") {
    count = clampInt(count, 3, 10);
    gap = clamp(gap * 1.05, 1.2, 4.2);
    verticalStep = Math.max(verticalStep, 0.65);
  } else if (family === "drop_well") {
    count = clampInt(count, 3, 10);
    gap = clamp(gap * 0.9, 1.0, 3.4);
    verticalStep = Math.min(verticalStep || -0.65, -0.65);
  } else if (family === "stepped_drop") {
    count = clampInt(count, 3, 10);
    gap = clamp(gap * 0.8, 0.9, 3.2);
    verticalStep = Math.min(verticalStep || -0.5, -0.5);
  } else if (family === "spiral_drop") {
    count = clampInt(count + 1, 3, 10);
    gap = clamp(gap * 0.85, 1.0, 3.3);
    verticalStep = Math.min(verticalStep || -0.45, -0.45);
    verticalVariance = Math.max(verticalVariance, 0.08);
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

    let advanceX = forward.x * step;
    let advanceZ = forward.z * step;
    if (family === "dual_lane_room" || family === "offset_islands" || family === "spiral_drop") {
      const sway = ((i % 2 === 0 ? 1 : -1) * (style?.scaleZ || 1)) * 2.0;
      advanceX += -forward.z * sway * 0.2;
      advanceZ += forward.x * sway * 0.2;
    }
    x += advanceX;
    z += advanceZ;
    if (verticalStep !== 0) {
      y += verticalStep;
    } else if (verticalVariance > 0) {
      y += randRange(rng, -verticalVariance, verticalVariance);
    }
  }

  if (has(NODE_TYPES.ENEMY)) {
    const enemyCountBoost = family === "cross_patrol" ? 2 : family === "choke_guard" ? 1 : 0;
    const enemyCount = clampInt(1 + Math.floor(intensity * 3.2) + enemyCountBoost, 1, 6);
    const patrolLength = 3.5 + intensity * 6.0;
    const speed = 1.0 + intensity * 2.5 + rng() * 0.4 + (family === "choke_guard" ? 0.4 : 0);
    const height = ENEMY_CLEARANCE_Y + intensity * 0.35;
    applyEnemiesV2(node, { count: enemyCount, patrol_length: patrolLength, speed, height }, entry, exit, helpers, rng);
  }

  if (has(NODE_TYPES.KEY)) {
    const keyId = node.key_id || "K1";
    const keyPos =
      family === "risk_key_room"
        ? { x: exit.x, y: exit.y + 1.1, z: exit.z }
        : { x: entry.x, y: entry.y + 1.0, z: entry.z };
    const key = helpers.addKey(keyPos, keyId, { node_id: node.id });
    helpers.recordKey(node.id, key);
    if (family === "timed_key_bridge" && exitPlatformId) {
      const platform = helpers.platformById.get(exitPlatformId);
      if (platform) {
        platform.kind = "moving";
        platform.motion = {
          axis: "z",
          amplitude: 1.8,
          period: 3.2 + rng() * 1.4,
          phase: rng() * Math.PI * 2,
        };
      }
    }
  }
  if (has(NODE_TYPES.LOCK)) {
    // The incremental generator represents Lock as a dedicated gate corridor.
  }

  return { entry, exit };
}

function applyEnemiesV2(node, spec, entry, exit, helpers, rng) {
  if (!spec) return;
  const count = Math.max(1, spec.count ?? 1);
  const patrolLength = spec.patrol_length ?? 4.5;
  const height = spec.height ?? ENEMY_CLEARANCE_Y;
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

function ensureKeyLockConsistency(level, helpers, rng) {
  const keyIds = new Set((level.keys || []).map((item) => item?.key_id).filter(Boolean));
  let repairs = 0;
  for (const lock of level.locks || []) {
    const keyId = lock?.key_id;
    if (!keyId || keyIds.has(keyId)) continue;
    const anchor = level.anchors?.[lock.node_id] || null;
    const base = anchor?.entry || level.start || lock.pos || { x: 0, y: 0, z: 0 };
    const keyPos = {
      x: base.x + randRange(rng, 1.2, 2.6),
      y: base.y + ENEMY_CLEARANCE_Y,
      z: base.z + randRange(rng, -1.2, 1.2),
    };
    const nodeId = lock.node_id || "__auto_key_repair";
    const key = helpers.addKey(keyPos, keyId, { node_id: nodeId });
    helpers.recordKey(nodeId, key);
    keyIds.add(keyId);
    repairs += 1;
  }
  if (repairs > 0) {
    const stats = level.meta?.component_generation?.selection_stats;
    if (stats) stats.key_lock_repairs = (stats.key_lock_repairs || 0) + repairs;
  }
}

function computeLockPlacement(segment, heading, data, platformById) {
  const forward = normalizeHeading(heading);
  const absX = Math.abs(forward.x);
  const absZ = Math.abs(forward.z);
  const exitPlatform = segment.exitPlatformId ? platformById.get(segment.exitPlatformId) : null;
  const platformSize = exitPlatform?.size || PLATFORM_SIZE;
  const gateSize = data.gate_size;

  let lockSize;
  if (gateSize && typeof gateSize === "object") {
    lockSize = {
      x: gateSize.x ?? 2,
      y: gateSize.y ?? 3,
      z: gateSize.z ?? 0.6,
    };
  } else {
    const thickness = 0.8;
    const margin = 1.2;
    const widthX = platformSize.x + margin;
    const widthZ = platformSize.z + margin;
    lockSize = absX >= absZ
      ? { x: thickness, y: 3, z: widthZ }
      : { x: widthX, y: 3, z: thickness };
  }

  const forwardSpan = absX >= absZ ? platformSize.x : platformSize.z;
  const lockDepth = absX >= absZ ? lockSize.x : lockSize.z;
  const offset = forwardSpan * 0.5 + lockDepth * 0.5;
  const topY = segment.exit.y + platformSize.y * 0.5;
  const lockPos = {
    x: segment.exit.x + forward.x * offset,
    y: topY + lockSize.y * 0.5,
    z: segment.exit.z + forward.z * offset,
  };

  return { lockPos, lockSize };
}

function buildLockGateChunk(node, entryPos, heading, rng, helpers, style = null) {
  const forward = snapHeadingToAxis(heading);
  const span = clampInt(node?.gate_span ?? LOCK_GATE_SPAN, 10, 60);
  const width = clampNumber(node?.gate_width ?? LOCK_CORRIDOR_WIDTH, 2.4, 12);
  const height = clampNumber(node?.gate_height ?? LOCK_GATE_HEIGHT, 3.5, 18);
  const family = style?.family || "center_gate";

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
  const sideOffset = family === "offset_gate" ? width * 0.22 : 0;
  const side = perpendicular(forward);
  const lockPos = {
    x: mid.x + side.x * sideOffset,
    y: topY + lockSize.y * 0.5,
    z: mid.z + side.z * sideOffset,
  };
  const lock = helpers.addLock(lockPos, lockId, requires, { node_id: node.id, size: lockSize });
  helpers.recordLock(node.id, lock);

  if (family === "double_gate_hall") {
    const guardPos = {
      x: lockPos.x + forward.x * 2.4,
      y: lockPos.y,
      z: lockPos.z + forward.z * 2.4,
    };
    const guard = helpers.addEnemy(
      { x: guardPos.x, y: guardPos.y - lockSize.y * 0.5 + 1.0, z: guardPos.z },
      {
        from: { x: guardPos.x - side.x * 2.5, y: guardPos.y - lockSize.y * 0.5 + 1.0, z: guardPos.z - side.z * 2.5 },
        to: { x: guardPos.x + side.x * 2.5, y: guardPos.y - lockSize.y * 0.5 + 1.0, z: guardPos.z + side.z * 2.5 },
      },
      { node_id: node.id, speed: 1.25 + rng() * 0.4 }
    );
    helpers.recordEnemy(node.id, guard);
  }

  return {
    entry: { ...entryPos },
    exit,
    heading: forward,
    gate: { pos: lockPos, size: lockSize, requires_key_id: requires, lock_id: lockId },
  };
}

function clampNumber(value, min, max) {
  const n = Number(value);
  if (!Number.isFinite(n)) return min;
  return Math.min(max, Math.max(min, n));
}

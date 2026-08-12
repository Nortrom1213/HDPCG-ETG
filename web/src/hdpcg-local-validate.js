import { buildHDPCGModel } from "./hdpcg-grid.js";

/**
 * Local topology validation for incremental expansion.
 * It checks reachability, gated progression, and forbidden markers within a local box.
 */
export function validateLocalTopology(options) {
  const level = options?.level;
  const etg = options?.etg;
  const fromId = options?.fromId;
  const toId = options?.toId;
  const boundsDelta = options?.boundsDelta || null;

  const cellSize = options?.cellSize ?? 1;
  const timeStep = options?.timeStep ?? 1;
  const modelPadding = options?.modelPadding ?? 2;
  const localPaddingCells = clampInt(options?.localPaddingCells ?? 3, 0, 18);

  const maxTime = clampInt(options?.maxTime ?? 160, 30, 500);
  const maxStates = clampInt(options?.maxStates ?? 120000, 10000, 450000);
  const maxQueue = clampInt(options?.maxQueue ?? 90000, 10000, 350000);
  const maxJumpOffsets = clampInt(options?.maxJumpOffsets ?? 900, 200, 6000);
  const toleranceRadiusCells = clampInt(options?.toleranceRadiusCells ?? options?.toleranceRadius ?? 2, 0, 12);
  const allowSiblingTolerance = options?.allowSiblingTolerance ?? true;

  if (!level || !fromId || !toId) return { ok: true, warnings: ["validator_skipped_missing_args"] };
  const fromAnchor = level.anchors?.[fromId];
  const toAnchor = level.anchors?.[toId];
  if (!fromAnchor || !toAnchor) return { ok: false, reason: "missing_anchors" };

  let unionBounds = unionBoundsFromDelta(boundsDelta);
  if (!unionBounds) return { ok: true };
  // Include endpoint-adjacent connector cells in the local box.
  unionBounds = mergeBounds(unionBounds, pointBounds(fromAnchor.entry));
  unionBounds = mergeBounds(unionBounds, pointBounds(fromAnchor.exit));
  unionBounds = mergeBounds(unionBounds, pointBounds(toAnchor.entry));
  unionBounds = mergeBounds(unionBounds, pointBounds(toAnchor.exit));

  const localBox = boundsToCellBox(unionBounds, cellSize, localPaddingCells);
  if (!localBox) return { ok: true };

  const model = buildHDPCGModel(level, { cellSize, timeStep, padding: modelPadding });

  const allowed = new Set([fromId, toId]);
  const siblingToleranceNodeIds =
    policy === "strict_1hop" && allowSiblingTolerance && etg
      ? buildSiblingToleranceSet(etg, fromId, toId)
      : new Set();

  const fromCell = nearestWalkableCellInBox(model, toCellCoord(fromAnchor.exit || fromAnchor.entry, cellSize), 0, 0, localBox);
  const toCell = nearestWalkableCellInBox(model, toCellCoord(toAnchor.entry || toAnchor.exit, cellSize), 0, 0, localBox);
  if (!fromCell || !toCell) return { ok: false, reason: "no_walkable_marker" };

  const forbiddenByCell = new Map(); // cellId -> Set(nodeId)
  const anchors = level.anchors || {};
  for (const [nodeId, anchor] of Object.entries(anchors)) {
    if (!nodeId || !anchor) continue;
    if (allowed.has(nodeId)) continue;
    // Validate ETG node anchors.
    if (etg && Array.isArray(etg.nodes) && !etg.nodes.some((n) => n?.id === nodeId)) continue;

    const cells = [];
    const entry = anchor.entry ? nearestWalkableCellInBox(model, toCellCoord(anchor.entry, cellSize), 0, 0, localBox) : null;
    const exit = anchor.exit ? nearestWalkableCellInBox(model, toCellCoord(anchor.exit, cellSize), 0, 0, localBox) : null;
    if (entry) cells.push(entry);
    if (exit) cells.push(exit);
    for (const cell of cells) {
      const id = cellKey(cell);
      const set = forbiddenByCell.get(id) || new Set();
      set.add(nodeId);
      forbiddenByCell.set(id, set);
    }
  }

  const result = bfsEarlyStopLocal({
    model,
    fromCell,
    toCell,
    localBox,
    forbiddenByCell,
    siblingToleranceNodeIds,
    toleranceRadiusCells,
    maxTime,
    maxStates,
    maxQueue,
    maxJumpOffsets,
    allowJump: options?.allowJump ?? true,
    allowDrop: options?.allowDrop ?? true,
  });

  if (!result.ok) return result;

  // Verify gated and keyed connectivity for each affected Lock.
  const lockGateCheck = validateLockGateIfPresent({ level, etg, fromId, toId, model, localBox, maxTime: clampInt(maxTime, 30, 500) });
  if (!lockGateCheck.ok) return lockGateCheck;
  if (lockGateCheck.warnings?.length) {
    result.warnings = [...(result.warnings || []), ...lockGateCheck.warnings];
  }
  return result;
}

function validateLockGateIfPresent({ level, etg, fromId, toId, model, localBox, maxTime }) {
  const candidates = new Set([fromId, toId].filter(Boolean));
  // Re-check existing lock gates near the new geometry.
  for (const [nodeId, anchor] of Object.entries(level.anchors || {})) {
    if (!anchor?.gate?.pos) continue;
    const cell = toCellCoord(anchor.gate.pos, model.cellSize);
    if (withinBox(cell, localBox)) candidates.add(nodeId);
  }
  for (const nodeId of candidates) {
    if (!isLockNode(etg, nodeId)) continue;
    const anchor = level.anchors?.[nodeId];
    const ports = anchor?.portsByNeighbor;
    if (!ports || typeof ports !== "object") continue;
    const portIds = Object.keys(ports);
    if (portIds.length !== 2) continue;
    const aPos = ports[portIds[0]];
    const bPos = ports[portIds[1]];
    if (!aPos || !bPos) continue;
    const aCell = nearestWalkableCellInBox(model, toCellCoord(aPos, model.cellSize), 0, 0, localBox);
    const bCell = nearestWalkableCellInBox(model, toCellCoord(bPos, model.cellSize), 0, 0, localBox);
    if (!aCell || !bCell) continue;

    const blocked = bfsReachableLocal({
      model,
      fromCell: aCell,
      toCell: bCell,
      localBox,
      maxTime,
      startPhase: 0,
    });
    if (blocked.reached) {
      return { ok: false, reason: "lock_gate_leak_no_key", lockNodeId: nodeId };
    }
    const open = bfsReachableLocal({
      model,
      fromCell: aCell,
      toCell: bCell,
      localBox,
      maxTime,
      startPhase: Math.max(0, (model.phaseCount || 1) - 1),
    });
    if (!open.reached) {
      return { ok: false, reason: "lock_gate_blocks_with_all_keys", lockNodeId: nodeId };
    }

    // Reject keyless bypasses between placed neighbors inside the local region.
    const neighborA = portIds[0];
    const neighborB = portIds[1];
    const aAnchor = level.anchors?.[neighborA];
    const bAnchor = level.anchors?.[neighborB];
    if (aAnchor && bAnchor) {
      const nACell = nearestWalkableCellInBox(model, toCellCoord(aAnchor.exit || aAnchor.entry, model.cellSize), 0, 0, localBox);
      const nBCell = nearestWalkableCellInBox(model, toCellCoord(bAnchor.entry || bAnchor.exit, model.cellSize), 0, 0, localBox);
      if (nACell && nBCell) {
        const bypass = bfsReachableLocal({
          model,
          fromCell: nACell,
          toCell: nBCell,
          localBox,
          maxTime,
          startPhase: 0,
        });
        if (bypass.reached) {
          return { ok: false, reason: "lock_bypassed_between_neighbors_no_key", lockNodeId: nodeId, neighbors: [neighborA, neighborB] };
        }
        const shouldOpen = bfsReachableLocal({
          model,
          fromCell: nACell,
          toCell: nBCell,
          localBox,
          maxTime,
          startPhase: Math.max(0, (model.phaseCount || 1) - 1),
        });
        if (!shouldOpen.reached) {
          return { ok: false, reason: "lock_still_blocks_between_neighbors_with_all_keys", lockNodeId: nodeId, neighbors: [neighborA, neighborB] };
        }
      }
    }
  }
  return { ok: true, warnings: [] };
}

function isLockNode(etg, nodeId) {
  const nodes = Array.isArray(etg?.nodes) ? etg.nodes : [];
  const node = nodes.find((n) => n?.id === nodeId);
  const types = Array.isArray(node?.types) && node.types.length ? node.types : node?.type ? [node.type] : [];
  return types.includes("Lock");
}

function bfsReachableLocal({ model, fromCell, toCell, localBox, maxTime, startPhase }) {
  const goalId = cellKey(toCell);
  const start = { x: fromCell.x, y: fromCell.y, z: fromCell.z, t: 0, phase: clampInt(startPhase ?? 0, 0, Math.max(0, (model.phaseCount || 1) - 1)) };
  const visited = new Set([stateKey(start)]);
  const queue = [start];
  let head = 0;
  let expanded = 0;

  const physics = buildPhysicsProfile(model);
  const groundOffsets = buildGroundOffsets(physics.maxGroundDistance);
  const jumpOffsets = buildJumpOffsets(physics.maxJumpDistance, physics.maxJumpUp, physics.maxJumpDown, 900);

  while (head < queue.length) {
    const state = queue[head++];
    expanded += 1;
    if (cellKey(state) === goalId) return { reached: true, expanded, visited: visited.size };
    const nextStates = collectNeighborsLocal(
      state,
      model,
      physics,
      groundOffsets,
      jumpOffsets,
      true,
      true,
      maxTime,
      localBox,
      model.phaseCount
    );
    for (const next of nextStates) {
      if (!withinBox(next, localBox)) continue;
      const key = stateKey(next);
      if (visited.has(key)) continue;
      visited.add(key);
      queue.push(next);
    }
  }
  return { reached: false, expanded, visited: visited.size };
}

function unionBoundsFromDelta(boundsDelta) {
  if (!boundsDelta) return null;
  const entries = Object.values(boundsDelta).filter(Boolean);
  if (entries.length === 0) return null;
  let out = null;
  for (const b of entries) {
    if (!b?.min || !b?.max) continue;
    if (!out) out = { min: { ...b.min }, max: { ...b.max } };
    else out = mergeBounds(out, b);
  }
  return out;
}

function boundsToCellBox(bounds, cellSize, paddingCells) {
  if (!bounds?.min || !bounds?.max) return null;
  const min = {
    x: Math.floor(bounds.min.x / cellSize) - paddingCells,
    y: Math.floor(bounds.min.y / cellSize) - paddingCells,
    z: Math.floor(bounds.min.z / cellSize) - paddingCells,
  };
  const max = {
    x: Math.ceil(bounds.max.x / cellSize) + paddingCells,
    y: Math.ceil(bounds.max.y / cellSize) + paddingCells,
    z: Math.ceil(bounds.max.z / cellSize) + paddingCells,
  };
  return { min, max };
}

function pointBounds(pos, epsilon = 0.01) {
  if (!pos) return null;
  const x = Number(pos.x);
  const y = Number(pos.y);
  const z = Number(pos.z);
  if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) return null;
  return {
    min: { x: x - epsilon, y: y - epsilon, z: z - epsilon },
    max: { x: x + epsilon, y: y + epsilon, z: z + epsilon },
  };
}

function withinBox(cell, box) {
  return (
    cell.x >= box.min.x && cell.x <= box.max.x &&
    cell.y >= box.min.y && cell.y <= box.max.y &&
    cell.z >= box.min.z && cell.z <= box.max.z
  );
}

function nearestWalkableCellInBox(model, cell, t, phase, box) {
  if (!cell) return null;
  if (!withinBox(cell, box)) return null;
  const snapped = model.findNearestWalkable(cell, t, phase, 6);
  if (!snapped) return null;
  if (!withinBox(snapped, box)) return null;
  return snapped;
}

function bfsEarlyStopLocal(args) {
  const {
    model,
    fromCell,
    toCell,
    localBox,
    forbiddenByCell,
    siblingToleranceNodeIds,
    toleranceRadiusCells,
    maxTime,
    maxStates,
    maxQueue,
    maxJumpOffsets,
    allowJump,
    allowDrop,
  } = args;

  const phaseCount = model.phaseCount;
  const start = { x: fromCell.x, y: fromCell.y, z: fromCell.z, t: 0, phase: 0 };
  const goalId = cellKey(toCell);

  const visited = new Set();
  const queue = [start];
  let head = 0;
  visited.add(stateKey(start));

  const physics = buildPhysicsProfile(model);
  const groundOffsets = buildGroundOffsets(physics.maxGroundDistance);
  const jumpOffsets = allowJump
    ? buildJumpOffsets(physics.maxJumpDistance, physics.maxJumpUp, physics.maxJumpDown, maxJumpOffsets)
    : [];

  let reachedTarget = false;
  let expanded = 0;
  const warnings = [];
  const warnedNodes = new Set();

  while (head < queue.length) {
    const state = queue[head++];
    expanded += 1;
    if (expanded > maxStates || queue.length > maxQueue) {
      return { ok: false, reason: "budget_exceeded", reachedTarget, expanded, visitedCount: visited.size, warnings };
    }

    const id = cellKey(state);

    // Reject a forbidden marker hit.
    if (forbiddenByCell.has(id)) {
      const hit = Array.from(forbiddenByCell.get(id));
      const notTolerated = [];
      const tolerated = [];
      for (const nodeId of hit) {
        const okSibling =
          siblingToleranceNodeIds &&
          siblingToleranceNodeIds.has(nodeId) &&
          manhattanDistance3(state, fromCell) <= toleranceRadiusCells;
        if (okSibling) tolerated.push(nodeId);
        else notTolerated.push(nodeId);
      }
      if (notTolerated.length > 0) {
        return {
          ok: false,
          reason: "forbidden_reached",
          forbiddenNodeIds: notTolerated,
          toleratedNodeIds: tolerated,
          reachedTarget,
          expanded,
          visitedCount: visited.size,
          warnings,
        };
      }
      // Treat sibling contact near the branch origin as a warning.
      for (const nodeId of tolerated) {
        if (warnedNodes.has(nodeId)) continue;
        warnedNodes.add(nodeId);
        warnings.push(`tolerated_sibling_touch:${nodeId}`);
      }
    }

    if (id === goalId) reachedTarget = true;

    const nextStates = collectNeighborsLocal(
      state,
      model,
      physics,
      groundOffsets,
      jumpOffsets,
      allowJump,
      allowDrop,
      maxTime,
      localBox,
      phaseCount
    );
    for (const next of nextStates) {
      if (!withinBox(next, localBox)) continue;
      const key = stateKey(next);
      if (visited.has(key)) continue;
      visited.add(key);
      queue.push(next);
    }
  }

  if (!reachedTarget) {
    return { ok: false, reason: "target_not_reachable", expanded, visitedCount: visited.size, warnings };
  }

  return { ok: true, reachedTarget, expanded, visitedCount: visited.size, warnings };
}

function collectNeighborsLocal(state, model, physics, groundOffsets, jumpOffsets, allowJump, allowDrop, maxTime, box, phaseCount) {
  const nextStates = [];
  const tNext = state.t + 1;
  if (tNext > maxTime) return nextStates;

  const addState = (x, y, z, t, phase) => {
    nextStates.push({ x, y, z, t, phase });
  };

  const addMove = (x, y, z, t, phase) => {
    const cellId = cellKey({ x, y, z });
    const nextPhase = model.applyKeyPhase(phase, cellId);
    addState(x, y, z, t, Math.min(nextPhase, phaseCount - 1));
  };

  if (withinBox(state, box) && model.isWalkableCell(state.x, state.y, state.z, tNext, state.phase)) {
    addMove(state.x, state.y, state.z, tNext, state.phase);
  }

  for (const offset of groundOffsets) {
    const x = state.x + offset.dx;
    const y = state.y;
    const z = state.z + offset.dz;
    const target = { x, y, z };
    if (!withinBox(target, box)) continue;
    if (!model.isWalkableCell(x, y, z, tNext, state.phase)) continue;
    if (!pathClearLocal(state, target, tNext, model, state.phase, box)) continue;
    addMove(x, y, z, tNext, state.phase);
  }

  const surfaceInfo = model.getSurfaceInfo(state.t, cellKey(state));
  if (surfaceInfo && surfaceInfo.moving) {
    const nextCell = rideWithPlatform(state, surfaceInfo, model, tNext);
    if (nextCell && withinBox(nextCell, box)) addMove(nextCell.x, nextCell.y, nextCell.z, tNext, state.phase);
  }

  if (allowJump || allowDrop) {
    for (const offset of jumpOffsets) {
      const jump = allowJump ? tryBallisticMoveLocal(state, offset, model, physics.jumpSpeed, physics, maxTime, box) : null;
      if (jump) {
        nextStates.push(jump);
        continue;
      }
      if (allowDrop) {
        const drop = tryBallisticMoveLocal(state, offset, model, 0, physics, maxTime, box);
        if (drop) nextStates.push(drop);
      }
    }
  }

  return nextStates;
}

function rideWithPlatform(state, surfaceInfo, model, tNext) {
  if (!surfaceInfo.platformId || !surfaceInfo.moving) return null;
  const platform = model.platformById.get(surfaceInfo.platformId);
  const platformPos = model.getPlatformPos(surfaceInfo.platformId, tNext);
  if (!platform || !platformPos) return null;

  const centerX = Math.round(platformPos.x / model.cellSize);
  const centerZ = Math.round(platformPos.z / model.cellSize);
  const targetX = centerX + surfaceInfo.localOffset.x;
  const targetZ = centerZ + surfaceInfo.localOffset.z;
  const topY = platformPos.y + platform.size.y * 0.5;
  const targetY = Math.round(topY / model.cellSize);
  if (!model.isWalkableCell(targetX, targetY, targetZ, tNext, state.phase)) return null;
  return { x: targetX, y: targetY, z: targetZ, t: tNext, phase: state.phase };
}

function tryBallisticMoveLocal(state, offset, model, initialVy, physics, maxTime, box) {
  const landing = {
    x: state.x + offset.dx,
    y: state.y + offset.dy,
    z: state.z + offset.dz,
  };
  if (!withinBox(landing, box)) return null;
  const horiz = Math.hypot(offset.dx, offset.dz);
  if (horiz < 0.01 && offset.dy === 0) return null;

  const startInfo = model.getSurfaceInfo(state.t, cellKey(state));
  if (!startInfo) return null;
  const landingId = cellKey(landing);
  let tLand = state.t + 1;
  if (tLand > maxTime) return null;
  let landingInfo = model.getSurfaceInfo(tLand, landingId);
  if (!landingInfo) return null;

  let dy = landingInfo.surfaceY - startInfo.surfaceY;
  const minTime = horiz / physics.airSpeed;
  let time = chooseTimeForDy(dy, initialVy, physics.gravity, minTime, physics.maxJumpTime);
  if (!time) return null;

  let ticks = Math.max(1, Math.ceil(time / physics.timeStep));
  tLand = state.t + ticks;
  if (tLand > maxTime) return null;
  landingInfo = model.getSurfaceInfo(tLand, landingId);
  if (!landingInfo) return null;
  dy = landingInfo.surfaceY - startInfo.surfaceY;
  time = chooseTimeForDy(dy, initialVy, physics.gravity, minTime, physics.maxJumpTime);
  if (!time) return null;
  ticks = Math.max(1, Math.ceil(time / physics.timeStep));
  tLand = state.t + ticks;
  if (tLand > maxTime) return null;
  if (!model.isWalkableCell(landing.x, landing.y, landing.z, tLand, state.phase)) return null;

  if (!ballisticPathClearLocal(state, landing, time, ticks, model, initialVy, physics, startInfo.surfaceY, maxTime, box)) {
    return null;
  }
  const cellId = cellKey(landing);
  const nextPhase = model.applyKeyPhase(state.phase, cellId);
  return { x: landing.x, y: landing.y, z: landing.z, t: tLand, phase: nextPhase };
}

function ballisticPathClearLocal(start, landing, time, ticks, model, initialVy, physics, startHeight, maxTime, box) {
  const samplesPerTick = 4;
  const samples = Math.max(4, ticks * samplesPerTick);
  for (let i = 1; i <= samples; i += 1) {
    const u = i / samples;
    const currentTime = time * u;
    const tIndex = start.t + Math.floor(currentTime / physics.timeStep);
    if (tIndex > maxTime) return false;
    const pos = {
      x: start.x + (landing.x - start.x) * u,
      y: startHeight + initialVy * currentTime + 0.5 * physics.gravity * currentTime * currentTime,
      z: start.z + (landing.z - start.z) * u,
    };
    const cell = roundCell(pos);
    if (!withinBox(cell, box)) return false;
    if (model.isBlockedCell(cell.x, cell.y, cell.z, tIndex, start.phase)) return false;
  }
  return true;
}

function pathClearLocal(start, end, tNext, model, phase, box) {
  const dx = end.x - start.x;
  const dz = end.z - start.z;
  const steps = Math.max(Math.abs(dx), Math.abs(dz));
  if (steps <= 1) return true;
  for (let i = 1; i < steps; i += 1) {
    const u = i / steps;
    const pos = {
      x: Math.round(start.x + dx * u),
      y: start.y,
      z: Math.round(start.z + dz * u),
    };
    if (!withinBox(pos, box)) return false;
    if (model.isBlockedCell(pos.x, pos.y, pos.z, tNext, phase)) return false;
  }
  return true;
}

function buildGroundOffsets(maxDistance) {
  const offsets = [];
  const radius = Math.floor(maxDistance + 0.001);
  for (let dx = -radius; dx <= radius; dx += 1) {
    for (let dz = -radius; dz <= radius; dz += 1) {
      if (dx === 0 && dz === 0) continue;
      const dist = Math.hypot(dx, dz);
      if (dist <= maxDistance + 1e-3) offsets.push({ dx, dz });
    }
  }
  return offsets;
}

function buildJumpOffsets(maxDistance, maxUp, maxDown, maxOffsets) {
  const offsets = [];
  const radius = Math.floor(maxDistance + 0.001);
  for (let dx = -radius; dx <= radius; dx += 1) {
    for (let dz = -radius; dz <= radius; dz += 1) {
      if (dx === 0 && dz === 0) continue;
      const dist = Math.hypot(dx, dz);
      if (dist > maxDistance + 1e-3) continue;
      for (let dy = -maxDown; dy <= maxUp; dy += 1) {
        if (dx === 0 && dz === 0 && dy === 0) continue;
        offsets.push({ dx, dy, dz });
      }
    }
  }
  offsets.sort((a, b) => {
    const da = a.dx * a.dx + a.dz * a.dz + Math.abs(a.dy) * 0.25;
    const db = b.dx * b.dx + b.dz * b.dz + Math.abs(b.dy) * 0.25;
    return da - db;
  });
  if (offsets.length > maxOffsets) return offsets.slice(0, maxOffsets);
  return offsets;
}

function buildPhysicsProfile(model) {
  const speed = 7.5;
  const gravity = -24;
  const jumpSpeed = 9.6;
  const timeStep = model.timeStep || 1;
  const airSpeed = speed * 1.35;
  const maxJumpTime = Math.max(timeStep, (2 * jumpSpeed) / Math.abs(gravity) + 0.9);
  const maxGroundDistance = speed * timeStep;
  const maxJumpDistance = airSpeed * maxJumpTime;
  const maxJumpUp = Math.ceil((jumpSpeed * jumpSpeed) / (2 * Math.abs(gravity))) + 4;
  const rawDrop = Math.ceil(0.5 * Math.abs(gravity) * maxJumpTime * maxJumpTime);
  const maxJumpDown = Math.min(rawDrop, 12);
  return {
    speed,
    airSpeed,
    gravity,
    jumpSpeed,
    timeStep,
    maxJumpTime,
    maxGroundDistance,
    maxJumpDistance,
    maxJumpUp,
    maxJumpDown,
  };
}

function chooseTimeForDy(dy, initialVy, gravity, minTime, maxTime) {
  const times = solveTimesForDy(dy, initialVy, gravity);
  if (!times.length) return null;
  for (const time of times) {
    if (time + 1e-4 >= minTime && time - 1e-4 <= maxTime) return time;
  }
  return null;
}

function solveTimesForDy(dy, initialVy, gravity) {
  const a = 0.5 * gravity;
  const b = initialVy;
  const c = -dy;
  const disc = b * b - 4 * a * c;
  if (disc < 0) return [];
  const sqrt = Math.sqrt(disc);
  const t1 = (-b - sqrt) / (2 * a);
  const t2 = (-b + sqrt) / (2 * a);
  return [t1, t2].filter((t) => t > 0).sort((x, y) => x - y);
}

function stateKey(state) {
  return `${state.t}|${state.phase}|${state.x},${state.y},${state.z}`;
}

function cellKey(cell) {
  return `${cell.x},${cell.y},${cell.z}`;
}

function roundCell(pos) {
  return {
    x: Math.round(pos.x),
    y: Math.floor(pos.y + 1e-3),
    z: Math.round(pos.z),
  };
}

function toCellCoord(pos, cellSize) {
  return {
    x: Math.round(pos.x / cellSize),
    y: Math.floor(pos.y / cellSize + 1e-3),
    z: Math.round(pos.z / cellSize),
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

function clampInt(value, min, max) {
  const n = Math.round(Number(value) || min);
  return Math.min(max, Math.max(min, n));
}

function buildSiblingToleranceSet(etg, parentId, excludeChildId) {
  const out = new Set();
  const edges = Array.isArray(etg?.edges) ? etg.edges : [];
  for (const e of edges) {
    if (!e) continue;
    const a = e.from;
    const b = e.to;
    if (a === parentId && b && b !== excludeChildId) out.add(b);
    if (b === parentId && a && a !== excludeChildId) out.add(a);
  }
  return out;
}

function manhattanDistance3(a, b) {
  return Math.abs(a.x - b.x) + Math.abs(a.y - b.y) + Math.abs(a.z - b.z);
}

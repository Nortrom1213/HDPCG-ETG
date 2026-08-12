export function computeReachable(model, options = {}) {
  const allowJump = options.allowJump ?? true;
  const allowDrop = options.allowDrop ?? true;
  const compressTime = options.compressTime ?? false;
  const walkableToleranceCells = clampInt(options.walkableToleranceCells ?? 1, 0, 2);
  const defaultMaxTime = estimateMaxTime(model);
  const maxTimeCap = Math.max(600, model.timeHorizon * (model.phaseCount + 2) * 2);
  const maxTime = clampInt(options.maxTime ?? defaultMaxTime, 0, maxTimeCap);
  const baseMaxStates = options.maxStates ?? 250000;
  const baseMaxQueue = options.maxQueue ?? 200000;
  const maxStates = Math.min(1200000, Math.max(baseMaxStates, maxTime * 1200));
  const maxQueue = Math.min(900000, Math.max(baseMaxQueue, maxTime * 900));
  const maxJumpOffsets = clampInt(options.maxJumpOffsets ?? 1400, 200, 6000);

  const timeHorizon = model.timeHorizon;
  const phaseCount = model.phaseCount;
  const startCell = model.findNearestWalkable(model.startCell, 0, 0) || model.startCell;
  const horizon = Math.max(1, timeHorizon || 1);

  const reachableByTimePhase = Array.from({ length: maxTime + 1 }, () =>
    Array.from({ length: phaseCount }, () => new Set())
  );

  const queue = [];
  let head = 0;
  const visited = new Set();
  const startState = { x: startCell.x, y: startCell.y, z: startCell.z, t: 0, phase: 0 };
  const visitKey = (state) =>
    compressTime
      ? `${state.phase}|${state.x},${state.y},${state.z}|${state.t % horizon}`
      : stateKey(state);
  const startKey = visitKey(startState);
  visited.add(startKey);
  queue.push(startState);

  let expanded = 0;
  let truncated = false;
  const boundary = { timeBoundaryHits: 0 };
  const physics = buildPhysicsProfile(model);
  const groundOffsets = buildGroundOffsets(physics.maxGroundDistance);
  const jumpOffsets = allowJump
    ? buildJumpOffsets(physics.maxJumpDistance, physics.maxJumpUp, physics.maxJumpDown, maxJumpOffsets)
    : [];

  while (head < queue.length) {
    const state = queue[head++];
    expanded += 1;
    if (expanded > maxStates || queue.length - head > maxQueue) {
      truncated = true;
      break;
    }

    const cellId = cellKey(state);
    reachableByTimePhase[state.t][state.phase].add(cellId);

    const neighbors = collectNeighbors(
      state,
      model,
      physics,
      groundOffsets,
      jumpOffsets,
      allowJump,
      allowDrop,
      maxTime,
      boundary,
      walkableToleranceCells
    );
    for (const next of neighbors) {
      const key = visitKey(next);
      if (visited.has(key)) continue;
      visited.add(key);
      queue.push(next);
    }
  }

  const cumulative = buildCumulativeReachable(reachableByTimePhase);
  const cumulativeByTimePhase = cumulative.byPhase;
  const cumulativeByTimeUnion = cumulative.unionByTime;
  const maxTimeUsed = findLastGrowthTime(cumulativeByTimePhase);
  const lastReachableCellTime = findLastUnionGrowthTime(cumulativeByTimeUnion);
  const lastReachableStateTime = findLastStateTime(reachableByTimePhase);

  return {
    reachableByTimePhase,
    reachableCumulativeByTimePhase: cumulativeByTimePhase,
    reachableCumulativeByTimeUnion: cumulativeByTimeUnion,
    visitedCount: visited.size,
    expanded,
    truncated,
    startCell,
    maxTime,
    maxTimeUsed,
    lastReachableCellTime,
    lastReachableStateTime,
    timeBoundaryHits: boundary.timeBoundaryHits,
    compressTime,
    walkableToleranceCells,
  };
}

function collectNeighbors(
  state,
  model,
  physics,
  groundOffsets,
  jumpOffsets,
  allowJump,
  allowDrop,
  maxTime,
  boundary,
  walkableToleranceCells
) {
  const nextStates = [];
  const phaseCount = model.phaseCount;
  const tNext = state.t + 1;
  if (tNext > maxTime) {
    boundary.timeBoundaryHits += 1;
    return nextStates;
  }

  const addState = (x, y, z, t, phase) => {
    nextStates.push({ x, y, z, t, phase });
  };

  const addMove = (x, y, z, t, phase) => {
    const cellId = cellKey({ x, y, z });
    const nextPhase = model.applyKeyPhase(phase, cellId);
    addState(x, y, z, t, Math.min(nextPhase, phaseCount - 1));
  };

  if (model.isWalkableCell(state.x, state.y, state.z, tNext, state.phase)) {
    addMove(state.x, state.y, state.z, tNext, state.phase);
  }

  for (const offset of groundOffsets) {
    const x = state.x + offset.dx;
    const y = state.y;
    const z = state.z + offset.dz;
    const resolved = resolveWalkableCell({ x, y, z }, tNext, state.phase, model, walkableToleranceCells);
    if (!resolved) continue;
    if (!pathClear(state, resolved, tNext, model, state.phase)) continue;
    addMove(resolved.x, resolved.y, resolved.z, tNext, state.phase);
  }

  const surfaceInfo = model.getSurfaceInfo(state.t, cellKey(state));
  if (surfaceInfo && surfaceInfo.moving) {
    const nextCell = rideWithPlatform(state, surfaceInfo, model, tNext, walkableToleranceCells);
    if (nextCell) addMove(nextCell.x, nextCell.y, nextCell.z, tNext, state.phase);
  }

  if (allowJump || allowDrop) {
    for (const offset of jumpOffsets) {
      const jump = allowJump
        ? tryBallisticMove(
            state,
            offset,
            model,
            physics.jumpSpeed,
            physics,
            maxTime,
            boundary,
            walkableToleranceCells
          )
        : null;
      if (jump) {
        nextStates.push(jump);
        continue;
      }
      if (allowDrop) {
        const drop = tryBallisticMove(state, offset, model, 0, physics, maxTime, boundary, walkableToleranceCells);
        if (drop) nextStates.push(drop);
      }
    }
  }

  return nextStates;
}

function rideWithPlatform(state, surfaceInfo, model, tNext, walkableToleranceCells) {
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
  const resolved = resolveWalkableCell(
    { x: targetX, y: targetY, z: targetZ },
    tNext,
    state.phase,
    model,
    walkableToleranceCells
  );
  if (!resolved) return null;
  return { x: resolved.x, y: resolved.y, z: resolved.z, t: tNext, phase: state.phase };
}

function tryBallisticMove(state, offset, model, initialVy, physics, maxTime, boundary, walkableToleranceCells) {
  let landing = {
    x: state.x + offset.dx,
    y: state.y + offset.dy,
    z: state.z + offset.dz,
  };
  let horiz = Math.hypot(offset.dx, offset.dz);
  if (horiz < 0.01 && offset.dy === 0) return null;

  const startInfo = model.getSurfaceInfo(state.t, cellKey(state));
  if (!startInfo) return null;
  let tLand = state.t + 1;
  if (tLand > maxTime) {
    boundary.timeBoundaryHits += 1;
    return null;
  }
  let resolved = resolveSurfaceAtTime(landing, tLand, state.phase, model, walkableToleranceCells);
  if (!resolved) return null;
  landing = resolved.cell;
  let landingInfo = resolved.surfaceInfo;

  let dy = landingInfo.surfaceY - startInfo.surfaceY;
  horiz = Math.hypot(landing.x - state.x, landing.z - state.z);
  const minTime = horiz / physics.airSpeed;
  let time = chooseTimeForDy(dy, initialVy, physics.gravity, minTime, physics.maxJumpTime);
  if (!time) return null;

  let ticks = Math.max(1, Math.ceil(time / physics.timeStep));
  tLand = state.t + ticks;
  if (tLand > maxTime) {
    boundary.timeBoundaryHits += 1;
    return null;
  }
  resolved = resolveSurfaceAtTime(landing, tLand, state.phase, model, walkableToleranceCells);
  if (!resolved) return null;
  landing = resolved.cell;
  landingInfo = resolved.surfaceInfo;
  dy = landingInfo.surfaceY - startInfo.surfaceY;
  horiz = Math.hypot(landing.x - state.x, landing.z - state.z);
  const minTime2 = horiz / physics.airSpeed;
  time = chooseTimeForDy(dy, initialVy, physics.gravity, minTime2, physics.maxJumpTime);
  if (!time) return null;
  ticks = Math.max(1, Math.ceil(time / physics.timeStep));
  tLand = state.t + ticks;
  if (tLand > maxTime) {
    boundary.timeBoundaryHits += 1;
    return null;
  }
  const finalCell = resolveWalkableCell(landing, tLand, state.phase, model, walkableToleranceCells);
  if (!finalCell) return null;
  landing = finalCell;

  if (
    !ballisticPathClear(state, landing, time, ticks, model, initialVy, physics, startInfo.surfaceY, maxTime)
  ) {
    return null;
  }
  const cellId = cellKey(landing);
  const nextPhase = model.applyKeyPhase(state.phase, cellId);
  return { x: landing.x, y: landing.y, z: landing.z, t: tLand, phase: nextPhase };
}

function resolveWalkableCell(target, t, phase, model, walkableToleranceCells) {
  if (model.isWalkableCell(target.x, target.y, target.z, t, phase)) return target;
  if (walkableToleranceCells <= 0) return null;
  return model.findNearestWalkable(target, t, phase, walkableToleranceCells);
}

function resolveSurfaceAtTime(target, t, phase, model, walkableToleranceCells) {
  const directId = cellKey(target);
  const directInfo = model.getSurfaceInfo(t, directId);
  if (directInfo) return { cell: target, surfaceInfo: directInfo };
  const resolved = resolveWalkableCell(target, t, phase, model, walkableToleranceCells);
  if (!resolved) return null;
  const resolvedInfo = model.getSurfaceInfo(t, cellKey(resolved));
  if (!resolvedInfo) return null;
  return { cell: resolved, surfaceInfo: resolvedInfo };
}

function ballisticPathClear(start, landing, time, ticks, model, initialVy, physics, startHeight, maxTime) {
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
    if (model.isBlockedCell(cell.x, cell.y, cell.z, tIndex, start.phase)) return false;
  }
  return true;
}

function pathClear(start, end, tNext, model, phase) {
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

function clampInt(value, min, max) {
  const n = Math.round(Number(value) || min);
  return Math.min(max, Math.max(min, n));
}

function estimateMaxTime(model) {
  const speed = 7.5;
  const padding = 40;
  const hardMin = 120;
  const phaseCount = Math.max(1, model.phaseCount || 1);
  const start = model.startCell || { x: 0, y: 0, z: 0 };
  const goal = model.goalCell;
  let dist = 0;
  if (goal) {
    dist = Math.hypot(goal.x - start.x, goal.z - start.z);
  } else if (model.bounds) {
    const spanX = model.bounds.max.x - model.bounds.min.x;
    const spanZ = model.bounds.max.z - model.bounds.min.z;
    dist = Math.hypot(spanX, spanZ);
  }
  const base = Math.ceil(dist / speed) + padding;
  const phaseBudget = (phaseCount - 1) * 90;
  const horizonBudget = Math.max(0, model.timeHorizon - 1) * 3;
  const estimate = base + Math.max(phaseBudget, horizonBudget);
  const hardMax = Math.max(360, base + phaseBudget + horizonBudget);
  return clampInt(estimate, hardMin, hardMax);
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

function buildCumulativeReachable(reachableByTimePhase) {
  const maxTime = reachableByTimePhase.length - 1;
  const phaseCount = reachableByTimePhase[0]?.length || 0;
  const cumulativeByPhase = Array.from({ length: maxTime + 1 }, () =>
    Array.from({ length: phaseCount }, () => new Set())
  );
  const cumulativeUnion = Array.from({ length: maxTime + 1 }, () => new Set());
  for (let t = 0; t <= maxTime; t += 1) {
    const union = cumulativeUnion[t];
    if (t > 0) {
      for (const cell of cumulativeUnion[t - 1]) union.add(cell);
    }
    for (let p = 0; p < phaseCount; p += 1) {
      const prev = t > 0 ? cumulativeByPhase[t - 1][p] : null;
      const current = reachableByTimePhase[t][p];
      const next = cumulativeByPhase[t][p];
      if (prev) {
        for (const cell of prev) next.add(cell);
      }
      for (const cell of current) {
        next.add(cell);
        union.add(cell);
      }
    }
  }
  return {
    byPhase: cumulativeByPhase,
    unionByTime: cumulativeUnion,
  };
}

function findLastGrowthTime(cumulativeByTimePhase) {
  const maxTime = cumulativeByTimePhase.length - 1;
  const phaseCount = cumulativeByTimePhase[0]?.length || 0;
  let lastGrowth = 0;
  for (let t = 1; t <= maxTime; t += 1) {
    let grew = false;
    for (let p = 0; p < phaseCount; p += 1) {
      if (cumulativeByTimePhase[t][p].size > cumulativeByTimePhase[t - 1][p].size) {
        grew = true;
        break;
      }
    }
    if (grew) lastGrowth = t;
  }
  return lastGrowth;
}

function findLastUnionGrowthTime(cumulativeByTimeUnion) {
  const maxTime = cumulativeByTimeUnion.length - 1;
  let lastGrowth = 0;
  for (let t = 1; t <= maxTime; t += 1) {
    if (cumulativeByTimeUnion[t].size > cumulativeByTimeUnion[t - 1].size) {
      lastGrowth = t;
    }
  }
  return lastGrowth;
}

function findLastStateTime(reachableByTimePhase) {
  const maxTime = reachableByTimePhase.length - 1;
  const phaseCount = reachableByTimePhase[0]?.length || 0;
  let last = 0;
  for (let t = 0; t <= maxTime; t += 1) {
    let any = false;
    for (let p = 0; p < phaseCount; p += 1) {
      if (reachableByTimePhase[t][p].size > 0) {
        any = true;
        break;
      }
    }
    if (any) last = t;
  }
  return last;
}

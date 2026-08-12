const DEFAULT_PADDING = 4;
const LOCK_PADDING = 0.6;
const LOCK_PLAYER_RADIUS = 0.6;

export function buildHDPCGModel(level, options = {}) {
  const cellSize = options.cellSize ?? 1;
  const timeStep = options.timeStep ?? 1;
  const padding = options.padding ?? DEFAULT_PADDING;
  const maxTimeHorizon = Math.max(1, Math.floor(Number(options.maxTimeHorizon ?? 180)));
  const maxPeriodTicks = Math.max(1, Math.floor(Number(options.maxPeriodTicks ?? 180)));

  // Reserve lock-referenced key ids so each lock retains a valid phase index.
  const keyOrder = buildKeyOrder(level.keys, level.locks);
  const keyIndexById = new Map(keyOrder.map((key, index) => [key.key_id, index]));
  const phaseCount = keyOrder.length + 1;

  const platformById = new Map(level.platforms.map((platform) => [platform.id, platform]));
  const movingPlatformIds = new Set(
    level.platforms.filter((platform) => platform.kind === "moving" && platform.motion).map((platform) => platform.id)
  );

  const timeHorizon = computeTimeHorizon(level, timeStep, { maxTimeHorizon, maxPeriodTicks });
  const bounds = computeBounds(level, cellSize, padding);
  const surfaces = buildSurfaceCache(level, timeHorizon, cellSize, timeStep);
  const enemies = buildEnemyCache(level, timeHorizon, cellSize, timeStep);

  const keyCells = new Map();
  const keyPickupCells = new Map();
  const lockCells = new Map();
  const surfaceColumns = buildSurfaceColumnMap(surfaces.surfaceByTime[0]);
  for (const key of level.keys) {
    const snapped = snapToSurfaceCell(key.pos, surfaceColumns, cellSize);
    const cell = snapped || toCellCoord(key.pos, cellSize);
    const index = keyIndexById.get(key.key_id);
    if (index === undefined) continue;
    keyCells.set(cellKey(cell), index);
    const pickupCells = expandPickupCells(key.pos, cell, cellSize, 1.1, surfaceColumns);
    for (const pickup of pickupCells) {
      const id = cellKey(pickup);
      const existing = keyPickupCells.get(id);
      if (existing === undefined || index < existing) keyPickupCells.set(id, index);
    }
  }
  const addLockCell = (cell, lockIndex) => {
    const id = cellKey(cell);
    const existing = lockCells.get(id);
    if (existing === undefined || (existing < 0 && lockIndex >= 0)) {
      lockCells.set(id, lockIndex);
    } else if (lockIndex >= 0 && lockIndex < existing) {
      lockCells.set(id, lockIndex);
    }
  };
  for (const lock of level.locks) {
    const index = keyIndexById.get(lock.key_id);
    const lockIndex = index ?? -1;
    const volumeCells = expandLockVolume(lock, cellSize, LOCK_PADDING);
    for (const cell of volumeCells) addLockCell(cell, lockIndex);
    const footprintCells = expandLockFootprint(
      lock,
      surfaces.surfaceByTime[0],
      surfaceColumns,
      cellSize,
      LOCK_PADDING,
      LOCK_PLAYER_RADIUS
    );
    for (const cell of footprintCells) addLockCell(cell, lockIndex);
  }

  const startCell = toCellCoord(level.start, cellSize);
  const goalCell = level.goal ? toCellCoord(level.goal, cellSize) : null;

  function isLockedCell(cellId, phase) {
    if (!lockCells.has(cellId)) return false;
    const index = lockCells.get(cellId);
    if (index < 0) return false;
    return phase <= index;
  }

  function wrapTime(t) {
    if (timeHorizon <= 0) return 0;
    return t % timeHorizon;
  }

  function isEnemyCell(cellId, t) {
    const idx = wrapTime(t);
    return enemies[idx] && enemies[idx].has(cellId);
  }

  function isWalkableCell(x, y, z, t, phase) {
    const idx = wrapTime(t);
    const cellId = cellKey({ x, y, z });
    if (!surfaces.surfaceByTime[idx]?.has(cellId)) return false;
    if (isEnemyCell(cellId, idx)) return false;
    if (isLockedCell(cellId, phase)) return false;
    return true;
  }

  function isBlockedCell(x, y, z, t, phase) {
    const idx = wrapTime(t);
    const cellId = cellKey({ x, y, z });
    if (isEnemyCell(cellId, idx)) return true;
    if (isLockedCell(cellId, phase)) return true;
    return false;
  }

  function applyKeyPhase(phase, cellId) {
    if (!keyPickupCells.has(cellId)) return phase;
    const keyIndex = keyPickupCells.get(cellId);
    if (phase === keyIndex) return Math.min(phase + 1, phaseCount - 1);
    return phase;
  }

  function findNearestWalkable(cell, t, phase, maxRadius = 6) {
    if (isWalkableCell(cell.x, cell.y, cell.z, t, phase)) return { ...cell };
    for (let radius = 1; radius <= maxRadius; radius += 1) {
      for (let dx = -radius; dx <= radius; dx += 1) {
        for (let dy = -radius; dy <= radius; dy += 1) {
          for (let dz = -radius; dz <= radius; dz += 1) {
            const target = { x: cell.x + dx, y: cell.y + dy, z: cell.z + dz };
            if (isWalkableCell(target.x, target.y, target.z, t, phase)) return target;
          }
        }
      }
    }
    return null;
  }

  function getSurfaceInfo(t, cellId) {
    const idx = wrapTime(t);
    return surfaces.surfaceByTime[idx]?.get(cellId) || null;
  }

  function getPlatformPos(platformId, t) {
    const platform = platformById.get(platformId);
    if (!platform) return null;
    if (platform.kind !== "moving" || !platform.motion) return { ...platform.pos };
    return samplePlatformPos(platform, wrapTime(t), timeStep);
  }

  return {
    cellSize,
    timeStep,
    timeHorizon,
    phaseCount,
    bounds,
    platformById,
    movingPlatformIds,
    keyCells,
    keyPickupCells,
    lockCells,
    surfaceByTime: surfaces.surfaceByTime,
    enemiesByTime: enemies,
    startCell,
    goalCell,
    isWalkableCell,
    isBlockedCell,
    isLockedCell,
    isEnemyCell,
    wrapTime,
    applyKeyPhase,
    findNearestWalkable,
    getSurfaceInfo,
    getPlatformPos,
  };
}

export function computeTimeHorizon(level, timeStep, options = {}) {
  const horizonCap = Math.max(1, Math.floor(Number(options.maxTimeHorizon ?? 180)));
  const periodCap = Math.max(1, Math.floor(Number(options.maxPeriodTicks ?? 180)));
  const periods = [];
  for (const platform of level.platforms) {
    if (platform.kind !== "moving" || !platform.motion) continue;
    const ticks = Math.min(periodCap, Math.max(1, Math.round((platform.motion.period || 1) / timeStep)));
    periods.push(ticks);
  }
  for (const enemy of level.enemies) {
    if (!enemy.patrol) continue;
    const span = Math.abs(enemy.patrol.to.x - enemy.patrol.from.x);
    const speed = Math.max(0.0001, enemy.speed || 1);
    const ticks = Math.min(periodCap, Math.max(1, Math.round((2 * span) / (speed * timeStep))));
    periods.push(ticks);
  }
  if (periods.length === 0) return 1;
  return lcmArray(periods, horizonCap);
}

function buildKeyOrder(keys, locks) {
  const byId = new Map();
  for (const key of [...(keys || [])]) {
    if (!key?.key_id) continue;
    if (!byId.has(key.key_id)) byId.set(key.key_id, key);
  }
  for (const lock of [...(locks || [])]) {
    if (!lock?.key_id) continue;
    if (!byId.has(lock.key_id)) byId.set(lock.key_id, { key_id: lock.key_id, _virtual: true });
  }
  const list = Array.from(byId.values());
  list.sort((a, b) => {
    const aNum = extractNumber(a.key_id);
    const bNum = extractNumber(b.key_id);
    if (aNum !== bNum) return aNum - bNum;
    return a.key_id.localeCompare(b.key_id);
  });
  return list;
}

function extractNumber(value) {
  const match = String(value || "").match(/\d+/);
  if (!match) return Number.POSITIVE_INFINITY;
  return Number(match[0]);
}

function buildSurfaceCache(level, timeHorizon, cellSize, timeStep) {
  const surfaceByTime = Array.from({ length: timeHorizon }, () => new Map());
  const staticPlatforms = level.platforms.filter((p) => p.kind !== "moving" || !p.motion);
  const movingPlatforms = level.platforms.filter((p) => p.kind === "moving" && p.motion);

  const staticCells = [];
  for (const platform of staticPlatforms) {
    staticCells.push(...surfaceCellsForPlatform(platform, platform.pos, cellSize));
  }

  for (let t = 0; t < timeHorizon; t += 1) {
    const map = surfaceByTime[t];
    for (const cell of staticCells) {
      map.set(cellKey(cell), cell);
    }
    for (const platform of movingPlatforms) {
      const pos = samplePlatformPos(platform, t, timeStep);
      const cells = surfaceCellsForPlatform(platform, pos, cellSize);
      for (const cell of cells) {
        map.set(cellKey(cell), cell);
      }
    }
  }

  return { surfaceByTime };
}

function buildEnemyCache(level, timeHorizon, cellSize, timeStep) {
  const enemyByTime = Array.from({ length: timeHorizon }, () => new Set());
  for (let t = 0; t < timeHorizon; t += 1) {
    const set = enemyByTime[t];
    for (const enemy of level.enemies) {
      const pos = sampleEnemyPos(enemy, t, timeStep);
      if (!pos) continue;
      const cell = toCellCoord(pos, cellSize);
      set.add(cellKey(cell));
    }
  }
  return enemyByTime;
}

function surfaceCellsForPlatform(platform, pos, cellSize) {
  const halfX = platform.size.x * 0.5;
  const halfZ = platform.size.z * 0.5;
  const topY = pos.y + platform.size.y * 0.5;
  const gridY = gridifyY(topY, cellSize);

  const minX = (pos.x - halfX) / cellSize;
  const maxX = (pos.x + halfX) / cellSize;
  const minZ = (pos.z - halfZ) / cellSize;
  const maxZ = (pos.z + halfZ) / cellSize;

  const startX = Math.ceil(minX);
  const endX = Math.floor(maxX);
  const startZ = Math.ceil(minZ);
  const endZ = Math.floor(maxZ);

  const centerX = Math.round(pos.x / cellSize);
  const centerZ = Math.round(pos.z / cellSize);

  const cells = [];
  for (let x = startX; x <= endX; x += 1) {
    for (let z = startZ; z <= endZ; z += 1) {
      cells.push({
        x,
        y: gridY,
        z,
        platformId: platform.id,
        moving: platform.kind === "moving",
        surfaceY: topY,
        localOffset: { x: x - centerX, z: z - centerZ },
      });
    }
  }
  return cells;
}

function samplePlatformPos(platform, t, timeStep) {
  const pos = { ...platform.pos };
  const { axis, amplitude, period, phase } = platform.motion;
  const ticks = Math.max(1, Math.round((period || 1) / timeStep));
  const omega = (2 * Math.PI) / ticks;
  const offset = Math.sin(omega * t + (phase || 0)) * (amplitude || 0);
  pos[axis] = platform.pos[axis] + offset;
  return pos;
}

function sampleEnemyPos(enemy, t, timeStep) {
  if (!enemy.patrol) return enemy.pos;
  const span = enemy.patrol.to.x - enemy.patrol.from.x;
  const total = Math.abs(span);
  if (total <= 0) return enemy.pos;
  const speed = Math.max(0.0001, enemy.speed || 1);
  const step = speed * timeStep;
  let offset = (t * step) % (2 * total);
  if (offset > total) offset = 2 * total - offset;
  const dir = span >= 0 ? 1 : -1;
  return {
    x: enemy.patrol.from.x + dir * offset,
    y: enemy.patrol.from.y,
    z: enemy.patrol.from.z,
  };
}

function computeBounds(level, cellSize, padding) {
  const bounds = {
    min: { x: Infinity, y: Infinity, z: Infinity },
    max: { x: -Infinity, y: -Infinity, z: -Infinity },
  };

  const expand = (x, y, z) => {
    bounds.min.x = Math.min(bounds.min.x, x);
    bounds.min.y = Math.min(bounds.min.y, y);
    bounds.min.z = Math.min(bounds.min.z, z);
    bounds.max.x = Math.max(bounds.max.x, x);
    bounds.max.y = Math.max(bounds.max.y, y);
    bounds.max.z = Math.max(bounds.max.z, z);
  };

  for (const platform of level.platforms) {
    const halfX = platform.size.x * 0.5;
    const halfY = platform.size.y * 0.5;
    const halfZ = platform.size.z * 0.5;
    let minX = platform.pos.x - halfX;
    let maxX = platform.pos.x + halfX;
    let minZ = platform.pos.z - halfZ;
    let maxZ = platform.pos.z + halfZ;
    if (platform.kind === "moving" && platform.motion) {
      const amp = Math.abs(platform.motion.amplitude || 0);
      if (platform.motion.axis === "x") {
        minX -= amp;
        maxX += amp;
      } else if (platform.motion.axis === "z") {
        minZ -= amp;
        maxZ += amp;
      }
    }
    expand(minX, platform.pos.y - halfY, minZ);
    expand(maxX, platform.pos.y + halfY, maxZ);
  }

  for (const enemy of level.enemies) {
    if (enemy.patrol) {
      expand(enemy.patrol.from.x, enemy.patrol.from.y, enemy.patrol.from.z);
      expand(enemy.patrol.to.x, enemy.patrol.to.y, enemy.patrol.to.z);
    } else {
      expand(enemy.pos.x, enemy.pos.y, enemy.pos.z);
    }
  }

  for (const key of level.keys) expand(key.pos.x, key.pos.y, key.pos.z);
  for (const lock of level.locks) expand(lock.pos.x, lock.pos.y, lock.pos.z);
  if (level.start) expand(level.start.x, level.start.y, level.start.z);
  if (level.goal) expand(level.goal.x, level.goal.y, level.goal.z);

  const min = {
    x: Math.floor(bounds.min.x / cellSize) - padding,
    y: Math.floor(bounds.min.y / cellSize) - padding,
    z: Math.floor(bounds.min.z / cellSize) - padding,
  };
  const max = {
    x: Math.ceil(bounds.max.x / cellSize) + padding,
    y: Math.ceil(bounds.max.y / cellSize) + padding,
    z: Math.ceil(bounds.max.z / cellSize) + padding,
  };

  return { min, max };
}

function toCellCoord(pos, cellSize) {
  return {
    x: Math.round(pos.x / cellSize),
    y: gridifyY(pos.y, cellSize),
    z: Math.round(pos.z / cellSize),
  };
}

function cellKey(cell) {
  return `${cell.x},${cell.y},${cell.z}`;
}

function gridifyY(value, cellSize) {
  return Math.floor(value / cellSize + 1e-3);
}

function buildSurfaceColumnMap(surfaceMap) {
  const map = new Map();
  if (!surfaceMap) return map;
  for (const cell of surfaceMap.values()) {
    const key = `${cell.x},${cell.z}`;
    const list = map.get(key) || [];
    list.push(cell);
    map.set(key, list);
  }
  return map;
}

function snapToSurfaceCell(pos, surfaceColumns, cellSize) {
  const baseX = Math.round(pos.x / cellSize);
  const baseZ = Math.round(pos.z / cellSize);
  let best = null;
  let bestDist = Infinity;
  for (let dx = -1; dx <= 1; dx += 1) {
    for (let dz = -1; dz <= 1; dz += 1) {
      const key = `${baseX + dx},${baseZ + dz}`;
      const list = surfaceColumns.get(key);
      if (!list) continue;
      for (const cell of list) {
        const dist = Math.abs(cell.surfaceY - pos.y);
        if (dist < bestDist) {
          bestDist = dist;
          best = cell;
        }
      }
    }
  }
  if (!best) return null;
  return { x: best.x, y: best.y, z: best.z };
}

function expandLockVolume(lock, cellSize, padding) {
  const size = lock.size || { x: 2, y: 3, z: 0.6 };
  const half = {
    x: size.x * 0.5 + padding,
    y: size.y * 0.5 + padding,
    z: size.z * 0.5 + padding,
  };
  const minX = Math.floor((lock.pos.x - half.x) / cellSize);
  const maxX = Math.floor((lock.pos.x + half.x) / cellSize);
  const minY = Math.floor((lock.pos.y - half.y) / cellSize);
  const maxY = Math.floor((lock.pos.y + half.y) / cellSize);
  const minZ = Math.floor((lock.pos.z - half.z) / cellSize);
  const maxZ = Math.floor((lock.pos.z + half.z) / cellSize);

  const cells = [];
  for (let x = minX; x <= maxX; x += 1) {
    for (let y = minY; y <= maxY; y += 1) {
      for (let z = minZ; z <= maxZ; z += 1) {
        cells.push({ x, y, z });
      }
    }
  }
  return cells;
}

function expandLockFootprint(lock, surfaceMap, surfaceColumns, cellSize, padding, playerRadius) {
  if (!surfaceMap || surfaceMap.size === 0) return [];
  const size = lock.size || { x: 2, y: 3, z: 0.6 };
  const thinAxis = size.x <= size.z ? "x" : "z";
  const band = (thinAxis === "x" ? size.x : size.z) * 0.5 + padding + playerRadius;
  const minY = lock.pos.y - size.y * 0.5 - padding - playerRadius;
  const maxY = lock.pos.y + size.y * 0.5 + padding + playerRadius;
  const minYCell = Math.floor(minY / cellSize);
  const maxYCell = Math.floor(maxY / cellSize);

  const seed = snapToSurfaceCell(lock.pos, surfaceColumns, cellSize);
  if (!seed) return [];

  const visited = new Set();
  const queue = [];
  const push = (cell) => {
    const id = cellKey(cell);
    if (visited.has(id)) return;
    visited.add(id);
    queue.push(cell);
  };
  push(seed);

  const component = [];
  const neighborDeltas = [
    { dx: 1, dz: 0 },
    { dx: -1, dz: 0 },
    { dx: 0, dz: 1 },
    { dx: 0, dz: -1 },
  ];
  const yOffsets = [0, 1, -1];

  let head = 0;
  while (head < queue.length) {
    const current = queue[head++];
    component.push(current);
    for (const delta of neighborDeltas) {
      for (const dy of yOffsets) {
        const neighbor = {
          x: current.x + delta.dx,
          y: current.y + dy,
          z: current.z + delta.dz,
        };
        const id = cellKey(neighbor);
        const surface = surfaceMap.get(id);
        if (!surface) continue;
        push(surface);
      }
    }
  }

  const cells = [];
  for (const cell of component) {
    const worldX = cell.x * cellSize;
    const worldZ = cell.z * cellSize;
    const axisDist = thinAxis === "x" ? worldX - lock.pos.x : worldZ - lock.pos.z;
    if (Math.abs(axisDist) > band + 1e-3) continue;
    const surfaceY = cell.surfaceY ?? cell.y * cellSize;
    if (surfaceY < minY || surfaceY > maxY) continue;
    for (let y = minYCell; y <= maxYCell; y += 1) {
      cells.push({ x: cell.x, y, z: cell.z });
    }
  }
  return cells;
}

function expandPickupCells(pos, fallbackCell, cellSize, radius, surfaceColumns) {
  const cells = [];
  const visited = new Set();
  const maxOffset = Math.max(1, Math.ceil(radius / cellSize) + 1);
  const baseX = Math.round(pos.x / cellSize);
  const baseZ = Math.round(pos.z / cellSize);

  for (let dx = -maxOffset; dx <= maxOffset; dx += 1) {
    for (let dz = -maxOffset; dz <= maxOffset; dz += 1) {
      const key = `${baseX + dx},${baseZ + dz}`;
      const column = surfaceColumns.get(key);
      if (!column) continue;
      for (const cell of column) {
        const worldX = cell.x * cellSize;
        const worldY = cell.surfaceY;
        const worldZ = cell.z * cellSize;
        const dist = Math.hypot(worldX - pos.x, worldY - pos.y, worldZ - pos.z);
        if (dist > radius + 1e-3) continue;
        const id = cellKey(cell);
        if (visited.has(id)) continue;
        visited.add(id);
        cells.push({ x: cell.x, y: cell.y, z: cell.z });
      }
    }
  }

  const fallbackId = cellKey(fallbackCell);
  if (!visited.has(fallbackId)) cells.push(fallbackCell);
  return cells;
}

function gcd(a, b) {
  let x = Math.abs(a);
  let y = Math.abs(b);
  while (y) {
    const t = y;
    y = x % y;
    x = t;
  }
  return x;
}

function lcm(a, b) {
  return Math.abs(a * b) / gcd(a, b);
}

function lcmArray(values, cap = Number.POSITIVE_INFINITY) {
  let out = 1;
  for (const value of values) {
    out = lcm(out, value);
    if (out >= cap) return cap;
  }
  return out;
}

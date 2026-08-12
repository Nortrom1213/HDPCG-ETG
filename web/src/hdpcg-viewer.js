import * as THREE from "../vendor/three.module.js";
import { rngFromSeed } from "./random.js";
import { createETG } from "./etg.js";
import { generateLevel } from "./generator.js";
import { validateAndRepair } from "./validator.js";
import { normalizeETG } from "./etg-utils.js";
import { buildHDPCGModel } from "./hdpcg-grid.js";
import { computeReachable } from "./hdpcg-bfs.js";

const canvas = document.querySelector("#viewer-canvas");
const importInput = document.querySelector("#import-file");

const timeSlider = document.querySelector("#time-slider");
const phaseSlider = document.querySelector("#phase-slider");
const showReachableInput = document.querySelector("#show-reachable");
const reachModeInput = document.querySelector("#reach-mode");
const showEnemiesInput = document.querySelector("#show-enemies");
const statusOutput = document.querySelector("#viewer-status");
const bfsOutput = document.querySelector("#bfs-output");

let renderer;
let scene;
let camera;
let orbit;

let model = null;
let bfsResult = null;
let level = null;
let sourceLabel = "generated";
let latestReport = null;
let reachabilityWarning = "";

let walkableMesh = null;
let lockedMesh = null;
let reachableMesh = null;
let enemyMesh = null;
let keyMesh = null;
let lockMesh = null;
let startMesh = null;
let goalMesh = null;

function bootstrap() {
  try {
    assertCoreElements();
    initScene();
    bindEvents();
    const params = new URLSearchParams(window.location.search);
    const wantsEtg = params.get("etg") === "1";

    if (wantsEtg) {
      if (!loadEtgOverride()) {
        lockEntry("Missing ETG preview data. Please click 5D Preview in the ETG Editor.");
        return;
      }
      generate();
      return;
    }

    // Direct opening waits for an explicit generation request.
    lockEntry("Entry locked. Please open this page from the ETG Editor preview, or import a JSON file.");
  } catch (err) {
    reportInitError(err);
  }
}

function lockEntry(message) {
  if (bfsOutput) bfsOutput.textContent = message;
  if (statusOutput) statusOutput.textContent = "locked";
}

function bindEvents() {
  importInput?.addEventListener("change", (event) => loadFromFile(event.target.files?.[0]));
  importInput?.addEventListener("click", () => {
    importInput.value = "";
  });
  timeSlider.addEventListener("input", renderFrame);
  phaseSlider.addEventListener("input", renderFrame);
  showReachableInput.addEventListener("change", renderFrame);
  reachModeInput.addEventListener("change", () => {
    renderFrame();
    updateBfsOutput();
  });
  showEnemiesInput.addEventListener("change", renderFrame);
}

function initScene() {
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0xf8f3ec);
  camera = new THREE.PerspectiveCamera(65, 1, 0.1, 400);
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio || 1);

  const ambient = new THREE.AmbientLight(0xffffff, 0.7);
  scene.add(ambient);
  const dir = new THREE.DirectionalLight(0xffffff, 0.7);
  dir.position.set(10, 20, 10);
  scene.add(dir);

  orbit = new OrbitCamera(camera, canvas);
  window.addEventListener("resize", resize);
  resize();

  const loop = () => {
    orbit.update();
    renderer.render(scene, camera);
    requestAnimationFrame(loop);
  };
  loop();
}

function generate() {
  const config = readConfig();
  const rngEtg = rngFromSeed(`${config.seed}-etg`);
  const rngGeo = rngFromSeed(`${config.seed}-geo`);
  const override = loadEtgOverride();
  const etg = override ? normalizeETG(override, config, rngEtg) : createETG(config, rngEtg);
  level = generateLevel(etg, config, rngGeo);
  validateAndRepair(level, { maxGap: 5.2, maxVertical: 3.2 });
  sourceLabel = override ? "imported-etg" : "generated";

  rebuildHDPCG(level, "generated");
  orbit.focusBounds(model.bounds, model.cellSize);
  renderFrame();
  updateBfsOutput();
}

function readConfig() {
  const defaults = {
    seed: "hdpcg-demo",
    length: 9,
    difficulty: 0.55,
    branchChance: 0.7,
    keyLockEnabled: true,
    componentStrategy: "diverse",
    candidatePoolSize: 12,
    selectionTopP: 0.70,
    selectionTemperature: 0.80,
    maxLocalRejects: 24,
    fallbackEnabled: true,
    familyBalanceWindow: 40,
    maxCanonicalRetries: 2,
  };

  const params = new URLSearchParams(window.location.search);
  const seed = (params.get("seed") || defaults.seed).trim();
  const length = clampInt(params.get("length") ?? defaults.length, 4, 16);
  const difficulty = clampFloat(params.get("difficulty") ?? defaults.difficulty, 0.1, 0.95);
  const branchChance = clampFloat(params.get("branchChance") ?? defaults.branchChance, 0, 1);
  const keyLockEnabled = parseBool(params.get("keyLockEnabled"), defaults.keyLockEnabled);
  return {
    seed,
    length,
    difficulty,
    branchChance,
    keyLock: keyLockEnabled,
    componentStrategy: (params.get("componentStrategy") || defaults.componentStrategy).trim(),
    candidatePoolSize: clampInt(params.get("candidatePoolSize") ?? defaults.candidatePoolSize, 1, 48),
    selectionTopP: clampFloat(params.get("selectionTopP") ?? defaults.selectionTopP, 0.05, 1),
    selectionTemperature: clampFloat(params.get("selectionTemperature") ?? defaults.selectionTemperature, 0.05, 4),
    maxLocalRejects: clampInt(params.get("maxLocalRejects") ?? defaults.maxLocalRejects, 1, 120),
    fallbackEnabled: parseBool(params.get("fallbackEnabled"), defaults.fallbackEnabled),
    familyBalanceWindow: clampInt(params.get("familyBalanceWindow") ?? defaults.familyBalanceWindow, 4, 200),
    maxCanonicalRetries: clampInt(params.get("maxCanonicalRetries") ?? defaults.maxCanonicalRetries, 0, 8),
  };
}

function renderFrame() {
  if (!model) {
    if (bfsOutput) bfsOutput.textContent = "BFS: unavailable (model missing)";
    return;
  }
  const timeLimit = getReachabilityTimeLimit();
  const t = clampInt(timeSlider.value, 0, timeLimit);
  const envTime = model.wrapTime(t);
  const phase = clampInt(phaseSlider.value, 0, model.phaseCount - 1);

  clearMeshes();
  drawWalkable(envTime, phase);
  if (showReachableInput.checked) drawReachable(t, phase);
  if (showEnemiesInput.checked) drawEnemies(envTime);
  drawKeys();
  drawLocks(phase);
  drawStartGoal();

  const reachMode = getReachabilityRenderMode();
  const reachableCount = getReachableSet(t, phase, reachMode)?.size || 0;
  const warningSuffix = reachabilityWarning ? ` | warn=${reachabilityWarning}` : "";
  statusOutput.textContent =
    `src=${sourceLabel} | t=${t}/${timeLimit} | env=${envTime}/${model.timeHorizon - 1} | phase=${phase}/${model.phaseCount - 1} | reachable(${reachMode})=${reachableCount}${warningSuffix}`;
}

function drawWalkable(t, phase) {
  const surfaceMap = model.surfaceByTime[t];
  if (!surfaceMap) return;
  const openCells = [];
  const lockedCells = [];
  for (const cell of surfaceMap.values()) {
    const id = cellKey(cell);
    if (model.isLockedCell(id, phase)) {
      lockedCells.push(cell);
    } else {
      openCells.push(cell);
    }
  }
  walkableMesh = buildInstancedMesh(openCells, 0xb9b4a9, 0.75, model.cellSize);
  lockedMesh = buildInstancedMesh(lockedCells, 0x8e44ad, 0.65, model.cellSize);
  if (walkableMesh) scene.add(walkableMesh);
  if (lockedMesh) scene.add(lockedMesh);
}

function drawReachable(t, phase) {
  const reachable = getReachableSet(t, phase, getReachabilityRenderMode());
  if (!reachable || reachable.size === 0) return;
  const cells = Array.from(reachable).map(parseCellKey);
  reachableMesh = buildInstancedMesh(cells, 0x2a7f71, 0.35, model.cellSize, 0.85);
  if (reachableMesh) scene.add(reachableMesh);
}

function drawEnemies(t) {
  const set = model.enemiesByTime[t];
  if (!set || set.size === 0) return;
  const cells = Array.from(set).map(parseCellKey);
  enemyMesh = buildInstancedMesh(cells, 0xc0392b, 0.8, model.cellSize, 0.75);
  if (enemyMesh) scene.add(enemyMesh);
}

function drawKeys() {
  if (!model.keyCells.size) return;
  const cells = [];
  for (const cellId of model.keyCells.keys()) {
    cells.push(parseCellKey(cellId));
  }
  keyMesh = buildInstancedMesh(cells, 0xf1c40f, 0.9, model.cellSize, 0.55);
  if (keyMesh) scene.add(keyMesh);
}

function drawLocks(phase) {
  if (!model.lockCells.size) return;
  const cells = [];
  for (const cellId of model.lockCells.keys()) {
    if (!model.isLockedCell(cellId, phase)) continue;
    cells.push(parseCellKey(cellId));
  }
  lockMesh = buildInstancedMesh(cells, 0x6c3483, 0.4, model.cellSize, 0.9);
  if (lockMesh) scene.add(lockMesh);
}

function drawStartGoal() {
  const start = model.startCell;
  if (start) {
    startMesh = buildInstancedMesh([start], 0x1abc9c, 1.0, model.cellSize, 0.7);
    scene.add(startMesh);
  }
  if (model.goalCell) {
    goalMesh = buildInstancedMesh([model.goalCell], 0x27ae60, 1.0, model.cellSize, 0.7);
    scene.add(goalMesh);
  }
}

function updateBfsOutput() {
  if (!bfsResult) {
    bfsOutput.textContent = "BFS: unavailable";
    return;
  }
  const lines = [];
  const effectiveTime = getReachabilityTimeLimit();
  lines.push(`time horizon: ${model.timeHorizon}`);
  lines.push(`effective time(reachability growth): ${effectiveTime}`);
  lines.push(`last reachable cell time(3D union): ${bfsResult.lastReachableCellTime ?? 0}`);
  lines.push(`last reachable 5D state time: ${bfsResult.lastReachableStateTime ?? 0}`);
  lines.push(`phase count: ${model.phaseCount}`);
  lines.push(`visited states: ${bfsResult.visitedCount}`);
  lines.push(`expanded: ${bfsResult.expanded}`);
  lines.push(`truncated: ${bfsResult.truncated ? "yes" : "no"}`);
  lines.push(`time-boundary hits: ${bfsResult.timeBoundaryHits ?? 0}`);
  lines.push(`time-compressed visit key: ${bfsResult.compressTime ? "yes" : "no"}`);
  lines.push(`walkable tolerance(cells): ${bfsResult.walkableToleranceCells ?? 0}`);
  if (reachabilityWarning) lines.push(`warning: ${reachabilityWarning}`);
  lines.push(`reachability render mode: ${getReachabilityRenderMode()}(current phase)`);
  bfsOutput.textContent = lines.join("\n");
}

function getReachabilityRenderMode() {
  return reachModeInput?.value === "step" ? "step" : "cumulative";
}

function getReachableSet(t, phase, mode) {
  if (mode === "step") {
    return bfsResult?.reachableByTimePhase?.[t]?.[phase] || null;
  }
  return (
    bfsResult?.reachableCumulativeByTimePhase?.[t]?.[phase] ||
    bfsResult?.reachableByTimePhase?.[t]?.[phase] ||
    null
  );
}

function rebuildHDPCG(nextLevel, nextSource = sourceLabel) {
  if (!nextLevel) return;
  level = normalizeLevel(nextLevel);
  latestReport = validateAndRepair(level, { maxGap: 5.2, maxVertical: 3.2 });
  model = buildHDPCGModel(level, { cellSize: 1, timeStep: 1, padding: 4, maxTimeHorizon: 180, maxPeriodTicks: 180 });
  bfsResult = computeReachableWithRetry(model);
  reachabilityWarning = "";
  if (bfsResult?.truncated) {
    reachabilityWarning = "reachable time may be capped by BFS budget";
  } else if ((bfsResult?.timeBoundaryHits ?? 0) > 0) {
    reachabilityWarning = "reachable time may still be capped by maxTime boundary";
  }
  const maxTime = getReachabilityTimeLimit();
  timeSlider.max = Math.max(0, maxTime);
  timeSlider.value = "0";
  phaseSlider.max = Math.max(0, model.phaseCount - 1);
  phaseSlider.value = "0";
  orbit.focusBounds(model.bounds, model.cellSize);
  sourceLabel = nextSource;
}

function getReachabilityTimeLimit() {
  return getReachabilityGrowthTime(bfsResult);
}

function getReachabilityGrowthTime(result) {
  const unionTime = result?.lastReachableCellTime;
  const phaseAwareTime = result?.maxTimeUsed;
  if (Number.isFinite(unionTime) && Number.isFinite(phaseAwareTime)) {
    return Math.max(unionTime, phaseAwareTime);
  }
  return (
    unionTime ??
    phaseAwareTime ??
    result?.maxTime ??
    Math.max(0, (model?.timeHorizon || 1) - 1)
  );
}

function computeReachableWithRetry(nextModel) {
  const maxTimeCap = Math.max(600, nextModel.timeHorizon * (nextModel.phaseCount + 2) * 2);
  const budgetPlan = [
    { maxStates: 120000, maxQueue: 90000, maxJumpOffsets: 900 },
    { maxStates: 260000, maxQueue: 200000, maxJumpOffsets: 1600 },
    { maxStates: 520000, maxQueue: 360000, maxJumpOffsets: 2400 },
    { maxStates: 900000, maxQueue: 700000, maxJumpOffsets: 3200 },
    { maxStates: 1200000, maxQueue: 900000, maxJumpOffsets: 4000 },
  ];

  // Expand the BFS estimate when growth reaches the current boundary.
  let maxTime = null;
  let result = null;

  for (let round = 0; round < 12; round += 1) {
    const budget = budgetPlan[Math.min(round, budgetPlan.length - 1)];
    const bfsOptions = {
      ...budget,
      compressTime: true,
      walkableToleranceCells: 1,
    };
    if (Number.isFinite(maxTime)) {
      bfsOptions.maxTime = maxTime;
    }
    result = computeReachable(nextModel, bfsOptions);

    const currentMaxTime = result?.maxTime ?? (Number.isFinite(maxTime) ? maxTime : 0);
    const boundaryLimited = (result?.timeBoundaryHits ?? 0) > 0;
    if (!result?.truncated && !boundaryLimited) return result;

    if (boundaryLimited && currentMaxTime < maxTimeCap) {
      maxTime = Math.min(maxTimeCap, Math.max(currentMaxTime + 1, Math.floor(currentMaxTime * 1.6)));
    } else if (!Number.isFinite(maxTime) && Number.isFinite(result?.maxTime)) {
      maxTime = result.maxTime;
    }
  }

  return result;
}

function loadFromFile(file) {
  if (!file) return;
  bfsOutput.textContent = "Importing...";
  statusOutput.textContent = "importing...";
  file
    .text()
    .then((raw) => {
      let data = null;
      try {
        data = JSON.parse(raw);
      } catch (err) {
        bfsOutput.textContent = `Import error: ${err.message}`;
        return;
      }
      const parsed = parseImportedData(data);
      if (!parsed) {
        bfsOutput.textContent =
          "Import error: expected ETG (nodes/edges), export package (level), or level JSON.";
        return;
      }
      try {
        rebuildHDPCG(parsed.level, parsed.source);
      } catch (err) {
        bfsOutput.textContent = `Import error: ${err.message}`;
        return;
      }
      renderFrame();
      updateBfsOutput();
    })
    .catch((err) => {
      bfsOutput.textContent = `Import error: ${err.message}`;
    });
}

function parseImportedData(data) {
  if (!data || typeof data !== "object") return null;
  if (data.level && Array.isArray(data.level.platforms)) {
    return { level: data.level, source: "package" };
  }
  if (Array.isArray(data.platforms) && data.start) {
    return { level: data, source: "level" };
  }
  if (data.etg && Array.isArray(data.etg.nodes) && Array.isArray(data.etg.edges)) {
    const config = readConfig();
    const rngEtg = rngFromSeed(`${config.seed}-etg`);
    const rngGeo = rngFromSeed(`${config.seed}-geo`);
    const etg = normalizeETG(data.etg, config, rngEtg);
    return { level: generateLevel(etg, config, rngGeo), source: "etg" };
  }
  if (Array.isArray(data.nodes) && Array.isArray(data.edges)) {
    const config = readConfig();
    const rngEtg = rngFromSeed(`${config.seed}-etg`);
    const rngGeo = rngFromSeed(`${config.seed}-geo`);
    const etg = normalizeETG(data, config, rngEtg);
    return { level: generateLevel(etg, config, rngGeo), source: "etg" };
  }
  return null;
}

function normalizeLevel(data) {
  return {
    ...data,
    platforms: Array.isArray(data.platforms) ? data.platforms : [],
    enemies: Array.isArray(data.enemies) ? data.enemies : [],
    keys: Array.isArray(data.keys) ? data.keys : [],
    locks: Array.isArray(data.locks) ? data.locks : [],
    checkpoints: Array.isArray(data.checkpoints) ? data.checkpoints : [],
    start: data.start || { x: 0, y: 0, z: 0 },
    goal: data.goal || null,
  };
}

function loadEtgOverride() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("etg") !== "1") return null;
  const raw = localStorage.getItem("etg_override");
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (err) {
    return null;
  }
}

function assertCoreElements() {
  const missing = [];
  if (!canvas) missing.push("#viewer-canvas");
  if (!importInput) missing.push("#import-file");
  if (!timeSlider) missing.push("#time-slider");
  if (!phaseSlider) missing.push("#phase-slider");
  if (!showReachableInput) missing.push("#show-reachable");
  if (!reachModeInput) missing.push("#reach-mode");
  if (!showEnemiesInput) missing.push("#show-enemies");
  if (!statusOutput) missing.push("#viewer-status");
  if (!bfsOutput) missing.push("#bfs-output");
  if (missing.length) {
    throw new Error(`Missing DOM elements: ${missing.join(", ")}`);
  }
}

function reportInitError(err) {
  const message = err?.message || String(err);
  if (bfsOutput) bfsOutput.textContent = `Init error: ${message}`;
  if (statusOutput) statusOutput.textContent = "init failed";
}


function buildInstancedMesh(cells, color, opacity, cellSize, scale = 0.85) {
  if (!cells || cells.length === 0) return null;
  const size = cellSize * scale;
  const geometry = new THREE.BoxGeometry(size, size * 0.6, size);
  const material = new THREE.MeshStandardMaterial({
    color,
    transparent: opacity < 1,
    opacity,
  });
  const mesh = new THREE.InstancedMesh(geometry, material, cells.length);
  const matrix = new THREE.Matrix4();
  for (let i = 0; i < cells.length; i += 1) {
    const cell = cells[i];
    matrix.makeTranslation(cell.x * cellSize, cell.y * cellSize, cell.z * cellSize);
    mesh.setMatrixAt(i, matrix);
  }
  mesh.instanceMatrix.needsUpdate = true;
  return mesh;
}

function clearMeshes() {
  const targets = [walkableMesh, lockedMesh, reachableMesh, enemyMesh, keyMesh, lockMesh, startMesh, goalMesh];
  for (const mesh of targets) {
    if (!mesh) continue;
    scene.remove(mesh);
    mesh.geometry.dispose();
    mesh.material.dispose();
  }
  walkableMesh = null;
  lockedMesh = null;
  reachableMesh = null;
  enemyMesh = null;
  keyMesh = null;
  lockMesh = null;
  startMesh = null;
  goalMesh = null;
}

function resize() {
  const { clientWidth, clientHeight } = canvas.parentElement;
  camera.aspect = clientWidth / clientHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(clientWidth, clientHeight, false);
}

function cellKey(cell) {
  return `${cell.x},${cell.y},${cell.z}`;
}

function parseCellKey(key) {
  const [x, y, z] = key.split(",").map((value) => Number(value));
  return { x, y, z };
}

function clampInt(value, min, max) {
  const n = Math.round(Number(value) || min);
  return Math.min(max, Math.max(min, n));
}

function clampFloat(value, min, max) {
  const n = Number(value);
  if (Number.isNaN(n)) return min;
  return Math.min(max, Math.max(min, n));
}

function parseBool(raw, fallback) {
  if (raw === null || raw === undefined || raw === "") return fallback;
  const v = String(raw).trim().toLowerCase();
  if (v === "1" || v === "true" || v === "yes" || v === "y" || v === "on") return true;
  if (v === "0" || v === "false" || v === "no" || v === "n" || v === "off") return false;
  return fallback;
}

class OrbitCamera {
  constructor(camera, canvas) {
    this.camera = camera;
    this.canvas = canvas;
    this.center = new THREE.Vector3(0, 0, 0);
    this.distance = 40;
    this.yaw = Math.PI * 0.25;
    this.pitch = -0.5;
    this.dragging = false;
    this.last = { x: 0, y: 0 };
    this._bind();
  }

  focusBounds(bounds, cellSize) {
    const centerX = (bounds.min.x + bounds.max.x) * 0.5 * cellSize;
    const centerY = (bounds.min.y + bounds.max.y) * 0.5 * cellSize;
    const centerZ = (bounds.min.z + bounds.max.z) * 0.5 * cellSize;
    this.center.set(centerX, centerY, centerZ);
    const spanX = (bounds.max.x - bounds.min.x) * cellSize;
    const spanY = (bounds.max.y - bounds.min.y) * cellSize;
    const spanZ = (bounds.max.z - bounds.min.z) * cellSize;
    this.distance = Math.max(spanX, spanY, spanZ) * 1.2 + 8;
  }

  _bind() {
    this.canvas.addEventListener("mousedown", (event) => {
      this.dragging = true;
      this.last = { x: event.clientX, y: event.clientY };
    });
    window.addEventListener("mouseup", () => {
      this.dragging = false;
    });
    window.addEventListener("mousemove", (event) => {
      if (!this.dragging) return;
      const dx = event.clientX - this.last.x;
      const dy = event.clientY - this.last.y;
      this.last = { x: event.clientX, y: event.clientY };
      this.yaw += dx * 0.005;
      this.pitch -= dy * 0.005;
      this.pitch = clamp(this.pitch, -1.2, -0.1);
    });
    this.canvas.addEventListener("wheel", (event) => {
      const delta = Math.sign(event.deltaY);
      this.distance = clamp(this.distance + delta * 2.2, 8, 200);
    });
  }

  update() {
    const direction = new THREE.Vector3(
      Math.cos(this.pitch) * Math.cos(this.yaw),
      Math.sin(this.pitch),
      Math.cos(this.pitch) * Math.sin(this.yaw)
    );
    const position = this.center.clone().sub(direction.multiplyScalar(this.distance));
    this.camera.position.lerp(position, 0.2);
    this.camera.lookAt(this.center);
  }
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

bootstrap();

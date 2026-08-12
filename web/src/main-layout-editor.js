import * as THREE from "../vendor/three.module.js";
import { Game } from "./game.js?v=10";
import { resolveVisualConfig } from "./visual/theme-manager.js?v=10";
import { createProceduralObstacleCourse } from "./procedural-obstacle-course.js";

const DEFAULT_LEVEL =
  "out/obstacle_course/level.json";

const AXIS = {
  x: new THREE.Vector3(1, 0, 0),
  y: new THREE.Vector3(0, 1, 0),
  z: new THREE.Vector3(0, 0, 1),
};

const COLORS = {
  x: 0xf05b52,
  y: 0x22a95f,
  z: 0x2d7fe8,
  rotate: 0xffc928,
  selected: 0xffffff,
  hover: 0x101722,
};

const canvas = document.querySelector("#game-canvas");
const labelLayer = document.querySelector("#label-layer");
const statusOutput = document.querySelector("#status-output");
const platformSelect = document.querySelector("#platform-select");
const platformFilter = document.querySelector("#platform-filter");
const selectedSummary = document.querySelector("#selected-summary");
const jsonOutput = document.querySelector("#json-output");
const showLabelsInput = document.querySelector("#show-labels");
const syncAssetSizeInput = document.querySelector("#sync-asset-size");
const moveStepInput = document.querySelector("#move-step");
const rotateStepInput = document.querySelector("#rotate-step");
const scaleStepInput = document.querySelector("#scale-step");
const params = new URLSearchParams(window.location.search);

const fields = {
  posX: document.querySelector("#pos-x"),
  posY: document.querySelector("#pos-y"),
  posZ: document.querySelector("#pos-z"),
  yawDeg: document.querySelector("#yaw-deg"),
  sizeX: document.querySelector("#size-x"),
  sizeY: document.querySelector("#size-y"),
  sizeZ: document.querySelector("#size-z"),
  assetX: document.querySelector("#asset-x"),
  assetY: document.querySelector("#asset-y"),
  assetZ: document.querySelector("#asset-z"),
};

const game = new Game(canvas, updateStatus, resolveVisualConfig({
  themeId: params.get("visualTheme") || "manual",
  quality: params.get("visualQuality") || "high",
  postfx: parseBool(params.get("postfx"), true),
  debug: parseBool(params.get("visualDebug"), false),
  renderClean: parseBool(params.get("cleanBackdrop"), true),
}));

const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
const tmpVec = new THREE.Vector3();

let level = null;
let originalById = new Map();
let selectedHelper = null;
let gizmoGroup = null;
let labelGroup = null;
let lastCamera = null;
let labelLoopStarted = false;

const state = {
  selectedId: null,
  transformMode: "move",
  drag: null,
  viewportDrag: null,
  orbit: null,
};

installEditorInputGuards();
load();

async function load() {
  if (!params.get("level")) {
    loadBuiltInCourse();
    return;
  }
  const levelPath = params.get("level") || DEFAULT_LEVEL;
  setStatus(`loading ${levelPath}`);
  try {
    const response = await fetch(cacheBust(levelPath), { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    level = normalizeLevel(extractLevel(await response.json()));
    originalById = new Map(level.platforms.map((platform) => [platform.id, deepClone(platform)]));
    populatePlatformSelect();
    renderLevel();
    selectPlatform(level.platforms[0]?.id);
    game.start();
    startLabelLoop();
    window.__obstacleCourseEditor = {
      game,
      getLevel: () => level,
      selectPlatform,
      setMode,
    };
  } catch (err) {
    setStatus(`error: ${err.message}`);
  }
}

function loadBuiltInCourse() {
  level = normalizeLevel(createProceduralObstacleCourse());
  originalById = new Map(level.platforms.map((platform) => [platform.id, deepClone(platform)]));
  populatePlatformSelect();
  renderLevel();
  selectPlatform(level.platforms[0]?.id);
  game.start();
  startLabelLoop();
  window.__obstacleCourseEditor = { game, getLevel: () => level, selectPlatform, setMode };
  setStatus("loaded built-in procedural course");
}

function renderLevel() {
  game.stop();
  selectedHelper = null;
  gizmoGroup = null;
  labelGroup = null;
  game.loadLevel(level);
  tagPlatformMeshes();

  const camera = lastCamera || chooseCamera(level);
  game.setShowcaseCamera(camera.position, camera.target);
  game.camera.fov = camera.fov;
  game.camera.updateProjectionMatrix();
  lastCamera = camera;
  state.orbit = cameraToOrbit(camera);

  rebuildLabels();
  updateSelectionVisuals();
  game.start();
}

function populatePlatformSelect() {
  const current = state.selectedId || platformSelect.value;
  const query = platformFilter.value.trim().toLowerCase();
  platformSelect.innerHTML = "";

  const entries = level.platforms
    .map((platform, index) => ({ platform, index }))
    .filter(({ platform, index }) => !query || platformSearchText(platform, index).includes(query));

  for (const { platform, index } of entries) {
    const option = document.createElement("option");
    option.value = platform.id;
    option.textContent = `${String(index + 1).padStart(2, "0")}  ${formatPlatformLabel(platform)}  ${platform.id}`;
    platformSelect.append(option);
  }

  const stillVisible = entries.some(({ platform }) => platform.id === current);
  if (stillVisible) platformSelect.value = current;
  else if (entries[0]) platformSelect.value = entries[0].platform.id;
}

function selectPlatform(id, options = {}) {
  if (!id) return;
  const platform = level?.platforms?.find((item) => item.id === id);
  if (!platform) return;

  state.selectedId = id;
  if (![...platformSelect.options].some((option) => option.value === id)) {
    platformFilter.value = "";
    populatePlatformSelect();
  }
  platformSelect.value = id;
  writePlatformToFields(platform);
  updateSelectionVisuals();
  updateJsonOutput();
  updateSelectedSummary(platform);
  setStatus(`selected ${formatPlatformLabel(platform)} tool=${state.transformMode}`);
  if (options.focus) focusSelected();
}

function selectedPlatform() {
  return level?.platforms?.find((platform) => platform.id === state.selectedId);
}

function writePlatformToFields(platform) {
  fields.posX.value = numberText(platform.pos.x);
  fields.posY.value = numberText(platform.pos.y);
  fields.posZ.value = numberText(platform.pos.z);
  fields.yawDeg.value = numberText(radToDeg(platformYaw(platform)));
  fields.sizeX.value = numberText(platform.size?.x);
  fields.sizeY.value = numberText(platform.size?.y);
  fields.sizeZ.value = numberText(platform.size?.z);
  fields.assetX.value = numberText(platform.asset_target_size?.x ?? platform.size?.x);
  fields.assetY.value = numberText(platform.asset_target_size?.y ?? platform.size?.y);
  fields.assetZ.value = numberText(platform.asset_target_size?.z ?? platform.size?.z);
}

function updateSelectedSummary(platform) {
  if (!platform) {
    selectedSummary.textContent = "";
    return;
  }
  selectedSummary.textContent = [
    `label: ${formatPlatformLabel(platform)}`,
    `node: ${platform.node_id || "-"}`,
    `kind: ${platform.kind || "static"}  asset: ${platform.asset_key || "-"}`,
  ].join("\n");
}

function applyFields() {
  const platform = selectedPlatform();
  if (!platform) return;
  platform.pos = {
    x: readField(fields.posX, platform.pos.x),
    y: readField(fields.posY, platform.pos.y),
    z: readField(fields.posZ, platform.pos.z),
  };
  const yaw = degToRad(readField(fields.yawDeg, radToDeg(platformYaw(platform))));
  setPlatformYaw(platform, yaw);
  platform.size = {
    x: Math.max(0.1, readField(fields.sizeX, platform.size?.x || 1)),
    y: Math.max(0.1, readField(fields.sizeY, platform.size?.y || 1)),
    z: Math.max(0.1, readField(fields.sizeZ, platform.size?.z || 1)),
  };
  platform.asset_target_size = {
    ...(platform.asset_target_size || {}),
    x: Math.max(0.1, readField(fields.assetX, platform.asset_target_size?.x ?? platform.size.x)),
    y: Math.max(0.1, readField(fields.assetY, platform.asset_target_size?.y ?? platform.size.y)),
    z: Math.max(0.1, readField(fields.assetZ, platform.asset_target_size?.z ?? platform.size.z)),
  };
  commitPlatformEdit(platform, true, `applied ${platform.id}`);
}

function resetSelected() {
  const platform = selectedPlatform();
  const original = platform ? originalById.get(platform.id) : null;
  if (!platform || !original) return;
  Object.assign(platform, deepClone(original));
  commitPlatformEdit(platform, true, `reset ${platform.id}`);
}

function commitPlatformEdit(platform, reloadScene, message) {
  syncLinkedEntities(platform);
  if (reloadScene) {
    renderLevel();
  } else {
    updateLivePlatformMesh(platform);
    updateSelectionVisuals();
  }
  selectPlatform(platform.id);
  setStatus(message);
}

function syncLinkedEntities(platform) {
  const nodeId = platform.node_id;
  if (!nodeId || String(nodeId).startsWith("edge:")) return;
  const yaw = platformYaw(platform);
  for (const group of [level.sweepers, level.timed_gates, level.bumpers, level.checkpoints]) {
    for (const item of group || []) {
      if (item.node_id !== nodeId) continue;
      item.pos = { ...(item.pos || {}), x: platform.pos.x, z: platform.pos.z };
      if ("yaw" in item || group !== level.checkpoints) {
        item.yaw = yaw;
        item.rotation_y = yaw;
      }
    }
  }
  const anchor = buildAnchor(platform);
  level.anchors[nodeId] = anchor;
  if (level.mapping?.node?.[nodeId]) {
    level.mapping.node[nodeId].entry = anchor.entry;
    level.mapping.node[nodeId].exit = anchor.exit;
  }
  if (nodeId === "FG_START") {
    level.start = { ...anchor.entry };
  }
  if (nodeId === "FG_FINISH" && level.goal) {
    level.goal = { ...level.goal, x: platform.pos.x, z: platform.pos.z };
  }
}

function buildAnchor(platform) {
  const yaw = platformYaw(platform);
  const sizeX = Number(platform.size?.x || 12);
  const ux = Math.cos(yaw);
  const uz = Math.sin(yaw);
  const half = sizeX * 0.38;
  return {
    entry: { x: round(platform.pos.x - ux * half, 4), y: 0, z: round(platform.pos.z - uz * half, 4) },
    exit: { x: round(platform.pos.x + ux * half, 4), y: 0, z: round(platform.pos.z + uz * half, 4) },
    heading: { x: round(ux, 6), z: round(uz, 6) },
  };
}

function updateSelectionVisuals() {
  updateSelectionHelper();
  updateGizmo();
  rebuildLabels();
}

function updateSelectionHelper() {
  const platform = selectedPlatform();
  if (selectedHelper) {
    game.scene.remove(selectedHelper);
    disposeObject(selectedHelper);
    selectedHelper = null;
  }
  if (!platform || !game.scene) return;

  const size = platform.size || { x: 1, y: 1, z: 1 };
  selectedHelper = new THREE.Group();
  selectedHelper.position.set(platform.pos.x, platform.pos.y, platform.pos.z);
  selectedHelper.rotation.y = platformYaw(platform);

  const box = new THREE.Mesh(
    new THREE.BoxGeometry(size.x + 0.34, size.y + 0.42, size.z + 0.34),
    new THREE.MeshBasicMaterial({ color: 0xffffff, wireframe: true, transparent: true, opacity: 0.98 })
  );
  const cap = new THREE.Mesh(
    new THREE.BoxGeometry(size.x + 0.42, 0.08, size.z + 0.42),
    new THREE.MeshBasicMaterial({ color: 0x0b4e7a, transparent: true, opacity: 0.18, depthWrite: false })
  );
  cap.position.y = size.y * 0.5 + 0.12;
  selectedHelper.add(box, cap);
  game.scene.add(selectedHelper);
}

function updateGizmo() {
  const platform = selectedPlatform();
  if (gizmoGroup) {
    game.scene.remove(gizmoGroup);
    disposeObject(gizmoGroup);
    gizmoGroup = null;
  }
  if (!platform || !game.scene) return;

  gizmoGroup = new THREE.Group();
  gizmoGroup.name = "layout-editor-gizmo";
  gizmoGroup.position.set(platform.pos.x, platform.pos.y + Number(platform.size?.y || 1) * 0.5 + 0.45, platform.pos.z);

  if (state.transformMode === "move") {
    gizmoGroup.add(makeArrowHandle("x", AXIS.x, 6.2, { type: "move", axis: "x" }));
    gizmoGroup.add(makeArrowHandle("y", AXIS.y, 4.8, { type: "move", axis: "y" }));
    gizmoGroup.add(makeArrowHandle("z", AXIS.z, 6.2, { type: "move", axis: "z" }));
  } else if (state.transformMode === "rotate") {
    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(6.0, 0.11, 10, 80),
      new THREE.MeshBasicMaterial({ color: COLORS.rotate, transparent: true, opacity: 0.95, depthTest: false })
    );
    ring.rotation.x = Math.PI / 2;
    ring.userData.handle = { type: "rotate", axis: "y" };
    gizmoGroup.add(ring);
  } else if (state.transformMode === "scale") {
    const yaw = platformYaw(platform);
    const localX = new THREE.Vector3(Math.cos(yaw), 0, Math.sin(yaw));
    const localZ = new THREE.Vector3(-Math.sin(yaw), 0, Math.cos(yaw));
    const halfX = Number(platform.size?.x || 1) * 0.5 + 1.5;
    const halfZ = Number(platform.size?.z || 1) * 0.5 + 1.5;
    const halfY = Number(platform.size?.y || 1) * 0.5 + 1.2;
    gizmoGroup.add(makeScaleHandle("x", localX, halfX, { type: "scale", axis: "x", local: true }));
    gizmoGroup.add(makeScaleHandle("z", localZ, halfZ, { type: "scale", axis: "z", local: true }));
    gizmoGroup.add(makeScaleHandle("y", AXIS.y, halfY, { type: "scale", axis: "y", local: false }));
  }

  game.scene.add(gizmoGroup);
}

function makeArrowHandle(axisName, axis, length, handle) {
  const group = new THREE.Group();
  const mat = new THREE.MeshBasicMaterial({ color: COLORS[axisName], depthTest: false });
  const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.07, length, 10), mat);
  const head = new THREE.Mesh(new THREE.ConeGeometry(0.28, 0.78, 16), mat);
  const quat = new THREE.Quaternion().setFromUnitVectors(AXIS.y, axis.clone().normalize());
  shaft.quaternion.copy(quat);
  head.quaternion.copy(quat);
  shaft.position.copy(axis.clone().multiplyScalar(length * 0.5));
  head.position.copy(axis.clone().multiplyScalar(length + 0.38));
  shaft.userData.handle = handle;
  head.userData.handle = handle;
  group.add(shaft, head);
  return group;
}

function makeScaleHandle(axisName, axis, distance, handle) {
  const group = new THREE.Group();
  const mat = new THREE.MeshBasicMaterial({ color: COLORS[axisName], depthTest: false });
  const line = new THREE.Mesh(new THREE.CylinderGeometry(0.055, 0.055, distance, 8), mat);
  const grip = new THREE.Mesh(new THREE.BoxGeometry(0.64, 0.64, 0.64), mat);
  const quat = new THREE.Quaternion().setFromUnitVectors(AXIS.y, axis.clone().normalize());
  line.quaternion.copy(quat);
  line.position.copy(axis.clone().multiplyScalar(distance * 0.5));
  grip.position.copy(axis.clone().multiplyScalar(distance));
  line.userData.handle = handle;
  grip.userData.handle = handle;
  group.add(line, grip);
  return group;
}

function rebuildLabels() {
  labelLayer.innerHTML = "";
  if (!showLabelsInput.checked || !level) return;
  for (const platform of level.platforms) {
    const isSelected = platform.id === state.selectedId;
    const label = document.createElement("div");
    label.className = `scene-label${isSelected ? " is-selected" : ""}`;
    label.dataset.platformId = platform.id;
    label.textContent = formatPlatformLabel(platform);
    labelLayer.append(label);
  }
  updateDomLabelPositions();
}

function startLabelLoop() {
  if (labelLoopStarted) return;
  labelLoopStarted = true;
  const tick = () => {
    updateDomLabelPositions();
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

function updateDomLabelPositions() {
  if (!showLabelsInput.checked || !level || !labelLayer.children.length) return;
  const width = canvas.clientWidth || 1;
  const height = canvas.clientHeight || 1;
  const byId = new Map(level.platforms.map((platform) => [platform.id, platform]));
  for (const label of labelLayer.children) {
    const platform = byId.get(label.dataset.platformId);
    if (!platform) continue;
    const lift = platform.id === state.selectedId ? 4.2 : 2.6;
    tmpVec.set(
      Number(platform.pos?.x || 0),
      Number(platform.pos?.y || 0) + Number(platform.size?.y || 1) * 0.5 + lift,
      Number(platform.pos?.z || 0)
    );
    tmpVec.project(game.camera);
    const visible = tmpVec.z > -1 && tmpVec.z < 1;
    const x = (tmpVec.x * 0.5 + 0.5) * width;
    const y = (-tmpVec.y * 0.5 + 0.5) * height;
    const inBounds = visible && x > -80 && x < width + 80 && y > -40 && y < height + 40;
    label.style.display = inBounds ? "block" : "none";
    if (inBounds) {
      label.style.left = `${round(x, 1)}px`;
      label.style.top = `${round(y, 1)}px`;
    }
  }
}

function tagPlatformMeshes() {
  for (const entry of game.platforms) {
    entry.mesh.userData.platformId = entry.data.id;
    entry.mesh.traverse((child) => {
      child.userData.platformId = entry.data.id;
    });
  }
}

function updateLivePlatformMesh(platform) {
  const entry = game.platforms.find((item) => item.data.id === platform.id);
  if (!entry) return;
  entry.mesh.position.set(platform.pos.x, platform.pos.y, platform.pos.z);
  entry.mesh.rotation.y = platformYaw(platform);
}

function updateJsonOutput() {
  if (!level) return;
  jsonOutput.value = JSON.stringify(level, null, 2);
}

async function copyJson() {
  updateJsonOutput();
  await navigator.clipboard.writeText(jsonOutput.value);
  setStatus("copied JSON to clipboard");
}

function downloadJson() {
  updateJsonOutput();
  const blob = new Blob([jsonOutput.value], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "obstacle_course_level_edited.json";
  link.click();
  URL.revokeObjectURL(url);
}

function installEditorInputGuards() {
  canvas.addEventListener("contextmenu", (event) => event.preventDefault());
  canvas.addEventListener("click", blockGameMouseEvent, true);
  canvas.addEventListener("mousedown", blockGameMouseEvent, true);
  canvas.addEventListener("pointerdown", onPointerDown, true);
  window.addEventListener("pointermove", onPointerMove, true);
  window.addEventListener("pointerup", onPointerUp, true);
  canvas.addEventListener("wheel", onWheel, { passive: false });
  window.addEventListener("keydown", onKeyDown);
}

function blockGameMouseEvent(event) {
  event.preventDefault();
  event.stopPropagation();
}

function onPointerDown(event) {
  if (!level) return;
  if (event.target !== canvas) return;
  event.preventDefault();
  event.stopPropagation();
  canvas.setPointerCapture?.(event.pointerId);

  if (event.button === 2 || event.button === 1) {
    state.viewportDrag = {
      type: event.button === 1 || event.shiftKey ? "pan" : "orbit",
      startX: event.clientX,
      startY: event.clientY,
      orbit: deepCloneOrbit(state.orbit),
    };
    return;
  }

  const handle = hitTestGizmo(event);
  if (handle) {
    beginTransformDrag(event, handle);
    return;
  }

  const platform = hitTestPlatform(event);
  if (platform) {
    selectPlatform(platform.id);
    setStatus(`selected ${formatPlatformLabel(platform)}`);
  }
}

function onPointerMove(event) {
  if (state.drag) {
    event.preventDefault();
    updateTransformDrag(event);
    return;
  }
  if (state.viewportDrag) {
    event.preventDefault();
    updateViewportDrag(event);
  }
}

function onPointerUp(event) {
  if (state.drag) {
    const id = state.drag.platformId;
    state.drag = null;
    const platform = level.platforms.find((item) => item.id === id);
    if (platform) commitPlatformEdit(platform, true, `edited ${formatPlatformLabel(platform)}`);
  }
  state.viewportDrag = null;
  canvas.releasePointerCapture?.(event.pointerId);
}

function onWheel(event) {
  if (!state.orbit) return;
  event.preventDefault();
  const factor = Math.exp(event.deltaY * 0.0012);
  state.orbit.distance = clamp(state.orbit.distance * factor, 16, 280);
  applyOrbitCamera();
}

function hitTestGizmo(event) {
  if (!gizmoGroup) return null;
  const objects = [];
  gizmoGroup.traverse((child) => {
    if (child.userData.handle) objects.push(child);
  });
  setPointerFromEvent(event);
  raycaster.setFromCamera(pointer, game.camera);
  const hit = raycaster.intersectObjects(objects, false)[0];
  return hit?.object?.userData?.handle || null;
}

function hitTestPlatform(event) {
  const objects = game.platforms.map((entry) => entry.mesh);
  setPointerFromEvent(event);
  raycaster.setFromCamera(pointer, game.camera);
  const hit = raycaster.intersectObjects(objects, true)[0];
  if (!hit) return null;
  const platformId = platformIdFromObject(hit.object);
  return level.platforms.find((platform) => platform.id === platformId) || null;
}

function beginTransformDrag(event, handle) {
  const platform = selectedPlatform();
  if (!platform) return;
  const center = platformCenter(platform);
  const start = deepClone(platform);
  const drag = {
    handle,
    platformId: platform.id,
    center,
    start,
    startYaw: platformYaw(platform),
    startSize: { ...(platform.size || {}) },
  };

  if (handle.type === "rotate") {
    const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(AXIS.y, center);
    const point = rayToPlane(event, plane);
    if (!point) return;
    drag.plane = plane;
    drag.startAngle = Math.atan2(point.z - center.z, point.x - center.x);
  } else {
    const axis = handle.type === "scale" ? scaleAxisWorld(handle.axis, platform) : AXIS[handle.axis].clone();
    const plane = axisDragPlane(axis, center);
    const point = rayToPlane(event, plane);
    if (!point) return;
    drag.axis = axis;
    drag.plane = plane;
    drag.startPoint = point;
  }

  state.drag = drag;
}

function updateTransformDrag(event) {
  const drag = state.drag;
  const platform = level.platforms.find((item) => item.id === drag.platformId);
  if (!platform) return;

  if (drag.handle.type === "move") {
    const point = rayToPlane(event, drag.plane);
    if (!point) return;
    const delta = point.clone().sub(drag.startPoint).dot(drag.axis);
    platform.pos = {
      x: round(Number(drag.start.pos.x || 0) + drag.axis.x * delta, 4),
      y: round(Number(drag.start.pos.y || 0) + drag.axis.y * delta, 4),
      z: round(Number(drag.start.pos.z || 0) + drag.axis.z * delta, 4),
    };
  } else if (drag.handle.type === "rotate") {
    const point = rayToPlane(event, drag.plane);
    if (!point) return;
    const angle = Math.atan2(point.z - drag.center.z, point.x - drag.center.x);
    setPlatformYaw(platform, round(drag.startYaw + angle - drag.startAngle, 6));
  } else if (drag.handle.type === "scale") {
    const point = rayToPlane(event, drag.plane);
    if (!point) return;
    const delta = point.clone().sub(drag.startPoint).dot(drag.axis);
    const axis = drag.handle.axis;
    const nextSize = { ...drag.startSize };
    nextSize[axis] = round(Math.max(0.5, Number(drag.startSize[axis] || 1) + delta * 2), 4);
    platform.size = { ...(platform.size || {}), ...nextSize };
    if (syncAssetSizeInput.checked) {
      platform.asset_target_size = { ...(platform.asset_target_size || platform.size), ...nextSize };
    }
  }

  syncLinkedEntities(platform);
  updateLivePlatformMesh(platform);
  writePlatformToFields(platform);
  updateSelectionVisuals();
  updateJsonOutput();
}

function updateViewportDrag(event) {
  const drag = state.viewportDrag;
  if (!drag || !state.orbit) return;
  const dx = event.clientX - drag.startX;
  const dy = event.clientY - drag.startY;
  state.orbit = deepCloneOrbit(drag.orbit);

  if (drag.type === "orbit") {
    state.orbit.azimuth -= dx * 0.006;
    state.orbit.elevation = clamp(state.orbit.elevation + dy * 0.0045, 0.12, 1.34);
  } else {
    const scale = state.orbit.distance * 0.0017;
    const right = new THREE.Vector3(Math.sin(state.orbit.azimuth), 0, -Math.cos(state.orbit.azimuth));
    const forward = new THREE.Vector3(Math.cos(state.orbit.azimuth), 0, Math.sin(state.orbit.azimuth));
    state.orbit.target.x += (-right.x * dx + forward.x * dy) * scale;
    state.orbit.target.z += (-right.z * dx + forward.z * dy) * scale;
  }
  applyOrbitCamera();
}

function applyOrbitCamera() {
  const orbit = state.orbit;
  const horizontal = orbit.distance * Math.cos(orbit.elevation);
  const position = {
    x: orbit.target.x + horizontal * Math.cos(orbit.azimuth),
    y: orbit.target.y + orbit.distance * Math.sin(orbit.elevation),
    z: orbit.target.z + horizontal * Math.sin(orbit.azimuth),
  };
  const target = { x: orbit.target.x, y: orbit.target.y, z: orbit.target.z };
  game.setShowcaseCamera(position, target);
  lastCamera = { position, target, fov: game.camera.fov };
}

function focusSelected() {
  const platform = selectedPlatform();
  if (!platform) return;
  const center = platformCenter(platform);
  const current = state.orbit || cameraToOrbit(lastCamera || chooseCamera(level));
  state.orbit = {
    target: { x: center.x, y: center.y + 1.0, z: center.z },
    distance: clamp(current.distance, 32, 160),
    azimuth: current.azimuth,
    elevation: current.elevation,
  };
  applyOrbitCamera();
  setStatus(`focused ${formatPlatformLabel(platform)}`);
}

function onKeyDown(event) {
  if (!level || isTextInput(event.target)) return;
  const key = event.key.toLowerCase();
  if (key === "w") return setMode("move");
  if (key === "e") return setMode("rotate");
  if (key === "r") return setMode("scale");
  if (event.repeat) return;

  const factor = event.shiftKey ? 4 : event.altKey ? 0.2 : 1;
  if (event.key === "ArrowLeft") return nudgeSelected("x", -1, moveStep() * factor, true, event);
  if (event.key === "ArrowRight") return nudgeSelected("x", 1, moveStep() * factor, true, event);
  if (event.key === "ArrowUp") return nudgeSelected("z", -1, moveStep() * factor, true, event);
  if (event.key === "ArrowDown") return nudgeSelected("z", 1, moveStep() * factor, true, event);
  if (event.key === "PageUp") return nudgeSelected("y", 1, moveStep() * factor, true, event);
  if (event.key === "PageDown") return nudgeSelected("y", -1, moveStep() * factor, true, event);
  if (event.key === "[") return rotateSelected(-1, rotateStep() * factor, true, event);
  if (event.key === "]") return rotateSelected(1, rotateStep() * factor, true, event);
}

function setMode(mode) {
  state.transformMode = mode;
  for (const button of document.querySelectorAll("[data-transform-mode]")) {
    button.classList.toggle("is-active", button.dataset.transformMode === mode);
  }
  updateGizmo();
  setStatus(`tool=${mode}`);
}

function nudgeSelected(axis, direction, amount, reloadScene = true, event = null) {
  event?.preventDefault();
  const platform = selectedPlatform();
  if (!platform) return;
  platform.pos = {
    ...platform.pos,
    [axis]: round(Number(platform.pos?.[axis] || 0) + direction * amount, 4),
  };
  commitPlatformEdit(platform, reloadScene, `moved ${formatPlatformLabel(platform)}`);
}

function rotateSelected(direction, amountDeg, reloadScene = true, event = null) {
  event?.preventDefault();
  const platform = selectedPlatform();
  if (!platform) return;
  setPlatformYaw(platform, round(platformYaw(platform) + degToRad(direction * amountDeg), 6));
  commitPlatformEdit(platform, reloadScene, `rotated ${formatPlatformLabel(platform)}`);
}

function scaleSelected(axis, direction) {
  const platform = selectedPlatform();
  if (!platform) return;
  const amount = scaleStep();
  platform.size = {
    ...(platform.size || {}),
    [axis]: round(Math.max(0.5, Number(platform.size?.[axis] || 1) + direction * amount), 4),
  };
  if (syncAssetSizeInput.checked) {
    platform.asset_target_size = { ...(platform.asset_target_size || platform.size), ...platform.size };
  }
  commitPlatformEdit(platform, true, `scaled ${formatPlatformLabel(platform)}`);
}

function platformIdFromObject(object) {
  let node = object;
  while (node) {
    if (node.userData?.platformId) return node.userData.platformId;
    node = node.parent;
  }
  return null;
}

function setPointerFromEvent(event) {
  const rect = canvas.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
}

function rayToPlane(event, plane) {
  setPointerFromEvent(event);
  raycaster.setFromCamera(pointer, game.camera);
  const hit = new THREE.Vector3();
  return raycaster.ray.intersectPlane(plane, hit) ? hit : null;
}

function axisDragPlane(axis, origin) {
  const cameraDir = game.camera.getWorldDirection(tmpVec).normalize();
  let normal = new THREE.Vector3().crossVectors(axis, cameraDir).cross(axis);
  if (normal.lengthSq() < 0.0001) {
    normal = Math.abs(axis.y) > 0.5 ? AXIS.x.clone() : AXIS.y.clone();
  }
  normal.normalize();
  return new THREE.Plane().setFromNormalAndCoplanarPoint(normal, origin);
}

function scaleAxisWorld(axis, platform) {
  const yaw = platformYaw(platform);
  if (axis === "x") return new THREE.Vector3(Math.cos(yaw), 0, Math.sin(yaw));
  if (axis === "z") return new THREE.Vector3(-Math.sin(yaw), 0, Math.cos(yaw));
  return AXIS.y.clone();
}

function platformCenter(platform) {
  return new THREE.Vector3(
    Number(platform.pos?.x || 0),
    Number(platform.pos?.y || 0),
    Number(platform.pos?.z || 0)
  );
}

function cameraToOrbit(camera) {
  const target = camera.target || { x: 0, y: 0, z: 0 };
  const position = camera.position || { x: 0, y: 80, z: 80 };
  const dx = position.x - target.x;
  const dy = position.y - target.y;
  const dz = position.z - target.z;
  const distance = Math.max(1, Math.hypot(dx, dy, dz));
  return {
    target: { x: target.x, y: target.y, z: target.z },
    distance,
    azimuth: Math.atan2(dz, dx),
    elevation: Math.asin(clamp(dy / distance, -0.98, 0.98)),
  };
}

function deepCloneOrbit(orbit) {
  return {
    target: { ...orbit.target },
    distance: orbit.distance,
    azimuth: orbit.azimuth,
    elevation: orbit.elevation,
  };
}

function chooseCamera(currentLevel) {
  const xs = [];
  const zs = [];
  for (const platform of currentLevel.platforms || []) {
    xs.push(Number(platform.pos?.x || 0));
    zs.push(Number(platform.pos?.z || 0));
  }
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minZ = Math.min(...zs);
  const maxZ = Math.max(...zs);
  const center = { x: (minX + maxX) * 0.5, z: (minZ + maxZ) * 0.5 };
  const extent = Math.max(1, maxX - minX, maxZ - minZ);
  return {
    position: { x: center.x, y: Math.max(70, extent * 0.56), z: center.z + Math.max(110, extent * 0.48) },
    target: { x: center.x, y: 0.8, z: center.z },
    fov: 66,
  };
}

function formatPlatformLabel(platform) {
  if (platform.node_id && !String(platform.node_id).startsWith("edge:")) return platform.node_id;
  if (String(platform.node_id || "").startsWith("edge:")) {
    const edgeId = String(platform.node_id).slice(5);
    const idx = platform.edge_segment_index ?? platform.segment_index;
    return idx == null ? edgeId : `${edgeId}.${idx}`;
  }
  return platform.id;
}

function platformSearchText(platform, index) {
  return `${index + 1} ${platform.id} ${platform.node_id || ""} ${platform.asset_key || ""} ${formatPlatformLabel(platform)}`.toLowerCase();
}

function platformYaw(platform) {
  return Number(platform.yaw ?? platform.rotation_y ?? 0);
}

function setPlatformYaw(platform, yaw) {
  platform.yaw = round(yaw, 6);
  platform.rotation_y = round(yaw, 6);
}

function updateStatus(stateValue) {
  if (state.drag) return;
  const pos = stateValue.position || { x: 0, y: 0, z: 0 };
  const selected = selectedPlatform();
  const suffix = selected ? ` selected=${formatPlatformLabel(selected)}` : "";
  setStatus(`mode=${stateValue.viewMode} tool=${state.transformMode} pos=(${pos.x.toFixed(1)}, ${pos.y.toFixed(1)}, ${pos.z.toFixed(1)})${suffix}`);
}

function setStatus(text) {
  statusOutput.textContent = text;
}

function extractLevel(payload) {
  if (payload?.level?.platforms) {
    return {
      ...payload.level,
      etg: payload.etg || payload.level.etg,
      mapping: payload.mapping || payload.level.mapping,
      anchors: payload.anchors || payload.level.anchors,
      meta: payload.meta || payload.level.meta,
    };
  }
  return payload;
}

function normalizeLevel(raw) {
  const out = raw && typeof raw === "object" ? deepClone(raw) : {};
  for (const key of ["platforms", "enemies", "sweepers", "timed_gates", "bumpers", "showcase_characters", "keys", "locks", "checkpoints"]) {
    out[key] = Array.isArray(out[key]) ? out[key] : [];
  }
  out.mapping = out.mapping && typeof out.mapping === "object" ? out.mapping : { node: {}, edge: {} };
  out.anchors = out.anchors && typeof out.anchors === "object" ? out.anchors : {};
  out.meta = out.meta && typeof out.meta === "object" ? out.meta : {};
  return out;
}

function cacheBust(path) {
  const sep = String(path).includes("?") ? "&" : "?";
  return `${path}${sep}v=${Date.now()}`;
}

function readField(input, fallback) {
  const value = Number(input.value);
  return Number.isFinite(value) ? value : Number(fallback || 0);
}

function moveStep() {
  return Math.max(0.01, readField(moveStepInput, 0.5));
}

function rotateStep() {
  return Math.max(0.1, readField(rotateStepInput, 5));
}

function scaleStep() {
  return Math.max(0.01, readField(scaleStepInput, 0.5));
}

function numberText(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) ? String(round(number, 4)) : "0";
}

function round(value, digits) {
  const scale = 10 ** digits;
  return Math.round(Number(value || 0) * scale) / scale;
}

function degToRad(value) {
  return (Number(value || 0) * Math.PI) / 180;
}

function radToDeg(value) {
  return (Number(value || 0) * 180) / Math.PI;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function parseBool(value, fallback) {
  if (value == null) return fallback;
  return ["1", "true", "yes", "on"].includes(String(value).toLowerCase());
}

function isTextInput(target) {
  return ["INPUT", "TEXTAREA", "SELECT"].includes(target?.tagName);
}

function disposeObject(object) {
  object.traverse((child) => {
    if (child.geometry) child.geometry.dispose();
    const materials = Array.isArray(child.material) ? child.material : child.material ? [child.material] : [];
    for (const material of materials) {
      for (const key of Object.keys(material)) {
        const value = material[key];
        if (value && typeof value.dispose === "function" && value.isTexture) value.dispose();
      }
      material.dispose?.();
    }
  });
}

platformSelect.addEventListener("change", () => selectPlatform(platformSelect.value));
platformFilter.addEventListener("input", () => {
  populatePlatformSelect();
  selectPlatform(platformSelect.value);
});
showLabelsInput.addEventListener("change", rebuildLabels);
document.querySelector("#apply-button").addEventListener("click", applyFields);
document.querySelector("#reset-button").addEventListener("click", resetSelected);
document.querySelector("#copy-button").addEventListener("click", copyJson);
document.querySelector("#download-button").addEventListener("click", downloadJson);
document.querySelector("#focus-selected-button").addEventListener("click", focusSelected);

for (const button of document.querySelectorAll("[data-transform-mode]")) {
  button.addEventListener("click", () => setMode(button.dataset.transformMode));
}
for (const button of document.querySelectorAll("[data-nudge]")) {
  button.addEventListener("click", () => {
    const [axis, direction] = button.dataset.nudge.split(":");
    nudgeSelected(axis, Number(direction), moveStep(), true);
  });
}
for (const button of document.querySelectorAll("[data-rotate]")) {
  button.addEventListener("click", () => rotateSelected(Number(button.dataset.rotate), rotateStep(), true));
}
for (const button of document.querySelectorAll("[data-scale]")) {
  button.addEventListener("click", () => {
    const [axis, direction] = button.dataset.scale.split(":");
    scaleSelected(axis, Number(direction));
  });
}

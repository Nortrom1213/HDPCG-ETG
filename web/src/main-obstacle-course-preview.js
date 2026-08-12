import { Game } from "./game.js?v=10";
import { resolveVisualConfig } from "./visual/theme-manager.js?v=10";
import { createProceduralObstacleCourse } from "./procedural-obstacle-course.js";

const DEFAULT_LEVEL =
  "out/obstacle_course/level.json";

const canvas = document.querySelector("#game-canvas");
const loadOutput = document.querySelector("#load-output");
const statusOutput = document.querySelector("#status-output");
const resetButton = document.querySelector("#reset-player");
const toggleViewModeButton = document.querySelector("#toggle-view-mode");
const qualitySelect = document.querySelector("#quality-select");
const params = new URLSearchParams(window.location.search);

const game = new Game(canvas, updateStatus, resolveVisualConfig({
  themeId: params.get("visualTheme") || "manual",
  quality: params.get("visualQuality") || "high",
  postfx: parseBool(params.get("postfx"), true),
  debug: parseBool(params.get("visualDebug"), false),
  renderClean: false,
}));
window.__obstacleCoursePreviewGame = game;
window.__obstacleCoursePreviewReady = false;
window.__obstacleCoursePreviewError = null;

if (qualitySelect) qualitySelect.value = game.visualConfig.quality;

load();

async function load() {
  if (!params.get("level")) {
    loadBuiltInCourse();
    return;
  }
  const levelPath = params.get("level") || DEFAULT_LEVEL;
  setLoadText(`loading ${levelPath}`);
  try {
    const response = await fetch(cacheBust(levelPath), { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    const level = normalizeLevel(extractLevel(payload));
    if (!parseBool(params.get("showcase"), false)) {
      level.showcase_characters = [];
    }
    level.meta = { ...(level.meta || {}), visual_theme: params.get("visualTheme") || "manual" };
    const previewSpawn = applyPreviewSpawn(level);

    game.stop();
    game.loadLevel(level);
    game.setThirdPersonCamera({
      distance: readNumber(params.get("cameraDistance"), 10.0),
      pitch: readNumber(params.get("cameraPitch"), -0.46),
      yaw: readNumber(params.get("cameraYaw"), previewSpawn.yaw),
      targetYOffset: readNumber(params.get("cameraTargetYOffset"), 0.9),
    });
    game.start();
    window.__obstacleCoursePreviewReady = true;
    window.__obstacleCoursePreviewError = null;
    updateViewButton();
    setLoadText(`loaded ${level.meta?.generator_mode || "obstacle_course"}${previewSpawn.label}`);
  } catch (err) {
    window.__obstacleCoursePreviewReady = false;
    window.__obstacleCoursePreviewError = err.message;
    setLoadText(`error: ${err.message}`);
  }
}

function loadBuiltInCourse() {
  const level = normalizeLevel(createProceduralObstacleCourse());
  const previewSpawn = applyPreviewSpawn(level);
  game.stop();
  game.loadLevel(level);
  game.setThirdPersonCamera({ distance: 10, pitch: -0.46, yaw: previewSpawn.yaw, targetYOffset: 0.9 });
  game.start();
  window.__obstacleCoursePreviewReady = true;
  window.__obstacleCoursePreviewError = null;
  updateViewButton();
  setLoadText("loaded built-in procedural course");
}

function cacheBust(path) {
  const sep = String(path).includes("?") ? "&" : "?";
  return `${path}${sep}v=${Date.now()}`;
}

function updateStatus(state) {
  const pos = state.position || { x: 0, y: 0, z: 0 };
  const mode = state.viewMode === "god" ? "god" : "player";
  statusOutput.textContent =
    `mode=${mode} goal=${state.goalReached ? "reached" : "not yet"} ` +
    `pos=(${pos.x.toFixed(1)}, ${pos.y.toFixed(1)}, ${pos.z.toFixed(1)})`;
}

function setLoadText(text) {
  if (loadOutput) loadOutput.textContent = text;
}

function updateViewButton() {
  if (!toggleViewModeButton) return;
  toggleViewModeButton.textContent = game.getViewMode() === "god" ? "Player View" : "God View";
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
  const level = raw && typeof raw === "object" ? { ...raw } : {};
  for (const key of [
    "platforms",
    "enemies",
    "sweepers",
    "timed_gates",
    "bumpers",
    "showcase_characters",
    "keys",
    "locks",
    "checkpoints",
  ]) {
    level[key] = Array.isArray(level[key]) ? level[key] : [];
  }
  level.start = normalizePos(level.start);
  level.goal = level.goal ? normalizePos(level.goal) : null;
  level.mapping = level.mapping && typeof level.mapping === "object" ? level.mapping : { node: {}, edge: {} };
  level.anchors = level.anchors && typeof level.anchors === "object" ? level.anchors : {};
  level.meta = level.meta && typeof level.meta === "object" ? level.meta : {};
  return level;
}

function normalizePos(pos) {
  const p = pos && typeof pos === "object" ? pos : {};
  return { ...p, x: Number(p.x) || 0, y: Number(p.y) || 0, z: Number(p.z) || 0 };
}

function applyPreviewSpawn(level) {
  if (params.get("previewStart") === "original") {
    return { yaw: 0, label: "" };
  }
  const nodeId = params.get("previewStartNode") || "FG_RUNUP";
  const anchor = level.anchors?.[nodeId];
  if (!anchor) return { yaw: 0, label: "" };
  const pos = anchor.exit || anchor.entry;
  const heading = anchor.heading || { x: 1, z: 0 };
  if (!pos) return { yaw: 0, label: "" };
  level.start = {
    ...level.start,
    x: Number(pos.x) || 0,
    y: Number(pos.y) || 0,
    z: Number(pos.z) || 0,
  };
  level.meta.preview_spawn = nodeId;
  return {
    yaw: Math.atan2(Number(heading.z) || 0, Number(heading.x) || 1),
    label: ` preview=${nodeId}`,
  };
}

function readNumber(raw, fallback) {
  if (raw === null || raw === undefined || raw === "") return fallback;
  const n = Number(raw);
  return Number.isFinite(n) ? n : fallback;
}

function parseBool(raw, fallback) {
  if (raw === null || raw === undefined || raw === "") return fallback;
  const v = String(raw).trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(v)) return true;
  if (["0", "false", "no", "off"].includes(v)) return false;
  return fallback;
}

resetButton?.addEventListener("click", () => {
  game.respawnPlayer();
});

toggleViewModeButton?.addEventListener("click", () => {
  game.toggleViewMode();
  updateViewButton();
});

qualitySelect?.addEventListener("change", () => {
  game.setVisualOptions({
    themeId: "manual",
    quality: qualitySelect.value,
    postfx: game.visualConfig.postfx,
    debug: game.visualConfig.debug,
  });
  game.reloadVisuals(game.level);
});

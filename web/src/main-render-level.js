import { Game } from "./game.js?v=10";
import { resolveVisualConfig } from "./visual/theme-manager.js?v=10";

const DEFAULT_LEVEL =
  "out/obstacle_course/level.json";

const canvas = document.querySelector("#game-canvas");
const statusOutput = document.querySelector("#status-output");
const params = new URLSearchParams(window.location.search);

const game = new Game(canvas, updateStatus, resolveVisualConfig({
  themeId: params.get("visualTheme") || params.get("theme") || "manual",
  quality: params.get("visualQuality") || "high",
  postfx: parseBool(params.get("postfx"), true),
  debug: parseBool(params.get("visualDebug"), false),
  renderClean: parseBool(params.get("cleanBackdrop"), true),
}));

window.__fallGuysRenderReady = false;
window.__fallGuysRenderError = null;
window.__fallGuysRenderGame = game;

load();

async function load() {
  const levelPath = params.get("level") || DEFAULT_LEVEL;
  try {
    const response = await fetch(cacheBust(levelPath), { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    const level = extractLevel(payload);
    if (!parseBool(params.get("showcase"), false)) {
      level.showcase_characters = [];
    }
    game.loadLevel(level);
    const camera = chooseCamera(level);
    game.setShowcaseCamera(camera.position, camera.target);
    if (camera.fov) {
      game.camera.fov = camera.fov;
      game.camera.updateProjectionMatrix();
    }
    game.start();
    window.__fallGuysRenderLevel = level;
    window.__fallGuysRenderCamera = camera;
    window.__fallGuysRenderReady = true;
    statusOutput.textContent = `loaded ${level.meta?.generator_mode || "level"}`;
  } catch (err) {
    setError(err.message);
  }
}

function cacheBust(path) {
  const sep = String(path).includes("?") ? "&" : "?";
  return `${path}${sep}v=${Date.now()}`;
}

function updateStatus(state) {
  statusOutput.textContent = `mode=${state.viewMode} goal=${state.goalReached ? "reached" : "not yet"}`;
}

function setError(message) {
  window.__fallGuysRenderError = message;
  statusOutput.textContent = `error: ${message}`;
}

function extractLevel(payload) {
  if (payload?.level?.platforms) {
    return normalizeLevel({
      ...payload.level,
      etg: payload.etg || payload.level.etg,
      mapping: payload.mapping || payload.level.mapping,
      anchors: payload.anchors || payload.level.anchors,
      meta: payload.meta || payload.level.meta,
    });
  }
  return normalizeLevel(payload);
}

function normalizeLevel(raw) {
  const level = raw && typeof raw === "object" ? { ...raw } : {};
  for (const key of ["platforms", "enemies", "sweepers", "timed_gates", "bumpers", "showcase_characters", "keys", "locks", "checkpoints"]) {
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
  return { x: Number(p.x) || 0, y: Number(p.y) || 0, z: Number(p.z) || 0 };
}

function chooseCamera(level) {
  const bounds = computeBounds(level);
  const center = {
    x: (bounds.min.x + bounds.max.x) * 0.5,
    y: (bounds.min.y + bounds.max.y) * 0.5,
    z: (bounds.min.z + bounds.max.z) * 0.5,
  };
  const size = {
    x: Math.max(1, bounds.max.x - bounds.min.x),
    y: Math.max(1, bounds.max.y - bounds.min.y),
    z: Math.max(1, bounds.max.z - bounds.min.z),
  };
  const extent = Math.max(size.x, size.z);
  const yawSign = String(level.meta?.generator_mode || "").includes("random") ? -1 : 1;
  const camera = {
    position: {
      x: center.x,
      y: Math.max(64, extent * 0.54),
      z: center.z + yawSign * Math.max(96, extent * 0.44),
    },
    target: {
      x: center.x,
      y: 0.8,
      z: center.z,
    },
    fov: 70,
    bounds,
  };
  const customPosition = readVectorParams("cam", camera.position);
  const customTarget = readVectorParams("target", camera.target);
  if (customPosition) camera.position = customPosition;
  if (customTarget) camera.target = customTarget;
  const fov = readNumber(params.get("fov"), camera.fov);
  if (Number.isFinite(fov)) camera.fov = Math.max(18, Math.min(90, fov));
  return camera;
}

function readVectorParams(prefix, fallback) {
  const x = params.get(`${prefix}X`);
  const y = params.get(`${prefix}Y`);
  const z = params.get(`${prefix}Z`);
  if (x === null && y === null && z === null) return null;
  return {
    x: readNumber(x, fallback.x),
    y: readNumber(y, fallback.y),
    z: readNumber(z, fallback.z),
  };
}

function readNumber(value, fallback) {
  if (value === null || value === undefined || value === "") return fallback;
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function computeBounds(level) {
  const bounds = {
    min: { x: Infinity, y: Infinity, z: Infinity },
    max: { x: -Infinity, y: -Infinity, z: -Infinity },
  };
  for (const platform of level.platforms || []) {
    const pos = platform.pos || {};
    const size = platform.size || {};
    expand(bounds, Number(pos.x) - Number(size.x) * 0.5, Number(pos.y) - Number(size.y) * 0.5, Number(pos.z) - Number(size.z) * 0.5);
    expand(bounds, Number(pos.x) + Number(size.x) * 0.5, Number(pos.y) + Number(size.y) * 0.5, Number(pos.z) + Number(size.z) * 0.5);
  }
  for (const item of [...(level.sweepers || []), ...(level.timed_gates || []), ...(level.bumpers || []), ...(level.showcase_characters || [])]) {
    const pos = item.pos || {};
    const r = Number(item.radius || item.barLength || 4);
    expand(bounds, Number(pos.x) - r, Number(pos.y) - r, Number(pos.z) - r);
    expand(bounds, Number(pos.x) + r, Number(pos.y) + r, Number(pos.z) + r);
  }
  if (!Number.isFinite(bounds.min.x)) {
    expand(bounds, -10, -1, -10);
    expand(bounds, 10, 5, 10);
  }
  return bounds;
}

function expand(bounds, x, y, z) {
  bounds.min.x = Math.min(bounds.min.x, x);
  bounds.min.y = Math.min(bounds.min.y, y);
  bounds.min.z = Math.min(bounds.min.z, z);
  bounds.max.x = Math.max(bounds.max.x, x);
  bounds.max.y = Math.max(bounds.max.y, y);
  bounds.max.z = Math.max(bounds.max.z, z);
}

function parseBool(raw, fallback) {
  if (raw === null || raw === undefined || raw === "") return fallback;
  const v = String(raw).trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(v)) return true;
  if (["0", "false", "no", "off"].includes(v)) return false;
  return fallback;
}

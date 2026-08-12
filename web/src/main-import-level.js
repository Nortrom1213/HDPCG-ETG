import { summarizeETG } from "./etg.js";
import { validateAndRepair } from "./validator.js";
import { buildExportPackage } from "./exporter.js";
import { Game } from "./game.js";
import { loadPaperConfig } from "./paper-config.js";
import { listVisualThemes, resolveVisualConfig } from "./visual/theme-manager.js";

const paperConfig = await loadPaperConfig();

const canvas = document.querySelector("#game-canvas");
const etgOutput = document.querySelector("#etg-output");
const reportOutput = document.querySelector("#report-output");
const statusOutput = document.querySelector("#status-output");
const importStatusOutput = document.querySelector("#import-status-output");

const importInput = document.querySelector("#import-level-json");
const exportButton = document.querySelector("#export");
const visualThemeInput = document.querySelector("#visual-theme");
const visualQualityInput = document.querySelector("#visual-quality");
const postfxToggle = document.querySelector("#postfx-toggle");
const visualDebugToggle = document.querySelector("#visual-debug-toggle");
const applyVisualButton = document.querySelector("#apply-visual");
const toggleViewModeButton = document.querySelector("#toggle-view-mode");

const initialVisualConfig = readVisualConfig();
const game = new Game(canvas, updateStatus, initialVisualConfig);

let latestPackage = null;
let latestLevel = null;
let latestReport = null;

hydrateVisualControls(initialVisualConfig);
updateViewModeButton();
setIdleState();

function updateStatus(state) {
  const keyText = state.keys.length ? state.keys.join(", ") : "none";
  const lockText = state.locks.map((lock) => `${lock.id}:${lock.locked ? "locked" : "open"}`).join(" ");
  const modeText = state.viewMode === "god" ? "god" : "player";
  statusOutput.textContent = `mode=${modeText} | keys=${keyText} | locks=${lockText || "none"} | goal=${state.goalReached ? "reached" : "not yet"}`;
}

function setIdleState() {
  statusOutput.textContent = "status: waiting for import";
  etgOutput.textContent = "No level loaded.";
  reportOutput.textContent = "Import a Python level JSON (`level_*.json` or `level_package_*.json`) to start.";
  importStatusOutput.textContent = "No file loaded.";
  try {
    game.stop();
  } catch (err) {
    return;
  }
  updateViewModeButton();
}

function readVisualConfig() {
  const params = new URLSearchParams(window.location.search);
  return resolveVisualConfig({
    themeId: (params.get("visualTheme") || "manual").trim(),
    quality: (params.get("visualQuality") || "medium").trim(),
    postfx: parseBool(params.get("postfx"), true),
    debug: parseBool(params.get("visualDebug"), false),
  });
}

function hydrateVisualControls(config) {
  if (visualThemeInput) {
    const options = listVisualThemes();
    visualThemeInput.innerHTML = options
      .map((item) => `<option value="${item.id}">${item.id}</option>`)
      .join("");
    visualThemeInput.value = config.themeId;
  }
  if (visualQualityInput) visualQualityInput.value = config.quality;
  if (postfxToggle) postfxToggle.checked = config.postfx;
  if (visualDebugToggle) visualDebugToggle.checked = config.debug;
}

function isObject(v) {
  return v && typeof v === "object" && !Array.isArray(v);
}

function normalizePos(pos, fallback = { x: 0, y: 0, z: 0 }) {
  const src = isObject(pos) ? pos : fallback;
  return {
    x: Number(src.x) || 0,
    y: Number(src.y) || 0,
    z: Number(src.z) || 0,
  };
}

function normalizeLevelShape(raw) {
  const level = isObject(raw) ? { ...raw } : {};
  level.platforms = Array.isArray(level.platforms) ? level.platforms : [];
  level.enemies = Array.isArray(level.enemies) ? level.enemies : [];
  level.sweepers = Array.isArray(level.sweepers) ? level.sweepers : [];
  level.timed_gates = Array.isArray(level.timed_gates) ? level.timed_gates : [];
  level.bumpers = Array.isArray(level.bumpers) ? level.bumpers : [];
  level.showcase_characters = Array.isArray(level.showcase_characters) ? level.showcase_characters : [];
  level.keys = Array.isArray(level.keys) ? level.keys : [];
  level.locks = Array.isArray(level.locks) ? level.locks : [];
  level.checkpoints = Array.isArray(level.checkpoints) ? level.checkpoints : [];
  level.start = normalizePos(level.start, { x: 0, y: 0, z: 0 });
  level.goal = level.goal ? normalizePos(level.goal) : null;
  level.mapping = isObject(level.mapping) ? level.mapping : { node: {}, edge: {} };
  level.mapping.node = isObject(level.mapping.node) ? level.mapping.node : {};
  level.mapping.edge = isObject(level.mapping.edge) ? level.mapping.edge : {};
  level.anchors = isObject(level.anchors) ? level.anchors : {};
  level.meta = isObject(level.meta) ? level.meta : {};
  return level;
}

function extractImportedLevel(payload) {
  if (!isObject(payload)) {
    throw new Error("JSON root must be an object.");
  }

  if (isObject(payload.level) && Array.isArray(payload.level.platforms)) {
    const merged = { ...payload.level };
    if (!isObject(merged.mapping) && isObject(payload.mapping)) merged.mapping = payload.mapping;
    if (!isObject(merged.anchors) && isObject(payload.anchors)) merged.anchors = payload.anchors;
    if (!isObject(merged.etg) && isObject(payload.etg)) merged.etg = payload.etg;
    if (!isObject(merged.meta) && isObject(payload.meta)) merged.meta = payload.meta;
    return { level: normalizeLevelShape(merged), kind: "package" };
  }

  if (Array.isArray(payload.platforms) && isObject(payload.start)) {
    return { level: normalizeLevelShape(payload), kind: "level" };
  }

  throw new Error("Unsupported JSON. Expected Python level JSON or level_package JSON.");
}

function buildSummary(level, sourceKind, fileName) {
  return {
    source_file: fileName || null,
    payload_kind: sourceKind,
    generator_mode: level.meta?.generator_mode || null,
    platforms: level.platforms.length,
    enemies: level.enemies.length,
    sweepers: level.sweepers.length,
    timed_gates: level.timed_gates.length,
    bumpers: level.bumpers.length,
    showcase_characters: level.showcase_characters.length,
    keys: level.keys.length,
    locks: level.locks.length,
    checkpoints: level.checkpoints.length,
    etg_summary: level.etg ? summarizeETG(level.etg) : null,
  };
}

function loadLevelFromPayload(payload, fileName = "") {
  const { level, kind } = extractImportedLevel(payload);
  const report = validateAndRepair(level, {
    maxGap: 5.2,
    maxVertical: 3.2,
  });

  latestLevel = level;
  latestReport = report;
  latestPackage = buildExportPackage(level, report, {
    sampleDuration: 12,
    sampleStep: paperConfig.state_model.time_step_seconds,
  });
  applyLevelPreferredVisuals(level);

  etgOutput.textContent = JSON.stringify(buildSummary(level, kind, fileName), null, 2);
  reportOutput.textContent = formatReport(report);
  importStatusOutput.textContent = `Loaded ${kind}: ${fileName || "(in-memory)"}.`;

  game.stop();
  game.loadLevel(level);
  game.start();
  updateViewModeButton();
}

function applyLevelPreferredVisuals(level) {
  const preferred = level?.meta?.visual_theme;
  if (!preferred) return;
  const next = resolveVisualConfig({
    themeId: preferred,
    quality: visualQualityInput?.value || "high",
    postfx: Boolean(postfxToggle?.checked),
    debug: Boolean(visualDebugToggle?.checked),
  });
  if (visualThemeInput) visualThemeInput.value = next.themeId;
  if (visualQualityInput) visualQualityInput.value = next.quality;
  game.setVisualOptions(next);
}

function formatReport(report, perf = null) {
  if (!report) return "validation: unavailable";
  const lines = [];
  if (perf) {
    lines.push(
      `perf(ms): total=${perf.total_ms}, etg=${perf.etg_ms}, generate=${perf.generation_ms}, validate=${perf.validation_ms}, export=${perf.export_ms}`
    );
  }
  if (report.issues.length === 0 && report.fixes.length === 0 && report.warnings.length === 0) {
    lines.push("validation: ok");
    return lines.join("\n");
  }
  lines.push(`validation: ${report.status}`);
  for (const issue of report.issues) lines.push(`- issue: ${issue}`);
  for (const fix of report.fixes) lines.push(`- fix: ${fix}`);
  for (const warning of report.warnings) lines.push(`- warning: ${warning}`);
  return lines.join("\n");
}

function downloadPackage() {
  if (!latestPackage) return;
  const json = JSON.stringify(latestPackage, null, 2);
  const blob = new Blob([json], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const seed = latestPackage.meta?.seed || latestLevel?.meta?.seed || "imported";
  link.href = url;
  link.download = `level_package_${seed}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function parseBool(raw, fallback) {
  if (raw === null || raw === undefined || raw === "") return fallback;
  const v = String(raw).trim().toLowerCase();
  if (v === "1" || v === "true" || v === "yes" || v === "y" || v === "on") return true;
  if (v === "0" || v === "false" || v === "no" || v === "n" || v === "off") return false;
  return fallback;
}

function updateViewModeButton() {
  if (!toggleViewModeButton) return;
  const mode = game.getViewMode();
  toggleViewModeButton.textContent = mode === "god" ? "Switch to Player View" : "Switch to God View";
}

function applyVisualSettings() {
  const next = resolveVisualConfig({
    themeId: visualThemeInput?.value || "manual",
    quality: visualQualityInput?.value || "medium",
    postfx: Boolean(postfxToggle?.checked),
    debug: Boolean(visualDebugToggle?.checked),
  });

  const prevTheme = game.visualConfig?.themeId || "manual";
  game.setVisualOptions(next);

  if (next.themeId !== prevTheme) {
    game.setVisualTheme(next.themeId);
  } else {
    game.reloadVisuals(latestLevel || game.level || null);
  }

  const params = new URLSearchParams(window.location.search);
  params.set("visualTheme", next.themeId);
  params.set("visualQuality", next.quality);
  params.set("postfx", next.postfx ? "1" : "0");
  params.set("visualDebug", next.debug ? "1" : "0");
  window.history.replaceState({}, "", `${window.location.pathname}?${params.toString()}`);
}

async function readFileAsText(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Failed to read file."));
    reader.readAsText(file);
  });
}

async function onImportFileChanged(event) {
  const file = event.target?.files?.[0];
  if (!file) return;
  importStatusOutput.textContent = `Loading ${file.name} ...`;
  try {
    const raw = await readFileAsText(file);
    const payload = JSON.parse(raw);
    loadLevelFromPayload(payload, file.name);
  } catch (err) {
    importStatusOutput.textContent = `Import failed: ${err.message}`;
  } finally {
    event.target.value = "";
  }
}

importInput?.addEventListener("change", onImportFileChanged);
exportButton?.addEventListener("click", downloadPackage);
applyVisualButton?.addEventListener("click", applyVisualSettings);
toggleViewModeButton?.addEventListener("click", () => {
  game.toggleViewMode();
  updateViewModeButton();
});

autoLoadFromQuery();

async function autoLoadFromQuery() {
  const params = new URLSearchParams(window.location.search);
  const levelPath = params.get("level");
  if (!levelPath) return;
  importStatusOutput.textContent = `Loading ${levelPath} ...`;
  try {
    const response = await fetch(levelPath);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    loadLevelFromPayload(payload, levelPath);
  } catch (err) {
    importStatusOutput.textContent = `Auto-load failed: ${err.message}`;
  }
}
